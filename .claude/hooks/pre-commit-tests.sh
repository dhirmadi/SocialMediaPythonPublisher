#!/usr/bin/env bash
# PreToolUse hook (matcher: Bash): block `git commit` if the pytest suite is red.
# This is the one hard gate in this repo's hook set -- exits 2 to block the tool call.
# Fails open (exit 0) if pytest/uv are unavailable or the test dir doesn't exist yet,
# so it never blocks work in an environment that can't run tests.

set -uo pipefail

COMMAND=$(jq -r '.tool_input.command // empty' < /dev/stdin 2>/dev/null)

# Only intercept commands that actually run `git commit`.
if [[ "$COMMAND" != *"git commit"* ]]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0

# Skip if the test suite doesn't exist yet.
if [[ ! -d "publisher_v2/tests" ]]; then
  exit 0
fi

# Skip if uv is not available.
if ! command -v uv &>/dev/null; then
  exit 0
fi

OUTPUT=$(uv run pytest -q --no-header --tb=short 2>&1)
RESULT=$?

if [[ $RESULT -ne 0 ]]; then
  echo "Pre-commit gate: pytest suite is RED. Fix failing tests before committing." >&2
  echo "" >&2
  echo "$OUTPUT" | tail -30 >&2
  exit 2
fi

exit 0
