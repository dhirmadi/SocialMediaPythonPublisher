# Epics — Social Media Publisher V2

This folder contains **cross-feature initiatives** that span multiple components (web UI, orchestration, storage, auth, deployment), and are too large to fit cleanly into a single `08_Features/<id>_*` feature.

Epics should:
- Define **goal / non-goals**
- Capture **decisions** and **constraints**
- Specify **contracts** between systems (especially with `platform-orchestrator`)
- Provide a **phased migration plan** and **acceptance criteria**
- Link to related features under `docs_v2/08_Features/`

## Index
- `001_single-dyno_multi-tenant_domain-based_runtime-config.md` — Move from many tenant apps/dynos to a single web fleet with wildcard domain routing and orchestrator-sourced runtime config.


