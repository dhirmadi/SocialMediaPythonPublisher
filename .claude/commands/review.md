---
description: Review staged or recent changes for quality, security, style, and spec compliance
allowed-tools: Bash, Read, Agent
---

Delegate this review to the `code-reviewer` subagent (`Agent` tool, `agent_type: code-reviewer`)
rather than reviewing inline — it runs in an isolated context with no anchoring on whatever you
just wrote, and its output format is already structured for this.

Give it:
- The scope: staged changes (`git diff --staged`), or the full working tree diff (`git diff`) if
  nothing is staged, or a specific branch (`git diff main...HEAD`) if the user names one.
- The relevant roadmap item path if the user names one, or ask `code-reviewer` to infer it from
  `docs_v2/roadmap/` if the diff makes it obvious.

If the diff touches `publisher_v2/web/**`, auth, secrets, or credential/config loading, also
invoke `security-auditor` (`agent_type: security-auditor`) on the same scope and merge its verdict
into the report.

Return both subagents' findings to the user verbatim (file:line, severity, issue, fix) plus the
overall verdict(s). Do not soften a blocker into a nit, and do not fix anything yourself unless
the user explicitly asks you to after seeing the report.
