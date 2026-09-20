---
description: Run V2 in preview mode (no publishing side effects)
allowed-tools: Bash, Read
---

Run the V2 publisher in preview mode. Configuration is env-first (`.env` plus `STORAGE_PATHS`, `PUBLISHERS`, `OPENAI_SETTINGS`); if $ARGUMENTS is provided, pass it through as extra CLI flags (for example `--select <filename>`).

```bash
PYTHONPATH=publisher_v2/src uv run python publisher_v2/src/publisher_v2/app.py --preview $ARGUMENTS
```

Report the preview output. Remind the user that preview mode never publishes or mutates state.
