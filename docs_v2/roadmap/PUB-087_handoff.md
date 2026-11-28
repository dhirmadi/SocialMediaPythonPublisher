# Implementation Handoff: PUB-087 — Verify the Database Server's TLS Certificate

**Hardened:** 2026-11-28
**Status:** Ready for implementation

## For Claude Code

### Test-first targets

| AC | Test file | Test name (exact function) |
|----|-----------|----------------------------|
| AC1 | `publisher_v2/tests/test_pub087_db_ca_certificate.py` | `test_pub087_ca_file_loads_as_single_certificate` |
| AC2 | `publisher_v2/tests/test_pub087_db_ca_certificate.py` | `test_pub087_ca_file_matches_pinned_fingerprint` |
| AC3 | `publisher_v2/tests/test_pub087_db_ca_certificate.py` | `test_pub087_ca_file_has_no_private_key` |
| AC4 | `publisher_v2/tests/test_db_connect_args.py` (extend) | `test_init_db_leaves_ssl_to_libpq_env_vars` |
| AC5 | `publisher_v2/tests/test_pub087_db_ca_certificate.py` | `test_pub087_configuration_doc_documents_pgssl_vars` |
| AC6 | — (no test; PR body states no issue is closed) | — |

- Resolve the repo root with `Path(__file__).resolve().parents[2]`, as `test_docs_commands.py` does.
- AC4 follows the existing pattern in `test_db_connect_args.py`:
  `patch("publisher_v2.db.create_async_engine", MagicMock())`, then assert
  `"ssl" not in create_engine.call_args.kwargs["connect_args"]`. It is a **characterization test that
  passes immediately**. Don't treat a green red-phase run as wrong; record it in the summary.
- AC3: assert `"PRIVATE KEY" not in text`. Never put a literal private-key header line in the test
  file.
- AC5: assert each of the five literals from the AC. The prose bullets are checked in review, not by
  the test.

### Mock boundaries

| External service | Mock strategy | Existing fixture |
|-----------------|---------------|------------------|
| Postgres / asyncpg | Not contacted. AC4 patches `publisher_v2.db.create_async_engine` | pattern in `publisher_v2/tests/test_db_connect_args.py` |
| Hetzner | None. AC1–AC3 read a committed file | — |

### Files likely touched

| Area | Files to modify | Files to create |
|-----|-----------------|-----------------|
| Certificate | — | `certs/hetzner-sqlca.crt`. Copy from the operator's Hetzner download (locally `~/.postgresql/hetzner_sqlca.pem`); AC2 is the integrity check |
| Docs | `docs_v2/05_Configuration/CONFIGURATION.md`: add `PGSSLMODE` and `PGSSLROOTCERT` rows to the §2.2 table next to `DATABASE_URL`, plus the cutover warning | — |
| Tests | `publisher_v2/tests/test_db_connect_args.py` | `publisher_v2/tests/test_pub087_db_ca_certificate.py` |

### Non-negotiables for this item

- [ ] Preview mode: N/A. No runtime code changes.
- [ ] Secrets: the certificate is public and has no private key (AC3). Do not commit any `*.pem`.
  The file is `.crt` because `.gitignore` excludes `*.pem`.
- [ ] Auth: N/A.
- [ ] No Python source changes under `publisher_v2/src/`. No new `os.environ` reads.
- [ ] Coverage: unchanged modules; the suite gate (≥85% overall) still passes.
- [ ] If `detect-private-key`, gitleaks or detect-secrets flags the certificate, stop and report it.
  Do not baseline it.

### Claude Code command

```text
/implement docs_v2/roadmap/PUB-087_db-tls-certificate-verification.md
```
