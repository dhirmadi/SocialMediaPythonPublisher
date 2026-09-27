# Product Roadmap — Social Media Publisher V2

## Purpose

This roadmap defines the product evolution path for the Social Media Python Publisher V2 — an automated content distribution platform with AI-generated captions. Images are sourced from Dropbox, analyzed by OpenAI Vision, captioned, and published to Telegram, Instagram, and email. A FastAPI web admin UI provides manual control.

Each roadmap item is a self-contained markdown file in this folder. Shipped items live in `archive/`.

## Roadmap Index

| ID | Category | Item | Priority | Effort | Dependencies | Status |
|----|----------|------|----------|--------|--------------|--------|
| **Foundation (Shipped)** ||||||
| PUB-000 | Foundation | [Preview Mode](archive/PUB-000_preview-mode.md) | INF | S | — | Done |
| PUB-001 | AI | [Caption File (SD Prompt)](archive/PUB-001_caption-file.md) | INF | M | — | Done |
| PUB-003 | AI | [Expanded Vision Analysis JSON](archive/PUB-003_expanded-vision-analysis.md) | INF | M | — | Done |
| PUB-004 | AI | [Caption File Extended Metadata](archive/PUB-004_caption-extended-metadata.md) | INF | S | PUB-001 | Done |
| PUB-006 | Foundation | [Core Workflow Dedup Performance](archive/PUB-006_core-workflow-dedup.md) | INF | M | — | Done |
| PUB-015 | Storage | [Cloud Storage Adapter (Dropbox)](archive/PUB-015_cloud-storage-dropbox.md) | INF | M | — | Done |
| PUB-016 | Observability | [Structured Logging & Redaction](archive/PUB-016_structured-logging.md) | INF | S | — | Done |
| PUB-017 | Publishing | [Multi-Platform Publishing Engine](archive/PUB-017_multi-platform-publishing.md) | INF | M | — | Done |
| **Web UI & Curation (Shipped)** ||||||
| PUB-005 | Web UI | [Web Interface MVP](archive/PUB-005_web-interface-mvp.md) | INF | L | — | Done |
| PUB-010 | Web UI | [Keep/Remove Curation Controls](archive/PUB-010_keep-remove-curation.md) | INF | M | PUB-005 | Done |
| PUB-018 | Web UI | [Thumbnail Preview Optimization](archive/PUB-018_thumbnail-preview.md) | INF | M | PUB-005, PUB-015 | Done |
| PUB-019 | Web UI | [Swipe Gestures & Workflow Modes](archive/PUB-019_swipe-workflow-modes.md) | INF | L | PUB-005, PUB-010 | Done |
| PUB-020 | Web UI | [Auth0 Login Migration](archive/PUB-020_auth0-login.md) | INF | M | PUB-005 | Done |
| **Runtime & Telemetry (Shipped)** ||||||
| PUB-007 | Observability | [Cross-Cutting Performance & Observability](archive/PUB-007_performance-observability.md) | INF | M | — | Done |
| PUB-008 | Publishing | [Publisher Async Throughput Hygiene](archive/PUB-008_async-throughput.md) | INF | S | PUB-017 | Done |
| PUB-009 | Config | [Feature Toggle System](archive/PUB-009_feature-toggles.md) | INF | S | — | Done |
| **Deployment & Ops (Shipped)** ||||||
| PUB-011 | Ops | [Heroku App Cloning with Hetzner DNS](archive/PUB-011_heroku-hetzner-cloning.md) | INF | L | — | Done |
| PUB-012 | Config | [Centralized Config & i18n Text](archive/PUB-012_central-config-i18n.md) | INF | M | — | Done |
| PUB-021 | Config | [Config Env Consolidation](archive/PUB-021_config-env-consolidation.md) | INF | L | PUB-012 | Done |
| **Multi-Tenant Orchestrator (Shipped)** ||||||
| PUB-022 | Foundation | [Orchestrator Schema V2 Integration](archive/PUB-022_orchestrator-schema-v2.md) | INF | XL | PUB-021 | Done |
| **Managed Storage** ||||||
| PUB-023 | Foundation | [Storage Protocol Extraction](archive/PUB-023_storage-protocol-extraction.md) | P1 | S | PUB-015 | Done |
| PUB-024 | Storage | [Managed Storage Adapter](archive/PUB-024_managed-storage-adapter.md) | P1 | M | PUB-023 | Done |
| PUB-031 | Storage / Web UI | [Managed Storage Migration & Admin Library](archive/PUB-031_managed-storage-migration-admin-library.md) | P1 | L | PUB-023, PUB-024 | Done |
| PUB-032 | Web UI / Storage | [Admin Library — Sorting & Filtering](archive/PUB-032_library-list-sort-filter.md) | P1 | M | PUB-031 | Done |
| **Web UI (Shipped)** ||||||
| PUB-033 | Web UI | [Unified Image Browser](archive/PUB-033_unified-image-browser.md) | P1 | L | PUB-031, PUB-032 | Done |
| PUB-036 | Web UI | [Upload Queue](archive/PUB-036_upload-queue.md) | P1 | S | PUB-031, PUB-033 | Done |
| PUB-037 | Web UI | [Multi-Select & Bulk Delete](archive/PUB-037_bulk-delete.md) | P2 | S | PUB-033, PUB-036 | Done |
| PUB-038 | Web UI | [Grid Toolbar Redesign](archive/PUB-038_toolbar-redesign.md) | P2 | S | PUB-033, PUB-036, PUB-037 | Done |
| **AI-Powered Content** ||||||
| PUB-025 | AI | [Platform-Adaptive Captions](archive/PUB-025_platform-adaptive-captions.md) | P1 | S | — | Done |
| PUB-026 | AI | [AI Alt Text Generation](archive/PUB-026_ai-alt-text.md) | P1 | S | — | Done |
| PUB-035 | AI | [Caption Context Intelligence](archive/PUB-035_caption-context-intelligence.md) | P1 | S–M | PUB-025 | Done |
| PUB-028 | AI | [Smart Hashtag Generation](archive/PUB-028_smart-hashtag-generation.md) | P2 | S | PUB-025 | Done |
| PUB-029 | AI | [Brand Voice Matching](archive/PUB-029_brand-voice-matching.md) | P2 | S–M | PUB-025, PUB-039 | Done |
| **Orchestrator AI Integration** ||||||
| PUB-039 | Config / AI | [AI Caption Feature Flags & Voice Profile](archive/PUB-039_ai-caption-feature-flags.md) | P1 | S | PUB-025, PUB-035 | Done |
| PUB-040 | Config / Observability | [OpenAI Model Lifecycle Warnings](archive/PUB-040_model-lifecycle-warnings.md) | P1 | S | PUB-022 | Done |
| PUB-043 | Config | [Orchestrator email publisher type](archive/PUB-043_orchestrator-email-publisher-type.md) | P0 | S | PUB-022 | Done |
| **AI Cost & Quality** ||||||
| PUB-041 | AI / Observability | [Vision Cost Optimization & Richer Caption Inputs](archive/PUB-041_vision-cost-optimization.md) | P0 | M | PUB-025, PUB-034, PUB-039 | Done |
| **Web UI / UX** ||||||
| PUB-042 | Web UI / UX | [Upload Queue: Lock UI During Active Uploads](archive/PUB-042_upload-queue-lock-ui.md) | P2 | S | PUB-036, PUB-037 | Done |
| PUB-044 | Web UI / UX | [Configurable Grid Page Size](archive/PUB-044_configurable-grid-page-size.md) | P2 | S | PUB-033 | Done |
| **Billing & Metering** ||||||
| PUB-034 | Foundation | [Usage Metering](archive/PUB-034_usage-metering.md) | P1 | S | Orchestrator #14 | Done |
| PUB-045 | Foundation | [R2 Storage Ops Metering](archive/PUB-045_storage-ops-metering.md) | P1 | S | PUB-034, PUB-024, Orchestrator BIL_10 | Done |
| **AI Quality** ||||||
| PUB-046 | AI | [Email Caption Length Control](archive/PUB-046_email-caption-length-control.md) | P1 | S | PUB-025, PUB-029, PUB-039 | Done |
| **Post-Review Plan 2026-09-21 (tracker #177)** ||||||
| PUB-047 | Foundation | [Reliability Batch — R2 Retries, Listing Cost, Meter Flush, Postgres Bounds](archive/PUB-047_reliability-batch.md) | P0 | S | — | Done |
| PUB-048 | Web UI | [Auth and Library Uniformity](archive/PUB-048_auth-and-library-uniformity.md) | P0 | S | — | Done |
| PUB-049 | AI | [Caption Evaluation Harness](archive/PUB-049_caption-evaluation-harness.md) | P0 | M | — | Done |
| PUB-050 | AI | [Owner Voice Corpus in Every Caption Prompt](archive/PUB-050_owner-voice-corpus.md) | P0 | M | PUB-049 | Done |
| PUB-051 | AI | [Caption Prompt and Register Repair](archive/PUB-051_caption-prompt-and-register-repair.md) | P0 | M | PUB-049 | Done |
| PUB-052 | AI | [Caption Candidate Selection and Model Trial](PUB-052_caption-candidate-selection.md) | P1 | S | PUB-049, PUB-051 | Proposal |
| PUB-053 | Web UI | [Shared-Dyno Isolation](PUB-053_shared-dyno-isolation.md) | P1 | L | PUB-047, PUB-083 | Proposal |
| PUB-054 | Foundation | [Publish State Integrity](PUB-054_publish-state-integrity.md) | P1 | M | PUB-047 | Proposal |
| PUB-055 | Ops | [CI Security Gates](PUB-055_ci-security-gates.md) | P1 | S | — | Done |
| PUB-056 | Storage | [Dropbox Removal or Storage Typing](PUB-056_dropbox-removal-or-typing.md) | P1 | M | PUB-047, PUB-053 | Proposal |
| PUB-057 | Config | [Configuration Consolidation](PUB-057_configuration-consolidation.md) | P1 | L | PUB-056 | Proposal |
| PUB-058 | Foundation | [Workflow Stages and Layering](PUB-058_workflow-stages-and-layering.md) | P1 | L | PUB-047, PUB-054 | Proposal |
| PUB-059 | Web UI | [Web App Factory, Routers and Typed Platform Captions](PUB-059_web-factory-and-typed-captions.md) | P2 | M | PUB-057, PUB-058 | Proposal |
| PUB-060 | Foundation | [Test and Docs Hygiene](PUB-060_test-and-docs-hygiene.md) | P2 | M | PUB-059 | Proposal |
| PUB-061 | Foundation | [Storage-Ops Drain Deadline — Stop Under-Billing a Slow-but-Alive Orchestrator](archive/PUB-061_storage-ops-drain-deadline.md) | P2 | XS | PUB-047 | Done |
| PUB-063 | Foundation | [Distinguish "absent" from "could not tell" in head_object](PUB-063_head-object-fail-open.md) | P1 | S | PUB-048 | Proposal |
| PUB-064 | AI | [Make the Caption Harness Exercise the Voice Path](PUB-064_harness-voice-path-coverage.md) | P1 | S | PUB-049, PUB-050 | Proposal |
| PUB-065 | Ops | [Dependency Security Upgrades](PUB-065_dependency-security-upgrades.md) | P1 | S | Blocks PUB-055 | Done |
| PUB-066 | Ops | [Unblock Dependabot's Python Updaters](archive/PUB-066_dependabot-python-updaters.md) | P1 | XS | PUB-055 | Done |
| PUB-067 | Ops | [SHA-Pin `code-quality.yml`](archive/PUB-067_sha-pin-code-quality-workflow.md) | P2 | S | PUB-055 | Superseded by PUB-078 |
| PUB-068 | Ops | [Add `publisher_v2/alembic` to the Bandit Scan Roots](archive/PUB-068_bandit-alembic-scan-root.md) | P3 | XS | PUB-055 | Superseded by PUB-078 |
| PUB-069 | Ops | [Single Source of Truth for the pip-audit Version Pin](archive/PUB-069_pip-audit-version-single-source.md) | P3 | XS | PUB-055 | Superseded by PUB-078 |
| PUB-070 | Foundation | [Migrate Off `TestClient`'s Per-Request `cookies=`](PUB-070_starlette-testclient-cookie-migration.md) | P2 | S | PUB-065 | Proposal |
| PUB-071 | Ops | [Triage the `openai` 3.x Major Upgrade](PUB-071_triage-openai-3x.md) | P3 | M | PUB-065 | Proposal |
| PUB-072 | Ops | [Assert Every Declared Dependabot Ecosystem Has a Manifest It Can Read](archive/PUB-072_dependabot-ecosystem-manifest-check.md) | P2 | XS | PUB-055, PUB-066 | Superseded by PUB-079 |
| PUB-073 | Ops | [Close the Requirements-Guard's Two Known Blind Spots](archive/PUB-073_requirements-guard-completeness.md) | P2 | XS | PUB-066 | Superseded by PUB-079 |
| PUB-074 | Foundation | [Require Mutation Proof for Regression-Guard Tests in Review](archive/PUB-074_guard-tests-must-be-proven-to-fail.md) | P1 | XS | — | Superseded by PUB-079 |
| PUB-075 | Ops | [Scope Dependabot to the Dependencies We Actually Maintain](archive/PUB-075_dependabot-scope-to-live-tree.md) | P1 | S | PUB-066 | Superseded by PUB-079 |
| PUB-076 | Ops | [The `uv` Updater Cannot Resolve — `instagrapi` Pins `pydantic` Exactly](archive/PUB-076_uv-resolution-instagrapi-pydantic.md) | P1 | S | PUB-066 | Superseded by PUB-079 |
| PUB-077 | Ops | [Fit the DB Connection Pool into the Shared 20-Connection Postgres](PUB-077_db-pool-budget.md) | P1 | S | PUB-047 | Proposal |
| PUB-078 | Ops | [CI Security-Gate Cleanup Batch](PUB-078_ci-security-gate-cleanup-batch.md) | P2 | S | PUB-055 | Proposal |
| PUB-079 | Ops | [Dependabot Correctness and Scope Batch](PUB-079_dependabot-correctness-and-scope-batch.md) | P1 | M | PUB-055, PUB-066 | Proposal |
| PUB-080 | AI | [Re-baseline the Caption Eval From Live Output](archive/PUB-080_caption-eval-live-baseline.md) | P1 | S | PUB-049, PUB-051 | Done |
| PUB-081 | AI | [Publish Reuses the Sidecar Analysis When Every Caption Is Supplied](PUB-081_publish-reuses-analysis-with-overrides.md) | P2 | S | PUB-051 | Proposal |
| PUB-082 | AI | [Consume the Orchestrator's Per-Instance Caption Overrides](PUB-082_runtime-platform-captions.md) | P1 | M | PUB-046, PUB-051 | Proposal |
| PUB-083 | Web UI | [Close the Tenant Factory Shutdown Race](PUB-083_tenant-factory-shutdown-race.md) | P2 | S | — (before PUB-053 #197) | Proposal |
| **New Platforms** ||||||
| PUB-027 | Publishing | [Bluesky Publisher](PUB-027_bluesky-publisher.md) | P1 | S | PUB-059 | Not Started |
| PUB-030 | Publishing | [Mastodon / Fediverse Publisher](PUB-030_mastodon-fediverse-publisher.md) | P1 | S | PUB-059 | Not Started |

## Recommended Execution Order (2026-09-27)

Cross-cutting sequencing across every open (non-`Done`) item, set by product management on
2026-09-27. This does **not** overwrite each item's own `Priority` field (P0-P3 stay as hardened) —
it is the order to actually pull items into IMPLEMENT in, gated **security → stabilization →
features**. Rationale: security closes real blast-radius and supply-chain gaps first; stabilization
fixes active production/correctness risk and pays down the debt that gates the next platform;
features ship last because two of the three are explicitly blocked on stabilization work landing
(PUB-059) and the third has no blockers left.

Items already `Done` (PUB-055, PUB-065, PUB-066, PUB-061) are excluded — they are shipped, just not
yet moved to `archive/` (see Outstanding Issue below).

### 1. Security (do first)

Simplified from an earlier 12-row list on 2026-09-27: eight small, independent CI/Dependabot fixes
had zero dependency on each other (only on already-`Done` items), so they're grouped below into
**parallel lanes** by which files they touch, and the eight originals were merged into two tracked
specs — [PUB-078](PUB-078_ci-security-gate-cleanup-batch.md) and
[PUB-079](PUB-079_dependabot-correctness-and-scope-batch.md) — superseding
PUB-067/068/069/072/073/075/076 (see each file's `Superseded` note; no scope was added or removed).

**Lanes 1-4 have zero file overlap and can run fully concurrently, starting now.** Lanes 5 and 6 both
edit `test_ci_security_gates.py`, so land them as two sequential PRs (either order) rather than in
parallel with each other. The trailing item has no rush and blocks nothing.

| Lane | ID | Item | Priority | Effort | Why here |
|------|----|------|----------|--------|----------|
| 1 (solo) | [PUB-063](PUB-063_head-object-fail-open.md) | `head_object` fail-open write guards | P1 | S | Active data-loss risk today: a transient 403/503 reads as "object absent" and an upload/move guard overwrites or destroys an existing image. Cheapest, highest-urgency fix in the whole roadmap. |
| 2 (solo) | [PUB-074](PUB-074_guard-tests-must-be-proven-to-fail.md) | Mutation proof for regression-guard tests | P1 | XS | Docs/agent-instructions only — zero src or test overlap with anything else here. Land it early so every guard test written in the lanes below is held to the "proven to fail" bar from day one. |
| 3 (solo) | [PUB-070](PUB-070_starlette-testclient-cookie-migration.md) | Migrate off `TestClient` per-request `cookies=` | P2 | S | Test-suite only. The negative auth assertions (`require_admin` returns 401/403) are what stands between an anonymous request and the admin API; fix the ambiguity before starlette resolves it for you. |
| 4 (solo, internally parallel) | [PUB-053](PUB-053_shared-dyno-isolation.md) | Shared-dyno isolation (host lookups, thumbnails, rate limits, executors, keys) | P1 | L | The largest security batch: cross-tenant amplification, decode bombs, shared rate-limit buckets, hung Instagram threads starving storage, per-purpose key derivation. Already decomposed into 6 sub-issues (#196-#203) that are themselves parallelizable across engineers/agents. Closes #168-#170 too. |
| 5 (batch, shares a file with lane 6) | [PUB-078](PUB-078_ci-security-gate-cleanup-batch.md) | CI security-gate cleanup (SHA-pin `code-quality.yml`, bandit's alembic gap, pip-audit version drift) | P2 | S | Three XS/S fixes finishing what PUB-055 started, all touching the same SHA-pin helper in `test_ci_security_gates.py` — one spec instead of three. Closes #204's last open criterion. |
| 6 (batch, shares a file with lane 5) | [PUB-079](PUB-079_dependabot-correctness-and-scope-batch.md) | Dependabot correctness and scope (manifest check, requirements-guard gaps, live-tree scoping, `uv`/`pydantic` resolution) | P1 | M | Four fixes surfaced by the same PUB-066 live run, all editing `.github/dependabot.yml` and/or `test_ci_security_gates.py` — one spec instead of four. Directly unblocks `pydantic` security patches and kills PR-queue noise that could hide a real advisory. |
| trailing (no rush) | [PUB-071](PUB-071_triage-openai-3x.md) | Triage the `openai` 3.x major | P3 | M | No advisory forces this; a deliberate hold with mypy friction. Doesn't block or get blocked by anything above — pick it up whenever. |

### 2. Stabilization (do second)

| Order | ID | Item | Priority | Effort | Why here / why this position |
|-------|----|------|----------|--------|-------------------------------|
| 1 | [PUB-077](PUB-077_db-pool-budget.md) | Fit the DB pool into the shared 20-connection Postgres | P1 | S | Not hypothetical — the orchestrator already hit `TooManyConnectionsError` once (#246) sharing this database. The control plane failing takes every tenant down. Highest-urgency stabilization item. |
| 2 | [PUB-054](PUB-054_publish-state-integrity.md) | Publish state integrity (tenant-keyed state, dedup, lease) | P1 | M | Cross-tenant 409 leakage, "success with nothing published" loops, and double-post risk on crash. Also unblocks PUB-058 (dependency). |
| 3 | [PUB-064](PUB-064_harness-voice-path-coverage.md) | Make the caption harness exercise the voice path | P1 | S | Cheap, isolated fix for a harness that is currently structurally blind to the PUB-050 feature it's supposed to be measuring — every caption-quality decision downstream (including PUB-052) is flying without instruments until this lands. |
| 4 | [PUB-056](PUB-056_dropbox-removal-or-typing.md) | Dropbox removal or storage typing | P1 | M | Resolves the `type: ignore` / `isinstance` / `hasattr` scattered around the web layer; blocks PUB-057. |
| 5 | [PUB-057](PUB-057_configuration-consolidation.md) | Configuration consolidation | P1 | L | One config model, one bool parser, a written precedence table. Needs PUB-056 first; blocks PUB-059. |
| 6 | [PUB-058](PUB-058_workflow-stages-and-layering.md) | Workflow stages and layering | P1 | L | Turns a 766-line `execute()` into named stages the CLI and web path share. Needs PUB-054 first; blocks PUB-059. |
| 7 | [PUB-059](PUB-059_web-factory-and-typed-captions.md) | Web app factory, routers, typed platform captions | P2 | M | Needs PUB-057 + PUB-058. Directly re-scopes PUB-027/PUB-030 to cheap, so it gates the features track below. |
| 8 | [PUB-060](PUB-060_test-and-docs-hygiene.md) | Test and docs hygiene | P2 | M | Needs PUB-059 (removes several `conftest.py` resets it would otherwise fight). Last because it's cleanup of the state the items above leave behind, not a risk fix. |

### 3. Features (do third)

| Order | ID | Item | Priority | Effort | Why here / why this position |
|-------|----|------|----------|--------|-------------------------------|
| 1 | [PUB-052](PUB-052_caption-candidate-selection.md) | Caption candidate selection and model trial | P1 | S | No blockers left (PUB-049, PUB-051 both Done) — ready today, and depends on PUB-064 above being true for its own Success Metrics to mean anything. |
| 2 | [PUB-027](PUB-027_bluesky-publisher.md) | Bluesky publisher | P1 | S | Blocked on PUB-059 (typed captions make this a cheap add instead of an eight-file change). Queue immediately behind PUB-052. |
| 3 | [PUB-030](PUB-030_mastodon-fediverse-publisher.md) | Mastodon / Fediverse publisher | P1 | S | Same blocker as PUB-027; sibling item, same effort. |

### Outstanding issue (flagged, not fixed here)

PUB-055, PUB-065 and PUB-066 are marked `Done` in the index above but their files (including
`PUB-055_handoff.md`, `PUB-055_plan.yaml`, `PUB-055_summary.md`) are still sitting in this directory
rather than `archive/`. Per the lifecycle, `Done` items should have already gone through
`/product-archive`. Not resolved as part of this prioritization pass — flagging for a follow-up
archive sweep.

## Priority Definitions

| Priority | Meaning |
|----------|---------|
| **INF** | Infrastructure — shipped foundation. Not actively developed. |
| **P0** | Critical — blocks other work or addresses a production issue |
| **P1** | High — next items to build; clear user or operational value |
| **P2** | Medium — valuable but can wait; may need design |
| **P3** | Future — ideas, research, or long-term vision |

## Effort Estimates

| Size | Description |
|------|-------------|
| **S** | Small — single module, < 1 week |
| **M** | Medium — multiple modules, 1-2 weeks |
| **L** | Large — significant feature, 2-4 weeks |
| **XL** | Extra Large — major initiative, 1+ month |

## Categories

| Category | What it covers |
|----------|---------------|
| Foundation | Core workflow, orchestration, domain models |
| Web UI | FastAPI web admin, templates, UX |
| Publishing | Platform publishers (Telegram, Instagram, Email) |
| Storage | Dropbox adapter, file management, archival |
| AI | OpenAI Vision analysis, caption generation |
| Config | Configuration loading, env vars, feature flags |
| Ops | Deployment, Heroku, DNS, scripts |
| Observability | Logging, metrics, performance |

## Status Values

| Status | Meaning |
|--------|---------|
| `Proposal` | Idea captured, needs scoping |
| `Not Started` | Scoped with ACs, ready to implement |
| `In Progress` | Actively being implemented |
| `Done` | Delivered and verified |
| `Deferred` | Deprioritized, may revisit |
| `Superseded` | Replaced by another item |

## Lifecycle

Each roadmap item follows a 7-stage lifecycle across two tools:

```
Cursor:  CREATE → HARDEN → [handoff] → REVIEW → DEPLOY → ARCHIVE
Claude:                      IMPLEMENT → VERIFY
```

See `/product-lifecycle` for the full guide.

Archived items carry a **Verified** evidence line (PR #, merge commit, test/coverage numbers)
under their header table, added by `/product-archive` — not just a bare `Done` status word.
This is what makes drift (a `Done` item that quietly regressed) checkable at a glance instead
of only surfacing during a manual `/product-health-check`.

## Historical Context

Items PUB-000 through PUB-022 were migrated from the original Epics/Features/Stories hierarchy in `docs_v2/08_Epics/` (now archived). The original detailed story-level documentation is preserved there for reference.

## Related

- [Architecture](../03_Architecture/ARCHITECTURE.md)
- [Architecture Decision Records](../03_Architecture/adr/README.md)
- [Specification](../02_Specifications/SPECIFICATION.md)
- [Configuration](../05_Configuration/CONFIGURATION.md)
- [Testing](../10_Testing/README.md)
- [Quality Reviews](../09_Reviews/QUALITY_METRICS.md)
- [Archived Epics (historical)](../08_Epics/README.md)
