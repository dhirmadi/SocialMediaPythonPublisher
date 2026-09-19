---
description: "V2 package layout, module boundaries, and architectural constraints"
paths:
  - "publisher_v2/src/publisher_v2/**"
---

# V2 architecture constraints

- CLI entrypoint: `publisher_v2/src/publisher_v2/app.py`.
- Config loading + Pydantic v2 models: `publisher_v2/src/publisher_v2/config/`.
- Orchestration: `WorkflowOrchestrator` in `publisher_v2.core.workflow` — all orchestration lives here.
- Platform publishers implement the `Publisher` interface in `publisher_v2.services.publishers.base`.
- AI integration uses `AIService` → `VisionAnalyzerOpenAI` + `CaptionGeneratorOpenAI`. Vision uses `response_format={"type": "json_object"}`.
- Rate limits: `AsyncRateLimiter` — keep defaults unless explicitly asked to change.
- Storage: Dropbox is source of truth; prefer server-side moves to archive.
- Keep new modules consistent with existing layout; do not create parallel trees.
- If your change adds a new module boundary, external dependency, or datastore, or makes a
  backward-incompatible contract change, flag it for an ADR (`docs_v2/03_Architecture/adr/`,
  drafted in Cursor via `/product-adr`) — don't just note it in the summary doc and move on.
