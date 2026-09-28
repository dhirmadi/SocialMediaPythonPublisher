#!/usr/bin/env bash
# PreToolUse hook (matcher: Bash): block `git commit` if the pytest suite is red.
# This is the one hard gate in this repo's hook set -- exits 2 to block the tool call.
# Fails open (exit 0) if pytest/uv are unavailable or the test dir doesn't exist yet,
# so it never blocks work in an environment that can't run tests.
#
# The suite runs in the repository the commit actually targets -- possibly a sibling
# git worktree, not $CLAUDE_PROJECT_DIR. Target directory precedence:
#   1. a leading `cd <dir> &&` in the command (relative paths resolve against the session cwd)
#   2. `git -C <dir> commit` in the command (same resolution)
#   3. the session cwd from the hook input (`.cwd`)
#   4. ${CLAUDE_PROJECT_DIR:-.}
# If the target is not inside a git repository, fall back to $CLAUDE_PROJECT_DIR.

set -uo pipefail

INPUT=$(cat 2>/dev/null)
COMMAND=$(jq -r '.tool_input.command // empty' <<<"$INPUT" 2>/dev/null)
SESSION_CWD=$(jq -r '.cwd // empty' <<<"$INPUT" 2>/dev/null)
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"

# A path argument: "double quoted", 'single quoted', or a bare word. Groups 2/3/4 hold the path.
PATH_ARG='("([^"]*)"|'"'"'([^'"'"']*)'"'"'|([^[:space:];&|]+))'
CD_RE='^[[:space:]]*cd[[:space:]]+'"$PATH_ARG"'[[:space:]]*&&'
GIT_C_RE='git[[:space:]]+-C[[:space:]]+'"$PATH_ARG"'[[:space:]]+commit'

# Only intercept commands that actually run `git commit` (including `git -C <dir> commit`).
if [[ "$COMMAND" != *"git commit"* ]] && ! [[ "$COMMAND" =~ $GIT_C_RE ]]; then
  exit 0
fi

# The quote-stripped path captured by the last regex match.
matched_path() {
  printf '%s' "${BASH_REMATCH[2]:-}${BASH_REMATCH[3]:-}${BASH_REMATCH[4]:-}"
}

# Expand a leading ~ and resolve a relative path against the session cwd.
resolve_path() {
  local p="$1"
  if [[ "$p" == "~" ]]; then
    p="$HOME"
  elif [[ "$p" == "~/"* ]]; then
    p="$HOME/${p#\~/}"
  fi
  if [[ "$p" != /* ]]; then
    p="${SESSION_CWD:-$PROJECT_DIR}/$p"
  fi
  printf '%s' "$p"
}

if [[ "$COMMAND" =~ $CD_RE ]]; then
  TARGET=$(resolve_path "$(matched_path)")
elif [[ "$COMMAND" =~ $GIT_C_RE ]]; then
  TARGET=$(resolve_path "$(matched_path)")
elif [[ -n "$SESSION_CWD" ]]; then
  TARGET="$SESSION_CWD"
else
  TARGET="$PROJECT_DIR"
fi

REPO_ROOT=$(git -C "$TARGET" rev-parse --show-toplevel 2>/dev/null) || REPO_ROOT=""
if [[ -z "$REPO_ROOT" ]]; then
  REPO_ROOT="$PROJECT_DIR"
fi

cd "$REPO_ROOT" || exit 0

# Skip if the test suite doesn't exist yet.
if [[ ! -d "publisher_v2/tests" ]]; then
  exit 0
fi

# Skip if uv is not available.
if ! command -v uv &>/dev/null; then
  exit 0
fi

# Let uv use this repo's own .venv -- a worktree must not run against the main checkout's venv.
unset VIRTUAL_ENV

OUTPUT=$(uv run pytest -q --no-header --tb=short 2>&1)
RESULT=$?

if [[ $RESULT -ne 0 ]]; then
  echo "Pre-commit gate: pytest suite is RED. Fix failing tests before committing." >&2
  echo "" >&2
  echo "$OUTPUT" | tail -30 >&2
  exit 2
fi

exit 0
