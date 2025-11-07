# Migration Plan — V1 to V2

Version: 2.0  
Last Updated: November 7, 2025

## 1. Approach
- V2 is implemented alongside V1 (`publisher_v2/`), leaving V1 intact.
- Config compatibility: same INI and `.env` keys where possible; renamed secret `DROPBOX_APP_SECRET` supported.

## 2. Steps
1) Implement V2 per SPECIFICATION.md and ARCHITECTURE.md  
2) Dry‑run in debug against sample folder  
3) Point cron to V2 CLI for a single scheduled slot (canary)  
4) Monitor logs and results  
5) Migrate all schedules to V2 after canary success  
6) Keep V1 for a grace period; then decommission

## 3. Rollback
- Repoint cron to V1
- Disable V2 virtualenv or container

## 4. Post‑Cutover
- Remove V1‑only scripts/jobs
- Archive V1 docs to `/docs_v1_archive` if desired


