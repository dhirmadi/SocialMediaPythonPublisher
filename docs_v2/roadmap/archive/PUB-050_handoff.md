# Implementation Handoff: PUB-050 — Owner Voice Corpus in Every Caption Prompt

**Hardened:** 2026-09-25
**Status:** Ready for implementation

## For Claude Code

### Test-first targets

| AC | Test file | Test name (exact function) |
|----|-----------|----------------------------|
| AC1 | `publisher_v2/tests/test_owner_voice_corpus.py` | `test_sample_voice_examples_returns_four_to_six_from_twelve_item_profile` |
| AC1 | `publisher_v2/tests/test_owner_voice_corpus.py` | `test_sample_voice_examples_result_has_no_duplicates_and_is_drawn_from_profile` |
| AC2 | `publisher_v2/tests/test_owner_voice_corpus.py` | `test_sample_voice_examples_is_deterministic_for_same_seed` |
| AC2 | `publisher_v2/tests/test_owner_voice_corpus.py` | `test_sample_voice_examples_differs_for_two_chosen_seeds` |
| AC3 | `publisher_v2/tests/test_owner_voice_corpus.py` | `test_sample_voice_examples_prefers_email_tagged_examples_when_pool_is_large_enough` |
| AC3 | `publisher_v2/tests/test_owner_voice_corpus.py` | `test_sample_voice_examples_ignores_a_tag_whose_text_is_not_in_the_profile` |
| AC3 | `publisher_v2/tests/test_owner_voice_corpus.py` | `test_sample_voice_examples_unions_tags_across_multiple_enabled_platforms` — proves the union semantics called out in the roadmap item's AC3 "Multi-platform note": with two enabled platforms and disjoint tag sets, examples tagged for *either* platform are preferred, not just one |
| AC4 | `publisher_v2/tests/test_owner_voice_corpus_workflow.py` | `test_workflow_run_prompt_contains_sampled_voice_examples` |
| AC4 | `publisher_v2/tests/test_owner_voice_corpus_workflow.py` | `test_workflow_run_prompt_prefers_tagged_examples_when_voice_profile_tags_set` (single enabled platform) |
| AC4 | `publisher_v2/tests/test_owner_voice_corpus_workflow.py` | `test_workflow_run_prompt_unions_tags_when_two_platforms_enabled` — end-to-end version of the union-semantics test above, through the real workflow |
| AC5 | `publisher_v2/tests/web/test_web_settings_voice_profile.py` | `test_get_voice_profile_reports_not_persisted` |
| AC5 | `publisher_v2/tests/web/test_web_settings_voice_profile.py` | `test_post_voice_profile_reports_not_persisted` |
| AC6 | — (PR-authoring process gate; no pytest target — see the roadmap item's Implementation Notes) | — |

The **Test name** column is the exact `pytest` function name to create — the only spec-to-test
traceability link this contract relies on. `/verify` and `/product-review-delivery` check it
literally; if a different name is genuinely needed, record the actual name and why in the summary
doc rather than silently renaming.

### New production code (not test-first, but load-bearing for every AC above)

- `services/ai.py`: new pure function `sample_voice_examples(examples, seed_source, platform_tags=None, platforms=None, target_min=4, target_max=6, max_tokens_budget=DEFAULT_VOICE_PROFILE_TOKEN_BUDGET) -> list[str]`. Exact algorithm is pinned in the roadmap item's Implementation Notes — implement it as written there, not a re-derivation, since AC2's determinism test depends on the precise seed → `random.Random` → `randint(4, 6)` → shuffle sequence.
- `config/schema.py::ContentConfig`: add `voice_profile_tags: dict[str, list[str]] | None = None`, with the same "graceful, non-crashing" tolerance as `voice_profile` for malformed/mismatched entries (do not raise if a tag's text isn't in `voice_profile` — see AC3's second test).
- `config/orchestrator_models.py::OrchestratorContent`: mirror the field.
- `config/source.py::_build_app_config_v2`: pass `voice_profile_tags=ct.voice_profile_tags if ct else None` next to the existing `voice_profile=...` line (~line 570).
- `config/loader.py`: `_load_content_settings_from_env` reads `voice_profile_tags` from `CONTENT_SETTINGS` the same way it reads `voice_profile` (~line 289); add `"voice_profile_tags"` to `REDACT_KEYS` (~line 51).
- `core/workflow.py` (~lines 588–594): replace the plain `truncate_voice_profile_to_budget(self.config.content.voice_profile)` call with `sample_voice_examples(self.config.content.voice_profile, seed_source=(selected_content_hash or selected_hash), platform_tags=self.config.content.voice_profile_tags, platforms=list(specs.keys()))`.
- `web/service.py::_select_voice_examples`: add a `seed_source: str` parameter, plus `platform_tags`/`platforms`. At its one call site (~line 893), pass `hashlib.sha256(analysis_source).hexdigest()` when `analysis_source` is `bytes` (the `vision_max_dimension > 0` branch — bytes already in hand), else fall back to `filename` (the `vision_max_dimension == 0` presigned-URL path never downloads the image).
- `web/models.py::VoiceProfileResponse`: add `persisted: bool = False` and `orchestrator_field: str = "content.voice_profile"`.
- `web/app.py`: both `api_get_voice_profile` and `api_set_voice_profile` construct `VoiceProfileResponse(..., persisted=False, orchestrator_field="content.voice_profile")`.
- `web/templates/index.html`: update the `voice-profile-status` copy after a successful save to also state the value is process-local (e.g. append "(not persisted to the orchestrator)"). No dedicated pytest AC for this line — see the roadmap item's Implementation Notes.
- `docs_v2/07_AI/AI_PROMPTS_AND_MODELS.md` §8: document `voice_profile_tags`, the sampling algorithm, its seed sources, the 4–6 target, and explicitly state the multi-platform union semantics from the roadmap item's AC3 note (tag preference is a union across every currently-enabled platform in one shared prompt, not per-platform differentiation) — don't let the doc overclaim what a tagged corpus buys a multi-platform tenant.

### Mock boundaries

| External service | Mock strategy | Existing fixture / pattern |
|-------------------|---------------|------------------------------|
| OpenAI (AC4) | `unittest.mock.patch("publisher_v2.services.ai.AsyncOpenAI", _FakeOpenAI)` with a `_FakeCompletions.create` that records `kwargs["messages"]` before returning a canned JSON caption payload | `publisher_v2/tests/web/test_per_platform_captions_real_app.py::_FakeOpenAI`/`_FakeCompletions` (copy the shape, add a `captured_messages: list` class var) |
| Orchestrator HTTP API (AC4) | `httpx.MockTransport` handler for `/v1/runtime/by-host` and `/v1/credentials/resolve`, wired into `OrchestratorConfigSource._client` | `publisher_v2/tests/config/test_orchestrator_voice_matching.py::_source` |
| Dropbox (AC4, only if the workflow run needs a real image) | `unittest.mock.patch("publisher_v2.services.storage.dropbox.Dropbox", _FakeDropbox)` | `publisher_v2/tests/web/test_per_platform_captions_real_app.py::_FakeDropbox` |
| Web auth / admin cookie (AC5) | Real `require_admin`/`require_auth` against a minted admin cookie | `publisher_v2/tests/web/test_web_settings_voice_profile.py::_admin` |

AC4 combines two existing, separately-proven patterns (`OrchestratorConfigSource` over `httpx.MockTransport`, and `WorkflowOrchestrator` over a faked Dropbox/OpenAI boundary) that have not previously been used in the same test — budget a bit more time for this one than the others; it is new wiring, not a copy-paste.

### Files likely touched

| Area | Files to modify | Files to create |
|------|------------------|------------------|
| AI / sampling | `publisher_v2/src/publisher_v2/services/ai.py` | `publisher_v2/tests/test_owner_voice_corpus.py` |
| Config schema | `publisher_v2/src/publisher_v2/config/schema.py`, `config/orchestrator_models.py`, `config/source.py`, `config/loader.py` | — |
| Workflow wiring | `publisher_v2/src/publisher_v2/core/workflow.py` | `publisher_v2/tests/test_owner_voice_corpus_workflow.py` |
| Web service wiring | `publisher_v2/src/publisher_v2/web/service.py` | — |
| Web setter contract | `publisher_v2/src/publisher_v2/web/models.py`, `web/app.py`, `web/templates/index.html` | — |
| Existing tests to extend, not replace | `publisher_v2/tests/web/test_web_settings_voice_profile.py` | — |
| Docs | `docs_v2/07_AI/AI_PROMPTS_AND_MODELS.md` §8 | — |

### Non-negotiables for this item

- [ ] Preview mode: unaffected — sampling only changes *which* examples are chosen, not whether any side effect occurs; preview must remain side-effect-free as it already is.
- [ ] Secrets: `voice_profile_tags` carries the same sensitive free-text as `voice_profile` — it must be added to `REDACT_KEYS` (`config/loader.py`) and never appear unredacted in a structured log. <!-- pragma: allowlist secret -->
- [ ] Auth: unchanged — `require_admin` + `require_auth` continue to gate both `voice-profile` verbs exactly as today; do not loosen or reorder those checks.
- [ ] Backward compatibility: a config payload with `voice_profile` set and no `voice_profile_tags` at all must keep working exactly as before (uniform seeded sampling, no platform preference) — this is the default/fallback path most existing tenants will be on.
- [ ] Coverage: ≥80% on `services/ai.py`, `core/workflow.py`, `web/service.py`, `web/app.py`, `config/*.py` (all inside `[tool.coverage.run] source`), ≥85% overall.

### Claude Code command

```text
/implement docs_v2/roadmap/PUB-050_owner-voice-corpus.md
```
