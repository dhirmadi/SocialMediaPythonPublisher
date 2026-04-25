# Security & Privacy — Social Media Publisher V2

Version: 2.0  
Last Updated: April 25, 2026

## 1. Secrets and Sessions
- Secrets only in `.env`; never in INI; never in logs
- Redaction middleware for logs (sk-*, r8_*, bot tokens, passwords)
- Instagram sessions encrypted at rest (Fernet) where practical; always git‑ignored
- Orchestrator mode: per-tenant secrets are resolved on-demand via the orchestrator credentials endpoint and must never be persisted to disk

## 2. Filesystem Hygiene
- Temp files created 0600; deleted in finally blocks
- Optional secure overwrite for sensitive data (config flag)
- Archive/move operations performed via the configured storage backend API (Dropbox or managed storage); no long-lived local persistence

## 3. Network and API
- TLS by default; timeouts set; retries with backoff
- Rate limits per vendor; avoid bans
- No long‑term public hosting of user images for analysis (use temporary links)
- Web admin endpoints that mutate state remain protected by HTTP auth + server-enforced admin session TTL (cookie)

## 4. Privacy
- No PII stored beyond what user provides (sender/recipient email)
- Captions avoid personal data extraction by design
- Logs exclude asset content; contain only IDs and concise summaries

## 5. Compliance‑ready Practices
- Clear separation between secrets and config
- Automated checks (safety, bandit) in CI/CD (future)


