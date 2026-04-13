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
| **Web UI (Active)** ||||||
| PUB-033 | Web UI | [Unified Image Browser](PUB-033_unified-image-browser.md) | P1 | L | PUB-031, PUB-032 | Hardened |
| **AI-Powered Content** ||||||
| PUB-025 | AI | [Platform-Adaptive Captions](PUB-025_platform-adaptive-captions.md) | P1 | S | — | Not Started |
| PUB-026 | AI | [AI Alt Text Generation](PUB-026_ai-alt-text.md) | P1 | S | — | Not Started |
| PUB-028 | AI | [Smart Hashtag Generation](PUB-028_smart-hashtag-generation.md) | P2 | S | PUB-025 | Not Started |
| PUB-029 | AI | [Brand Voice Matching](PUB-029_brand-voice-matching.md) | P2 | S–M | PUB-025 | Not Started |
| **New Platforms** ||||||
| PUB-027 | Publishing | [Bluesky Publisher](PUB-027_bluesky-publisher.md) | P1 | S | — | Not Started |
| PUB-030 | Publishing | [Mastodon / Fediverse Publisher](PUB-030_mastodon-fediverse-publisher.md) | P1 | S | — | Not Started |

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

See `/product/lifecycle` for the full guide.

## Historical Context

Items PUB-000 through PUB-022 were migrated from the original Epics/Features/Stories hierarchy in `docs_v2/08_Epics/` (now archived). The original detailed story-level documentation is preserved there for reference.

## Related

- [Architecture](../03_Architecture/ARCHITECTURE.md)
- [Specification](../02_Specifications/SPECIFICATION.md)
- [Configuration](../05_Configuration/CONFIGURATION.md)
- [Testing](../10_Testing/README.md)
- [Quality Reviews](../09_Reviews/QUALITY_METRICS.md)
- [Archived Epics (historical)](../08_Epics/README.md)
