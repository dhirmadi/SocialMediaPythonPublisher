# Web layer (FastAPI admin UI)

- Single-page app: `templates/index.html` (vanilla JS + CSS, no build step).
- Routes live in `app.py` and `routers/auth.py` — keep them thin, delegate to `service.py`.
- Auth: `auth.py` manages Bearer/Basic auth + admin cookie (`pv2_admin`).
- Admin-only UI elements must be **hidden** (not disabled) for non-admin users.
- Mobile-first responsive design; no horizontal scroll on 320–768px.
- Dark-red admin theme; maintain accessible contrast.
- Do not add new JS frameworks or build toolchains.
