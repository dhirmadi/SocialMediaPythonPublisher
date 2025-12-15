## Social Media Python Publisher — V2

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Modern, reliable, and privacy‑aware publishing pipeline for photos. V2 uses OpenAI (vision + copy), Dropbox for storage, and pluggable publishers (Email/FetLife, Telegram, Instagram). It’s built with uv, strict config validation, retries/backoff, rate limiting, SHA256 de‑duplication, and a safe Preview Mode.

---

### 📚 Documentation (Start Here)

- V2 docs live in `docs_v2/`:
  - Overview: `docs_v2/01_Overview/README.md` (start here)
  - Architecture: `docs_v2/03_Architecture/ARCHITECTURE.md`, `docs_v2/03_Architecture/SYSTEM_DESIGN.md`
  - Specification & configuration: `docs_v2/02_Specifications/SPECIFICATION.md`, `docs_v2/05_Configuration/CONFIGURATION.md`
  - Features & change requests: `docs_v2/08_Features/`
  - AI prompts & models: `docs_v2/07_AI/AI_PROMPTS_AND_MODELS.md`
  - Preview mode: `docs_v2/08_Features/PREVIEW_MODE.md`
  - Reviews & testing: `docs_v2/09_Reviews/REVIEW_SUMMARY.md`, `docs_v2/10_Testing/`
- V1 docs have been archived to `docs_v1/`

---

### 🚀 What You Get (Highlights)

- OpenAI‑only AI strategy with separate models for best cost/quality
- Dropbox as source of truth for images; server‑side archive moves and sidecar handling
- Platform‑aware caption formatting (length, hashtags, constraints)
- Stable‑Diffusion‑ready caption sidecar `.txt` files and extended JSON analysis metadata
- SHA256 de‑duplication to avoid reposting the same image
- Tenacity‑based retries and async rate limiting on external calls
- Secure temp files (0600), secrets via `.env`, structured JSON logs
- Optional FastAPI web interface for previewing, analyzing, and publishing with admin‑only controls
- CLI flags for `--select`, `--dry-publish`, and safe `--preview`
- Email/FetLife publisher with caption placement control, subject prefixes, no hashtags, ≤240 chars, punctuation sanitization, and optional confirmation email with tags

---

### 🚀 Quick Start (uv)

#### Prerequisites
- Python 3.12 (3.9–3.11 supported per `pyproject.toml`)
- uv

#### Install
```bash
uv sync
```

#### Run (Preview)
```bash
make preview-v2 CONFIG=configfiles/fetlife.ini
```

#### Run (Live)
```bash
make run-v2
```

**Full Configuration Guide:** See `docs_v2/05_Configuration/CONFIGURATION.md` for:
- Complete secrets, dynamic config, and static config reference
- OpenAI model selection and prompt customization
- FetLife email options and platform limits
- Feature toggles and internationalization

---

### 🧭 CLI Flags

- `--config <file.ini>` (required)
- `--select <filename>` select an exact image in Dropbox folder
- `--dry-publish` run end‑to‑end but skip platform publishing + archiving
- `--preview` human‑readable output; no platform calls, no archive, no cache updates

Preview mode shows: image details (temp link, SHA256), vision analysis (description/mood/tags/safety), final caption with length, per‑platform formatting, and for Email/FetLife the subject preview, caption placement, and subject mode.

---

### ⚙️ Configuration (Essentials)

Publisher V2 uses a **three-layer configuration model**:

1. **Secrets** (`.env` only) — API keys, passwords, tokens
2. **Dynamic Config** (`.env` + INI) — Feature toggles, platform settings, folders
3. **Static Config** (YAML files) — AI prompts, platform limits, UI text

**Secrets in `.env` (git‑ignored):**
- `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`, `DROPBOX_REFRESH_TOKEN`
- `OPENAI_API_KEY`
- Optional: `EMAIL_PASSWORD`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHANNEL_ID`, `INSTA_PASSWORD`

**INI example (excerpt):**

```ini
[Dropbox]
image_folder = /Photos/bondage_fetlife
archive = archive

[Content]
hashtag_string =; ignored for Email/FetLife in V2
archive = true
debug = false
telegram = false
instagram = false
fetlife = true

[openAI]
vision_model = gpt-4o
caption_model = gpt-4o-mini
system_prompt = You write captions for FetLife email posts in a kinky, playful, respectful tone; no hashtags or emojis; ≤240 chars; end with an open question.
role_prompt = Using the image analysis (description, mood, tags), write 1–2 short sentences in that tone; no hashtags; ≤240; end with an open question.

[Email]
sender = you@gmail.com
recipient = 12345-abc@upload.fetlife.com
smtp_server = smtp.gmail.com
smtp_port = 587
; FetLife specifics
caption_target = subject         ; subject | body | both
subject_mode = normal            ; normal | private | avatar
confirmation_to_sender = true
confirmation_tags_count = 5
confirmation_tags_nature = short, lowercase, human-friendly topical nouns; no hashtags; no emojis
```

---

### 🗃️ Repository Layout
- `publisher_v2/` — V2 application and tests
- `docs_v2/` — V2 documentation (source of truth)
- `code_v1/` — Archived V1 code
- `docs_v1/` — Archived V1 documentation

---

### 🧩 Dependencies

- uv is the canonical dependency manager (`pyproject.toml`, `uv.lock`).
- Need pip files? Export from uv:
  - `make export-reqs` → generates `requirements.txt`
  - `make export-reqs-dev` → generates `requirements-dev.txt`

---

### 🔐 Security & Privacy
- Secrets live in `.env`; never in git
- Structured logging with redaction (e.g., `sk-` keys)
- Temp files are 0600 and cleaned up; session files are git‑ignored
- Cursor/IDE artifacts and local scripts are ignored in `.gitignore`

---

### 🧪 Testing
- `uv run pytest -v` (async tests supported)
- Or `make test` for coverage + report

---

### 🌐 V2 Web Interface (MVP)

An optional minimal web interface is available, built on FastAPI:

- Shows a random image from the configured Dropbox folder.
- Lets you trigger AI analysis & caption generation (admin‑only).
- Lets you publish using the existing publishers (admin‑only).
- Uses HTTP auth plus a short‑lived admin session cookie to protect mutating actions.
- Mobile‑first, single‑page UI with admin‑only controls hidden for non‑admin users.

To run locally:

```bash
export CONFIG_PATH=configfiles/fetlife.ini
uv run uvicorn publisher_v2.web.app:app --reload
```

Then open `http://localhost:8000` in your browser. See `docs_v2/08_Features/08_01_Feature_Request/005_web-interface-mvp.md` and related change requests under `docs_v2/08_Features/08_04_ChangeRequests/005/` for details.

---

### 📄 License

MIT License — see [LICENSE](LICENSE).