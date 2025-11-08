# Social Media Python Publisher — V2

[![Python Version](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

State-of-the-art social media publisher with OpenAI-only AI, Dropbox storage, and pluggable publishers (Email/FetLife, Telegram, Instagram) — redesigned as V2 with Poetry, typed config, retries, rate limiting, SHA256 dedup, preview mode, and platform-aware formatting.

---

## 📚 Documentation

- V2 docs: see `docs_v2/`
  - `docs_v2/README.md` (start here)
  - `docs_v2/SYSTEM_DESIGN.md`, `ARCHITECTURE.md`, `SPECIFICATION.md`, `CONFIGURATION.md`
  - `docs_v2/PREVIEW_MODE.md`, `AI_PROMPTS_AND_MODELS.md`, `REVIEW_SUMMARY.md`
- V1 docs have been archived to `docs_v1/`

---

## 🚀 Quick Start (V2)

### Prerequisites
- Python 3.12
- Poetry

### Install
```bash
poetry install
```

### Run (Preview)
```bash
make preview-v2 CONFIG=configfiles/fetlife.ini
```

### Run (Live)
```bash
make run-v2
```

See `docs_v2/CONFIGURATION.md` for config schema, Email/FetLife behavior (subject prefix, caption placement), and model selection.

---

## 🗃️ Repository Layout
- `publisher_v2/` — V2 application and tests
- `docs_v2/` — V2 documentation (source of truth)
- `code_v1/` — Archived V1 code
- `docs_v1/` — Archived V1 documentation

---

## 📄 License

MIT License — see [LICENSE](LICENSE).