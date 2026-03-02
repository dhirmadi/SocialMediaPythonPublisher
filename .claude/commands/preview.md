---
description: Run V2 in preview mode (no publishing side effects)
allowed-tools: Bash, Read
---

Run the V2 publisher in preview mode. If $ARGUMENTS is provided, use it as the config path; otherwise default to `configfiles/fetlife.ini`.

```bash
CONFIG="${ARGUMENTS:-configfiles/fetlife.ini}"
PYTHONPATH=publisher_v2/src uv run python publisher_v2/src/publisher_v2/app.py --config "$CONFIG" --preview
```

Report the preview output. Remind the user that preview mode never publishes or mutates state.
