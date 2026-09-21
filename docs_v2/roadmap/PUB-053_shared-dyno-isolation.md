# PUB-053: Shared-Dyno Isolation — Host Lookups, Thumbnails, Rate Limits, Executors, Keys

| Field | Value |
|-------|-------|
| **ID** | PUB-053 |
| **Category** | Web UI |
| **Priority** | P1 |
| **Effort** | M |
| **Status** | Proposal |
| **Dependencies** | PUB-047 |

## User Story

As a platform maintainer, I want one tenant's admin, or one anonymous client, to be unable to exhaust the dyno's memory, threads, rate budgets or the control plane's request budget for every other tenant, so that the multi-tenant deployment fails per tenant rather than per dyno.

## Problem

The web dyno runs every tenant in one process. The review ([#177](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/177), security M2, M3, M5, L4 to L10; performance M4 to M8, M11, L1, L2, L4) found the following cross-tenant blast radius:

- **Host lookups amplify.** `web/middleware.py:72-74` resolves the raw `Host` on every request; `config/source.py:306-348` caches only on success, so unknown or failing hosts refetch with retries every time; cache expiry has no single-flight (`:312-347`), so a grid page fires about 50 concurrent orchestrator calls; `/health/ready` probes the orchestrator uncached.
- **Thumbnails decode bombs.** `_verify_image_bytes` accepts 12,000 px per side without decoding; `Image.MAX_IMAGE_PIXELS = 40M` raises only at 80 MP; `_generate_thumbnail` decodes PNG in full (72 MP ≈ 220 to 290 MB) with only a per-key single-flight. The tenant factory (`web/tenant_factory.py:79-83`) discards warm caches on TTL expiry even when `config_version` is unchanged, so the 900 s thumbnail TTL is never reached and a browsing tenant re-bills 600 to 1,200 ops per hour.
- **Rate limits are per IP and shared.** Analyze and publish key on `remote_ip`; keep, remove, delete and move have no limiter; upload and delete key on the raw cookie, which every login rotates. Without `WEB_TRUST_FORWARDED_FOR` every request keys to the router IP.
- **Threads.** instagrapi issues requests with no socket timeout; cancelled coroutines leave `to_thread` work running in the default pool of about eight, shared with boto3, Pillow and SMTP; several blocking calls run on the loop.
- **Smaller items.** Stale config served with no ceiling and credentials cached inside it; a missing `auth` block inherits the platform allowlist; the Auth0 callback reflects attacker text into the admin toast; `STANDALONE_HOST` is dead for the web app; storage outages surface as 404; publishers rebuilt on every web publish; prune floor and a redundant index; no warn-once helper; `head_object` returns `None` on 403 (#168); one secret drives three key domains.

## Desired Outcome

A burst of requests for an unknown host costs the orchestrator at most one lookup per TTL; cache expiry produces one refetch. No upload above a pixel budget is stored; at most four thumbnails decode concurrently; warm caches survive TTL expiry when the config version is unchanged. No two tenants share a limiter bucket and every mutating route has one. No Instagram HTTP call can hang indefinitely and hung publisher threads cannot starve storage work. Each small item is fixed in its own PR. Keys are derived per purpose.

## Scope

**In scope:**
- Negative cache for `TenantNotFoundError` and build failures; single-flight per host; readiness cached (sub-issue #196)
- Pixel budget at upload; decode semaphore; `Image.reduce()` for PNG; TTL extension on unchanged version; per-tenant lock in the factory, closing #169 (#197)
- One limiter helper keyed on `(tenant, sid)`; every mutating route limited; ad-hoc dict limiters retired (#198)
- instagrapi timeout adapter; dedicated executor for storage and thumbnails; blocking calls moved off the loop; tenant service constructed in a thread (#201)
- Nine small items, nine PRs (#202): stale ceiling, auth-block default, callback error allow-list, `STANDALONE_HOST`, storage outage not 404, publisher rebuild, prune and index, warn-once, `head_object`
- HKDF per-purpose keys from `WEB_SESSION_SECRET`; SHA-256 digest on serializers; legacy Instagram sessions re-keyed on read (#203)

**Out of scope:**
- Posted-state tenancy and dedup (PUB-054)
- CI gates (PUB-055)
- Any CSP change

## Acceptance Criteria

- AC1: Given a fake orchestrator counting calls, when 100 requests arrive for an unknown host within the negative TTL, then one lookup was made; when 50 concurrent requests find an expired entry, then one refetch was made; when readiness is called ten times in ten seconds, then one probe was made
- AC2: Given a 12,000 × 6,000 PNG, when it is uploaded, then the response is 415 naming the pixel budget
- AC3: Given 50 concurrent thumbnail misses with a slow fake generator, when they run, then at most four decodes are in flight
- AC4: Given a tenant service past its TTL with an unchanged `config_version`, when it is requested, then the same instance and its thumbnail cache are returned; given a changed version, then it is rebuilt; given two concurrent first requests, then one service is built
- AC5: Given two tenants behind one IP, when tenant A exhausts analyze, then tenant B is not limited; given a second login for the same admin, then the upload budget is not reset; given each mutating route, then it returns 429 after its budget
- AC6: Given the instagrapi client, when its session adapter is inspected, then a default timeout is mounted; given a hung fake publisher, when a thumbnail is generated concurrently, then it completes within its own duration
- AC7: Given each of the nine small items, when its PR merges, then its named test passes through the real object and #168 is closed by the `head_object` PR
- AC8: Given the cookie-purpose key version is bumped, when a stored Instagram session is read, then it is still decrypted and re-encrypted under the derived key

## Implementation Notes

- Six sub-issues; #202 fans out into nine PRs by rule 1 on #177.
- #203 touches `web.auth` internals; owner's merge is the approval; `security-auditor` gate mandatory.
- Item 2 of #202 depends on the #181 contract answer; item 7 carries an additive migration (drop index only).

## Risks

- A global thumbnail semaphore trades cross-tenant safety for a cold grid taking longer to fill; four is a starting point, made a setting.
- Re-keying Instagram sessions on read must be idempotent and logged once per record.

## Success Metrics

- Zero R14/R15 events attributable to thumbnail decode after deploy.
- Orchestrator request rate from the data plane flat under a synthetic unknown-host flood.
- Two-tenant limiter tests green.

## Related

- Tracker [#177](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/177); sub-issues [#196](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/196), [#197](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/197), [#198](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/198), [#201](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/201), [#202](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/202), [#203](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/203); closes [#168](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/168), [#169](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/169), [#170](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/170)
- [PUB-018: Thumbnail Preview Optimization](archive/PUB-018_thumbnail-preview.md), [PUB-022: Orchestrator Schema V2 Integration](archive/PUB-022_orchestrator-schema-v2.md)
- Prior fixes #77 (forwarded IP), #86 (tenant-safe thumbnail cache), #140 (thumbnail HEAD)
