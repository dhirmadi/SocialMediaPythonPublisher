# Social Media Publisher — V2 Documentation Set

Version: 2.3  
Last Updated: November 8, 2025  
Status: Approved for implementation

This folder contains the complete documentation to implement a brand‑new, modernized solution that preserves Dropbox for storage while upgrading AI, architecture, and publishing flows.

Contents:
- SYSTEM_DESIGN.md — System overview, goals, scope, user journeys
- ARCHITECTURE.md — Architecture, components, interfaces, deployment
- USER_FLOW.md — End‑to‑end flows, sequence diagrams, UX behaviors
- SPECIFICATION.md — Complete implementation spec (APIs, contracts, data models)
- AI_PROMPTS_AND_MODELS.md — Model choices, prompting strategies, evaluation
- CONFIGURATION.md — Environment, INI schema, pydantic validation
- PREVIEW_MODE.md — How to safely preview without publishing
- SECURITY_PRIVACY.md — Security posture, secrets, sessions, PII, logging
- NFRS.md — Non‑functional requirements and targets

Start with SYSTEM_DESIGN.md, then read SPECIFICATION.md and ARCHITECTURE.md. AI coders can safely implement using SPECIFICATION.md alone, with ARCHITECTURE.md and CONFIGURATION.md as reference.

New in v2.4:
- Stable‑Diffusion‑ready caption sidecar (`<image>.txt`) generated alongside normal captions
- Moves with image on archive; preview shows `sd_caption` without side effects

Utility scripts:
- A standalone Heroku/Hetzner provisioning script lives under `/scripts/heroku_hetzner_clone.py` to clone the `fetlife-prod` Heroku app, attach a `<name>.shibari.photo` domain, update the `FETLIFE_INI` `image_folder`, and create the matching Hetzner DNS CNAME record. See the script's `--help` output for usage.


