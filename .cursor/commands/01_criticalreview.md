This command has been superseded by the **`architect-reviewer`** subagent
(`.cursor/agents/architect-reviewer.md`).

Invoke it directly instead: point the `architect-reviewer` subagent at the document you want
reviewed (roadmap item, handoff doc, feature spec, design note, etc.). It carries the exact same
rubric this command used to paste inline, but as a real, isolated-context, read-only subagent
rather than prompt text run inline in your own conversation — which matters most when you're
reviewing something you just drafted yourself and need a genuinely independent pass.

This file is kept only so old references to `/01_criticalreview` still resolve to something.
`.cursor/skills/product-harden/SKILL.md` step 5 already invokes `architect-reviewer` directly;
don't reintroduce a copy-pasted rubric here or anywhere else — edit the subagent definition
instead.
