# PUB-087: Verify the Database Server's TLS Certificate

| Field | Value |
|-------|-------|
| **ID** | PUB-087 |
| **Category** | Config |
| **Priority** | P1 |
| **Effort** | S |
| **Status** | Not Started |
| **Dependencies** | — (paired with orchestrator `SEC_08`; neither blocks the other) |

## User Story

As a platform operator, I want the publisher to verify its Postgres server's certificate when the
database moves off Heroku, so that a connection crossing the public internet cannot be silently
intercepted.

## Problem

The publisher database is moving from Heroku Postgres (`essential-0`, attached to `org-prod`) to a
Hetzner-managed Postgres 17 server (`n0ov.your-database.de`, database and role `publisher`). Hetzner
requires TLS and signs server certificates with its own self-signed CA. That CA is
`CN=sql.your-server.de, O=Hetzner Online AG, OU=Databases`, valid until 2032-06-04, SHA-256
fingerprint `0C:2F:66:73:68:A8:03:14:E2:45:5E:1D:FF:FE:89:64:85:4D:9D:11:2F:C6:F5:A3:68:CF:D2:AE:93:6A:74:27`.

Today the publisher encrypts but does not verify. Neither `publisher_v2.db.init_db` nor
`publisher_v2/alembic/env.py` passes an `ssl` argument. asyncpg's default `prefer` negotiates TLS
because the server demands it, but checks neither the certificate nor the hostname. Heroku cannot
allow-list by source IP, so the server accepts connection attempts from the whole internet.

**No code change is needed to close this.** asyncpg honours libpq's `PGSSLMODE` and `PGSSLROOTCERT`
environment variables whenever no explicit `ssl` argument is passed. This was verified on
2026-11-28 against the Hetzner server with the locked asyncpg 0.31.0 and SQLAlchemy 2.0.49, through
`create_async_engine`:

| Setting | Result |
|---|---|
| No variables (today) | Connects, TLSv1.3, **unverified** |
| `PGSSLMODE=verify-full`, `PGSSLROOTCERT=<Hetzner CA>` | Connects |
| `PGSSLMODE=verify-full`, `PGSSLROOTCERT=<certifi bundle>` | `SSLCertVerificationError: unable to get local issuer certificate` |
| `verify-full`, right CA, host given as the raw IP | `SSLCertVerificationError: IP address mismatch` |
| `?sslmode=verify-full` in the URL | `TypeError: connect() got an unexpected keyword argument 'sslmode'` |

What is missing is a CA file on the dyno for `PGSSLROOTCERT` to point at, plus documentation of the
two variables.

## Desired Outcome

The Hetzner CA ships in the slug. After cutover, setting `PGSSLMODE=verify-full` and
`PGSSLROOTCERT=/app/certs/hetzner-sqlca.crt` makes every publisher connection refuse a server whose
certificate is not signed by that CA for the `DATABASE_URL` host. That covers the web process and
release-phase migrations; Heroku config vars apply to both. No Python changes.

## Scope

**In scope:**
- Commit the Hetzner CA as `certs/hetzner-sqlca.crt` at the repo root.
  - Use the `.crt` extension: `.gitignore` excludes `*.pem`, and CLAUDE.md forbids committing
    `*.pem`, a rule aimed at private keys.
  - The file is a public certificate with no private key. It contains only the PEM block, starting
    at byte 0, with no `openssl x509 -text` preamble.
- A test that guards the file.
- Document `PGSSLMODE` / `PGSSLROOTCERT` in `docs_v2/05_Configuration/CONFIGURATION.md`, including
  that they must be set **at cutover, not before**.

**Out of scope:**
- Any change to `publisher_v2/db/` or `publisher_v2/alembic/env.py`.
- A new configuration variable (an earlier draft proposed `DATABASE_SSL_ROOT_CERT`; dropped as
  redundant with the libpq variables asyncpg already reads).
- The data migration and cutover. That is an operator runbook.
- Client-certificate (mTLS) authentication.

## Acceptance Criteria

FP = `0C:2F:66:73:68:A8:03:14:E2:45:5E:1D:FF:FE:89:64:85:4D:9D:11:2F:C6:F5:A3:68:CF:D2:AE:93:6A:74:27`

- AC1: Given the repo root, when `certs/hetzner-sqlca.crt` is read, then it contains exactly one
  `-----BEGIN CERTIFICATE-----` block, and `ssl.create_default_context(cafile=<that path>)` loads it
  without raising.
- AC2: Given the same file, when the SHA-256 digest of its DER encoding is computed and formatted as
  colon-separated upper-case hex, then it equals FP.
