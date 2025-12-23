# Env-first mode (Feature 021): No INI file needed
# Required env vars: STORAGE_PATHS, PUBLISHERS, OPENAI_SETTINGS + secrets
web: PYTHONPATH=publisher_v2/src uvicorn publisher_v2.web.app:app --host 0.0.0.0 --port $PORT
