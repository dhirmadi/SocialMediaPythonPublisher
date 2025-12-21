# Social Media Publisher — V2 Documentation Set

Version: 2.3  
Last Updated: December 21, 2025  
Status: Approved for implementation

This folder contains the complete documentation to implement a brand‑new, modernized solution that preserves Dropbox for storage while upgrading AI, architecture, and publishing flows.

Contents:
- `03_Architecture/SYSTEM_DESIGN.md` — System overview, goals, scope, user journeys
- `03_Architecture/ARCHITECTURE.md` — Architecture, components, interfaces, deployment
- `02_Specifications/USER_FLOW.md` — End‑to‑end flows, sequence diagrams, UX behaviors
- `02_Specifications/SPECIFICATION.md` — Complete implementation spec (APIs, contracts, data models)
- `07_AI/AI_PROMPTS_AND_MODELS.md` — Model choices, prompting strategies, evaluation
- `05_Configuration/CONFIGURATION.md` — Environment, INI schema, pydantic validation
- `08_Features/000_preview_mode/000_feature.md` — Preview mode guarantees (no side effects)
- `04_Security_Privacy/SECURITY_PRIVACY.md` — Security posture, secrets, sessions, PII, logging
- `06_NFRs/NFRS.md` — Non‑functional requirements and targets

Start with SYSTEM_DESIGN.md, then read SPECIFICATION.md and ARCHITECTURE.md. AI coders can safely implement using SPECIFICATION.md alone, with ARCHITECTURE.md and CONFIGURATION.md as reference.

Notable capabilities:
- Stable‑Diffusion‑ready caption sidecar (`<image>.txt`) generated alongside normal captions
- Moves with image on archive; preview shows `sd_caption` without side effects

Utility scripts:
- A standalone Heroku/Hetzner provisioning script lives under `/scripts/heroku_hetzner_clone.py` to clone the `fetlife-prod` Heroku app, attach a `<name>.shibari.photo` domain, update the `FETLIFE_INI` `image_folder`, and create the matching Hetzner DNS CNAME record. See the script's `--help` output for usage.


