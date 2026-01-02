# Social Media Publisher — V2 Documentation Set

Version: 2.3  
Last Updated: December 30, 2025  
Status: Canonical docs (live; maintained)

**Canonical entrypoint:** `docs_v2/README.md`

This folder provides a reading-oriented overview of the V2 documentation set.

Contents:
- `03_Architecture/SYSTEM_DESIGN.md` — System overview, goals, scope, user journeys
- `03_Architecture/ARCHITECTURE.md` — Architecture, components, interfaces, deployment
- `02_Specifications/USER_FLOW.md` — End‑to‑end flows, sequence diagrams, UX behaviors
- `02_Specifications/SPECIFICATION.md` — Complete implementation spec (APIs, contracts, data models)
- `02_Specifications/ORCHESTRATOR_SERVICE_API_INTEGRATION_GUIDE.md` — Orchestrator service-to-service API integration (when using platform orchestrator)
- `02_Specifications/ORCHESTRATOR_RUNTIME_CONFIG_SCHEMA_REFERENCE.md` — Canonical orchestrator runtime config schema + GUI validation rules
- `07_AI/AI_PROMPTS_AND_MODELS.md` — Model choices, prompting strategies, evaluation
- `05_Configuration/CONFIGURATION.md` — Configuration model (orchestrator-default), env/INI compatibility, validation
- `08_Epics/000_v2_foundation/000_preview_mode/000_feature.md` — Preview mode guarantees (no side effects)
- `04_Security_Privacy/SECURITY_PRIVACY.md` — Security posture, secrets, sessions, PII, logging
- `06_NFRs/NFRS.md` — Non‑functional requirements and targets

Suggested reading order:

1. `docs_v2/README.md` (navigation)
2. `03_Architecture/SYSTEM_DESIGN.md`
3. `03_Architecture/ARCHITECTURE.md`
4. `05_Configuration/CONFIGURATION.md` (orchestrator-default)
5. `02_Specifications/SPECIFICATION.md` (implementation details)

Notable capabilities:
- Stable‑Diffusion‑ready caption sidecar (`<image>.txt`) generated alongside normal captions
- Moves with image on archive; preview shows `sd_caption` without side effects

Utility scripts:
- A standalone Heroku/Hetzner provisioning script lives under `/scripts/heroku_hetzner_clone.py` to clone the `fetlife-prod` Heroku app, attach a `<name>.shibari.photo` domain, update the `FETLIFE_INI` `image_folder`, and create the matching Hetzner DNS CNAME record. See the script's `--help` output for usage.


