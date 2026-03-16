---
paths:
  - "docs_v2/**"
---

# Documentation authoring (V2)

- `docs_v2/` is the canonical documentation tree. `docs_v1/` is archived — never edit.
- **Roadmap items** live at `docs_v2/roadmap/PUB-NNN_slug.md` (active) or `docs_v2/roadmap/archive/PUB-NNN_slug.md` (shipped).
- When changing user-visible behavior, config semantics, or API contracts, update the relevant docs in `docs_v2/`.
- Preserve endpoint contracts in `docs_v2/03_Architecture/ARCHITECTURE.md` unless a change request says otherwise.
- Prefer small, high-signal doc updates; don't rewrite large sections unless asked.
