## Social Media Python Publisher — V2

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Modern, reliable, and privacy‑aware publishing pipeline for photos. V2 uses OpenAI (vision + copy), Dropbox for storage, and pluggable publishers (Email/FetLife, Telegram, Instagram). It’s built with Poetry, strict config validation, retries/backoff, rate limiting, SHA256 de‑duplication, and a safe Preview Mode.

---

### 📚 Documentation (Start Here)

- V2 docs: see `docs_v2/`
  - `docs_v2/README.md` (start here)
  - `docs_v2/SYSTEM_DESIGN.md`, `ARCHITECTURE.md`, `SPECIFICATION.md`, `CONFIGURATION.md`
  - `docs_v2/PREVIEW_MODE.md`, `AI_PROMPTS_AND_MODELS.md`, `REVIEW_SUMMARY.md`
- V1 docs have been archived to `docs_v1/`

---

### 🚀 What You Get (Highlights)

- OpenAI‑only AI strategy with separate models for best cost/quality
- Dropbox as source of truth for images; server‑side archive moves
- Platform‑aware caption formatting (length, hashtags, constraints)
- SHA256 de‑duplication to avoid reposting the same image
- Tenacity‑based retries and async rate limiting on external calls
- Secure temp files (0600), secrets via `.env`, structured JSON logs
- CLI flags for `--select`, `--dry-publish`, and safe `--preview`
- Email/FetLife publisher with caption placement control, subject prefixes, no hashtags, ≤240 chars, punctuation sanitization, and optional confirmation email with tags

---

### 🚀 Quick Start (Poetry)

#### Prerequisites
- Python 3.12
- Poetry

#### Install
```bash
poetry install
```

#### Run (Preview)
```bash
make preview-v2 CONFIG=configfiles/fetlife.ini
```

#### Run (Live)
```bash
make run-v2
```

See `docs_v2/CONFIGURATION.md` for full schema, OpenAI model selection, and FetLife email options.

---

### 🧭 CLI Flags

- `--config <file.ini>` (required)
- `--select <filename>` select an exact image in Dropbox folder
- `--dry-publish` run end‑to‑end but skip platform publishing + archiving
- `--preview` human‑readable output; no platform calls, no archive, no cache updates

Preview mode shows: image details (temp link, SHA256), vision analysis (description/mood/tags/safety), final caption with length, per‑platform formatting, and for Email/FetLife the subject preview, caption placement, and subject mode.

---

### ⚙️ Configuration (Essentials)

Put secrets in `.env` (git‑ignored):
- `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`, `DROPBOX_REFRESH_TOKEN`
- `OPENAI_API_KEY`
- Optional: `EMAIL_PASSWORD`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHANNEL_ID`, `INSTA_PASSWORD`

INI example (excerpt):

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

- Poetry is the canonical dependency manager (`pyproject.toml`, `poetry.lock`).
- Need pip files? Export from Poetry:
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
- `poetry run pytest -v` (async tests supported)
- Or `make test` for coverage + report

---

### 🌐 V2 Web Interface (MVP)

An optional minimal web interface is available, built on FastAPI:

- Shows a random image from the configured Dropbox folder.
- Lets you trigger AI analysis & caption generation.
- Lets you publish using the existing publishers.

To run locally:

```bash
export CONFIG_PATH=configfiles/fetlife.ini
poetry run uvicorn publisher_v2.web.app:app --reload
```

Then open `http://localhost:8000` in your browser.

---

### 📄 License

MIT License — see [LICENSE](LICENSE).