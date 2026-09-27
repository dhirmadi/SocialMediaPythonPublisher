# PUB-082: Consume the Orchestrator's Per-Instance Caption Overrides

| Field | Value |
|-------|-------|
| **ID** | PUB-082 |
| **Category** | AI |
| **Priority** | P1 |
| **Effort** | M |
| **Status** | Proposal |
| **Dependencies** | PUB-046, PUB-051 (archive); orchestrator AI_03 (#220) and PLT_12 (#224/#225), both shipped |

## User Story

As the owner, I want the per-platform caption overrides I set on an instance in the orchestrator to
reach the captions Publisher writes, so that a tenant's length band and register take effect without
a Publisher code or YAML change.

## Problem

Tracked in [#232](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/232).

1. **The block is dropped on the floor.** The orchestrator projects `config.platform_captions` on
   `GET /v1/runtime/by-host` (schema reference §5.9). `OrchestratorConfigV2`
   (`config/orchestrator_models.py:198-213`) has no field for it. `extra="allow"` keeps it in
   `model_extra`, and `_build_app_config_v2` (`config/source.py:467-608`) never reads it.
2. **The registry is static and process-wide.** `CaptionSpec.for_platforms` (`core/models.py:73-140`)
   reads only `get_static_config().ai_prompts.platform_captions` (`core/models.py:81`), an
   `lru_cache` singleton (`config/static_loader.py:418`) loaded from `ai_prompts.yaml:106-125`.
   Every tenant in the shared web process gets the same styles.
3. **A real requirement is waiting.** The owner's band (orchestrator #220, comment of 2026-09-26) is
   150–230 characters for email. It must compose with, not override, the email platform's limit
   (`platform_limits.yaml` 240) and the short-limit path (`max_length <= 300`, `services/ai.py:100`,
   PUB-046: word-count instructions, one-line cleanup, condense pass).

## Decisions

All confirmed by the owner on 2026-09-27, including examples applying whether or not voice matching is
on, and silent clamping of an over-limit `max_length`.

- **Where it lives.** The parsed block is carried on the per-tenant `ApplicationConfig` (proposed
  field `platform_caption_overrides`), set by `_build_app_config_v2`. `CaptionSpec.for_platforms`
  merges it over the static registry on each call. The static singleton is never mutated, so one
  tenant's overrides cannot leak to another; cache keying is the existing per-host runtime cache and
  `config_version`. Env-first mode (the CLI cron path) never sets the field.
- **`generic`** is Publisher's existing `generic` registry entry in both its roles: the spec used when
  no publisher is enabled, and the fallback for an enabled platform with no registry entry. It does
  not cascade: an omitted `telegram.style` falls back to YAML `telegram.style`, not to runtime
  `generic.style`.
- **`max_length` composes by clamping.** Effective value = `min(runtime max_length,
  platform_limits.<platform>.max_caption_length)` (the `generic` limit when the platform has none).
  An override can tighten a platform, never loosen it. Email therefore stays at or under 240 and on
  the short-limit path. A lower bound (the band's 150) has no numeric field; it goes in `guidance`.
- **`examples`.** YAML carries no examples (#138). Runtime examples for a platform are appended after
  the voice-profile examples on that platform's spec, whether or not voice matching is on.
- **`instagram` stays in `ai_prompts.yaml`.** Env-first mode still has an Instagram publisher
  (`config/loader.py:415`); orchestrated mode forces `instagram_enabled=False`
  (`config/source.py:559`). PLT_12 AC9 is closed as "kept, env-only". A runtime `instagram` key, or
  any key outside `telegram`/`email`/`generic`, is ignored.
- **Invalid block fails soft.** A malformed `platform_captions` is dropped with one WARNING and the
  tenant runs on YAML, matching the static loader's fail-soft. It never fails the whole runtime config.

## Scope

**In scope:**
- `PlatformCaptionPartial` model (`style`, `examples`, `guidance`, `max_length`, all optional, bounds
  per §5.9) and `OrchestratorConfigV2.platform_captions: dict[str, PlatformCaptionPartial] | None`.
- Wiring through `_build_app_config_v2` to `ApplicationConfig`, and the per-field merge and clamp in
  `CaptionSpec.for_platforms`.
- `WebImageService._platform_limits` (`web/service.py:782-792`) reports the effective (clamped)
  `max_length`, so the UI counter matches what generation targets.
- A short note in `docs_v2/03_Architecture/ARCHITECTURE.md` on the merge order and clamp.

**Out of scope:**
- An env-var equivalent of the block for env-first mode.
- Overriding `hashtags` or `closing` at runtime (not in the contract).
- A minimum-length field or enforcement.
- Orchestrator docs: `publisher-v2-service-api.md:171-179` and §5.9 name "PUB-047" as the consumer
  and claim Publisher's registry was "updated in lockstep" with PLT_12. Neither is true. **Owner
  action in the orchestrator repo:** point both at PUB-082 and drop the lockstep claim.
- Deploying the orchestrator side to org-prod (#220: staging only). Owner action; until then this item
  has no production effect.

## Acceptance Criteria

- AC1: Given a runtime payload with `platform_captions`, when `OrchestratorConfigV2` parses it, then
  each known key parses as a `PlatformCaptionPartial` with only the given fields set.
- AC2: Given a tenant whose runtime block sets `email.guidance` only, when specs are built on the web
  analyze path and on the web publish path (`WorkflowOrchestrator`), then both email specs carry the
  runtime guidance and the YAML `style` and `max_length`.
- AC3: Given a runtime leaf for `style`, `guidance` or `max_length`, when specs are built, then the
  runtime value wins for that field and every omitted field keeps its YAML value.
- AC4: Given no `platform_captions` block, when specs are built for telegram, email, both, and none
  enabled, then every spec equals the spec built today (golden comparison).
- AC5: Given `email.max_length: 230`, when specs are built, then email `max_length` is 230 and the
  prompt uses the short-limit word-count line. Given `email.max_length: 500`, then it is clamped to
  240. Given `telegram.max_length: 5000`, then it is clamped to 4096.
- AC6: Given a runtime `generic` override and no enabled publisher, when specs are built, then the
  `generic` spec carries the override. Given the same override and an enabled telegram with no
  telegram override, then the telegram spec is pure YAML.
- AC7: Given runtime `email.examples` and a voice profile with voice matching on, when the email spec
  is built, then its examples are the voice-profile examples followed by the runtime examples.
- AC8: Given tenant A with an email override and tenant B without, in one process, when both build
  specs in either order, then B's email spec is pure YAML and the static registry is unchanged.
- AC9: Given a runtime key `instagram` or `mastodon`, when the config is built, then it is ignored,
  the other keys still apply, and the YAML `instagram` entry is unchanged.
- AC10: Given a malformed block (e.g. `max_length: 0`, `examples: "x"`), when the runtime config is
  fetched, then the tenant config still builds, overrides are absent, and one WARNING
  `platform_captions_invalid` names field locations only.
- AC11: Given override bodies containing a sentinel string, when a config is built and specs are
  generated (valid and invalid block), then no log record at INFO or above contains the sentinel.
- AC12: Given an email override of 230, when the web UI requests platform limits, then email reports 230.
- AC13: Given this item ships, when its implementing PR merges, then #232 is closed with `Closes #232`
  in the PR body.

## Test-first targets

| AC | Test |
|----|------|
| AC1 | `publisher_v2/tests/config/test_orchestrator_platform_captions.py::test_config_v2_parses_platform_captions_as_partials` |
| AC2 | `publisher_v2/tests/config/test_orchestrator_platform_captions.py::test_runtime_override_reaches_web_analyze_and_publish_specs` |
| AC3 | `publisher_v2/tests/test_caption_spec_runtime_overrides.py::test_runtime_leaf_wins_and_omitted_leaf_keeps_yaml` |
| AC4 | `publisher_v2/tests/test_caption_spec_runtime_overrides.py::test_absent_block_builds_specs_identical_to_static_registry` |
| AC5 | `publisher_v2/tests/test_caption_spec_runtime_overrides.py::test_runtime_max_length_is_clamped_to_platform_limit` |
| AC5 | `publisher_v2/tests/test_caption_spec_runtime_overrides.py::test_owner_email_band_stays_on_short_limit_path` |
| AC6 | `publisher_v2/tests/test_caption_spec_runtime_overrides.py::test_generic_override_does_not_cascade_to_named_platforms` |
| AC7 | `publisher_v2/tests/test_caption_spec_runtime_overrides.py::test_runtime_examples_follow_voice_profile_examples` |
| AC8 | `publisher_v2/tests/test_caption_spec_runtime_overrides.py::test_overrides_do_not_leak_across_tenants` |
| AC9 | `publisher_v2/tests/config/test_orchestrator_platform_captions.py::test_unknown_platform_caption_keys_are_ignored` |
| AC10 | `publisher_v2/tests/config/test_orchestrator_platform_captions.py::test_invalid_platform_captions_block_fails_soft` |
| AC11 | `publisher_v2/tests/config/test_orchestrator_platform_captions.py::test_override_bodies_never_logged_at_info_or_above` |
| AC12 | `publisher_v2/tests/web/test_platform_limits_runtime_override.py::test_platform_limits_report_effective_max_length` |

## Risks

- **Pydantic errors echo input.** A `ValidationError` string contains the offending value; AC10/AC11
  require logging `loc` only, never `str(exc)`.
- **Clamping hides an owner mistake.** A 500 on email silently becomes 240. The WARNING-free clamp is
  deliberate and owner-confirmed (the limit is the platform's); revisit if owners report confusion.
- **Runtime examples bypass the voice-matching flag.** Owner-confirmed; if that changes, AC7 changes.

## References

- [#232](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/232) — this item's issue
- dhirmadi/platform-orchestrator#220 (AI_03, owner band comment 2026-09-26), #224/#225 (PLT_12)
- Orchestrator `docs/02_Architecture/runtime-config-schema-reference.md` §5.9 and
  `publisher-v2-service-api.md` — the contract
- PUB-046 (archive) — short-limit path; PUB-051 (archive) — current YAML styles; #138 — no static examples
