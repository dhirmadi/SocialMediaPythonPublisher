# PUB-087: Verify the Database Server's TLS Certificate

| Field | Value |
|-------|-------|
| **ID** | PUB-087 |
| **Category** | Config |
| **Priority** | P1 |
| **Effort** | S |
| **Status** | Proposal |
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
  - The file is a public certificate with no private key.
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

- AC1: Given the repo, when `certs/hetzner-sqlca.crt` is loaded with
  `ssl.create_default_context(cafile=...)`, then it loads without error and contains exactly one
  certificate. Its SHA-256 fingerprint equals
  `0C:2F:66:73:68:A8:03:14:E2:45:5E:1D:FF:FE:89:64:85:4D:9D:11:2F:C6:F5:A3:68:CF:D2:AE:93:6A:74:27`.
- AC2: Given the repo, when `certs/hetzner-sqlca.crt` is inspected, then it contains no
  `PRIVATE KEY` block.
- AC3: Given this item ships, when `CONFIGURATION.md` is read, then it documents:
  - `PGSSLMODE=verify-full` and `PGSSLROOTCERT=/app/certs/hetzner-sqlca.crt`, and what they do;
  - that they must be set in the same release as the Hetzner `DATABASE_URL`, because Heroku
    Postgres's certificate is not signed by this CA;
  - that `?sslmode=` in `DATABASE_URL` breaks the connection.
- AC4: Given this item ships, when its implementing PR merges, then no GitHub issue is closed by
  it. None is filed yet; `/product-harden` either files one and lists it here with `Closes #N`, or
  confirms none is needed.

## Implementation Notes

- AC1 can compute the fingerprint from the DER bytes: `ssl.PEM_cert_to_DER_cert` plus `hashlib`.
  It needs no new dependency.
- Copy the file from the operator's Hetzner download, not from this spec. The fingerprint in AC1
  is the integrity check.
- `detect-private-key` and gitleaks do not flag public certificates. If a hook does, stop and
  report it; do not baseline it silently.

## Risks

- **Setting `PGSSLMODE=verify-full` before cutover breaks the publisher**, because Heroku Postgres
  presents a different certificate. Mitigation: AC3 says so, and the cutover runbook sets both
  variables together with `DATABASE_URL`.
- **Removing either variable silently drops back to unverified TLS.** Mitigation: the post-cutover
  check below.
- **Hetzner rotates the CA** (the current one expires 2032-06-04). Mitigation: replace the file;
  AC1's fingerprint test fails loudly and forces a deliberate update.

## Success Metrics

- After cutover, a one-off dyno run with a deliberately wrong `PGSSLROOTCERT` fails with
  `CERTIFICATE_VERIFY_FAILED`, and the normal web process connects.

## Related

- Orchestrator `SEC_08` (`docs/10_Roadmap/SEC_08_DatabaseTlsCertificateVerification.md` in
  `dhirmadi/platform-orchestrator`): the same change for `org-prod` on `n0ot.your-database.de`.
- PUB-047 (#186): asyncpg `timeout` / `command_timeout` connect args. They are unaffected because
  `ssl` stays unset, which is what lets asyncpg read the environment.