- AC3: Given the same file, when its text is searched, then it contains no `PRIVATE KEY` substring.
- AC4: Given `DATABASE_URL` is set and no other DB setting changes, when `publisher_v2.db.init_db`
  creates the engine, then `connect_args` has no `ssl` key. If code ever passes `ssl`, asyncpg ignores
  `PGSSLMODE`/`PGSSLROOTCERT` and verification is silently lost; this guards against that.
  This is a characterization test: it passes on day one, because the existing assertion in
  `test_db_connect_args.py` already pins `connect_args`. It locks the behaviour in under its own
  name.
- AC5: Given this item ships, when `docs_v2/05_Configuration/CONFIGURATION.md` is read, then it
  contains each of these literal strings: `PGSSLMODE=verify-full`,
  `PGSSLROOTCERT=/app/certs/hetzner-sqlca.crt`, `sslmode=`, `ssl=` and `fetlife-staging-org`. The
  test asserts only the literals. The reviewer checks that the surrounding text says:
  - the variables are per app, and go only on apps whose `DATABASE_URL` points at Hetzner. They go
    on `fetlife-production-org` after cutover, not on `fetlife-staging-org` while it uses Heroku
    Postgres. On a Heroku-Postgres app they break the connection;
  - they are set in the same release as the Hetzner `DATABASE_URL`;
  - neither `sslmode=` nor `ssl=` may appear in `DATABASE_URL`. `sslmode=` raises a `TypeError`, and
    `ssl=` becomes an explicit `ssl` argument that overrides `PGSSLMODE`.
- AC6: Given this item ships, when its implementing PR merges, then no GitHub issue is closed. None
  exists, and none is needed: the item is tracked here and in the paired orchestrator `SEC_08`.

## Implementation Notes

- AC2 computes the fingerprint with `ssl.PEM_cert_to_DER_cert` plus `hashlib.sha256`; no new
  dependency.
- **Preview mode:** not affected. No runtime code changes, and preview never opens the DB pool.
- **Do not add `os.environ` reads for `PGSSLMODE` or `PGSSLROOTCERT`** in publisher code. asyncpg
  reads them itself, and `publisher_v2/tests/test_env_centralization.py` pins every variable the code reads.
- `publisher_v2/alembic/env.py` builds its engine from the ini section with no `connect_args`, so it
  already leaves `ssl` unset. No test is needed there, but do not add `connect_args` to it.
- Copy the file from the operator's Hetzner download, not from this spec. The fingerprint in AC2
  is the integrity check.
- `detect-private-key` and gitleaks do not flag public certificates. If a hook does, stop and
  report it; do not baseline it silently.
- In the AC3 test, search for the bare substring `"PRIVATE KEY"`. Never write a literal
  `BEGIN … PRIVATE KEY` header line into the test file: `detect-private-key` would flag the test
  itself.

## Risks

- **Setting `PGSSLMODE=verify-full` before cutover breaks the publisher**, because Heroku Postgres
  presents a different certificate. Mitigation: AC5 says so, and the cutover runbook sets both
  variables together with `DATABASE_URL`.
- **Removing `PGSSLMODE` silently drops back to unverified TLS** (asyncpg's default `prefer`).
  Removing only `PGSSLROOTCERT`, or pointing it at a missing file, fails hard instead: asyncpg falls
  back to `~/.postgresql/root.crt`, which does not exist on a dyno, and raises
  `ClientConfigurationError` or `FileNotFoundError`. Mitigation: the post-cutover check below.
- **Hetzner rotates the CA** (the current one expires 2032-06-04). Mitigation: replace the file;
  AC2's fingerprint test fails loudly and forces a deliberate update.

## Success Metrics

- After cutover, a one-off dyno run with `PGSSLROOTCERT` pointed at a different valid CA bundle
  (`/etc/ssl/certs/ca-certificates.crt`) fails with `CERTIFICATE_VERIFY_FAILED`, and the normal web
  process connects. A nonexistent path is not a valid test, because it fails with
  `FileNotFoundError` before any handshake.

## Related

- Orchestrator `SEC_08` (`docs/10_Roadmap/SEC_08_DatabaseTlsCertificateVerification.md` in
  `dhirmadi/platform-orchestrator`): the same change for `org-prod` on `n0ot.your-database.de`.
- PUB-047 (#186): asyncpg `timeout` / `command_timeout` connect args. They are unaffected because
  `ssl` stays unset, which is what lets asyncpg read the environment.

## Change Log

- 2026-11-28 — Spec hardened for Claude Code handoff. ACs split so each tests one behaviour, the `ssl`-kwarg regression guard (AC4) was added, the docs AC was made literal, and no GitHub issue is needed. Independent review applied: corrected AC cross-references and the `PGSSLROOTCERT` failure mode, added the staging and `ssl=` URL warnings, marked AC4 as a characterization test, and required a PEM-only file.
