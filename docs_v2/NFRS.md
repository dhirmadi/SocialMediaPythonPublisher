# Non‑Functional Requirements — Social Media Publisher V2

Version: 2.0  
Last Updated: November 7, 2025

## 1. Performance
- E2E latency: < 30s typical per post (single image)
- Caption generation: < 3s typical with 4o‑mini
- Parallel platform publish: all complete within 10s typical

## 2. Reliability
- Retries with exponential backoff on transient errors
- Any‑success archive policy; partial failures recorded

## 3. Security
- Zero secrets in logs or VCS
- Sessions encrypted at rest (if stored)

## 4. Maintainability
- > 80% coverage on core modules
- Lint, type check clean
- Modular, pluggable publishers

## 5. Operability
- Structured logs; correlation IDs
- Simple CLI and clear error messages


