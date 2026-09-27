---
name: ci-tooling-dedup-review-traps
description: PUB-084 wave 2b (#295) review - dropping a duplicate workflow step can drop its trigger set (cron, extra branches); sandbox refuses heredocs containing pipes or dot-github paths
metadata:
  type: project
---

Reviewing CI dedup (removing a step that "duplicates" one in another workflow): compare the `on:` blocks of both files, not just PR/push-to-main. In #295 the removed security-scan TruffleHog also ran on the weekly cron (full-history verified scan) and on develop; secret-scan.yml only fires on pull_request and push to main.

**Why:** the AC only asserted PR and push-to-main, so the tests passed while the scheduled scan silently disappeared.

**How to apply:** for every deleted CI step, list each trigger of its workflow and name the surviving step that covers it.

Tooling note: in the worktree-isolated sandbox, Bash heredocs whose body contains a pipe char or a dot-github path are refused as "too complex". For mutation checks on workflow files use cp to a scratch backup, then `perl -0pi -e` / `sed -i ""` per mutation, run pytest, cp back, and cmp against the backup. Pre-commit via a printf-written script in the scratchpad works. See [[mutation-check-review-technique]].
