---
paths:
  - "publisher_v2/src/publisher_v2/**caption**"
  - "publisher_v2/src/publisher_v2/**sidecar**"
  - "publisher_v2/src/publisher_v2/utils/**"
---

# Caption & sidecar rules (do not break)

- Keep existing JSON fields untouched; **add** new fields (e.g. `sd_caption`) — never rename or repurpose.
- Write `<image>.txt` alongside the image containing only `sd_caption`; overwrite on reprocessing.
- Ensure caption files move with the image on archive.
- Caption style: PG-13 fine-art; include pose, styling/material, lighting, mood.
- Respect sidecar schemas and extended analysis fields documented in:
  - `docs_v2/roadmap/archive/PUB-003_expanded-vision-analysis.md`
  - `docs_v2/roadmap/archive/PUB-004_caption-extended-metadata.md`
- Do not change field names/semantics without updating specs, tests, and migration notes.
