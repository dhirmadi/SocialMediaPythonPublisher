# PUB-050: Owner Voice Corpus in Every Caption Prompt

| Field | Value |
|-------|-------|
| **ID** | PUB-050 |
| **Category** | AI |
| **Priority** | P0 |
| **Effort** | M |
| **Status** | Implementation Complete |
| **Dependencies** | PUB-049 |

## User Story

As a publisher operator curating content, I want the captions the model writes to be anchored on captions I actually wrote, so that "in the account owner's voice" means something and the output stops reading like the average of every warm fine-art caption on the internet.

## Problem

`voice_profile` defaults to `None` on both loaders (`config/loader.py:289-290`, `config/orchestrator_models.py:181`), and `voice_matching_enabled` is derived from its presence (`config/schema.py:460-481`, #131), so voice matching is off by default. The only setter, `POST /api/config/voice-profile` (`web/app.py:867-878`), is documented as "in-memory for this process; does not persist back to the orchestrator". The cron publisher is a different process and never sees examples. When a profile does exist, `build_voice_examples_block` (`services/ai.py:832-852`) renders the same examples in the same order in every call, which is a template rather than a voice. The rendered default prompt says "You write in the account owner's voice; adult, warm, specific, unhurried" and supplies nothing about that voice. The review names this the most likely single root cause of "AI-like" captions.

## Desired Outcome

Every cron and web caption prompt for the tenant contains four to six owner-written examples, sampled per image from a durable corpus of ten to twenty, stable per image and varied across images. The web setter states honestly, in its response and its UI, that the change is process-local and names the orchestrator field an operator would need to set for it to survive a restart.

## Scope

**In scope:**
- Publisher V2 schema: add `content.voice_profile_tags: dict[str, list[str]] | None` (maps a platform name to the subset of `voice_profile` strings preferred for that platform; `None`/absent means no platform preference). This is the concrete answer to "tagged by platform if the schema allows" — this item makes the schema allow it. Mirrored on `OrchestratorContent`, `ContentConfig`, `_build_app_config_v2` (`config/source.py`), and the `CONTENT_SETTINGS` env loader (`config/loader.py`), following the existing `voice_profile` plumbing exactly, including its `REDACT_KEYS` log redaction.
- Orchestrator (contract owner, separate PR there, out of this PR): once the schema above ships, populate `content.voice_profile` (and optionally `content.voice_profile_tags`) for the tenant from the corpus supplied in #179. This is not a blocking dependency for AC1–AC5 below, which exercise fixture/constructed data.
- New pure function `sample_voice_examples(...)` (`services/ai.py`, alongside `truncate_voice_profile_to_budget`/`build_voice_examples_block`): deterministically samples 4–6 examples seeded by a per-image seed string, preferring examples tagged for the platform(s) being written when `voice_profile_tags` is present, then applies the existing 500-token budget truncation. Replaces the plain `truncate_voice_profile_to_budget(...)` call at both of its current call sites: `core/workflow.py`'s real publish/preview run (seed = `selected_content_hash or selected_hash`, both already in scope there) and `web/service.py::_select_voice_examples` (seed = a hash of `analysis_source` when it's already `bytes`, else `filename` — see Implementation Notes).
- Web setter (`GET`/`POST /api/config/voice-profile`) and `VoiceProfileResponse`: add `persisted: bool` and `orchestrator_field: str` fields. For this item the setter stays in-memory/process-local (no orchestrator write-back endpoint exists to call), so both handlers always report `persisted=False, orchestrator_field="content.voice_profile"`. The voice-profile editor's status line (`#voice-profile-status` in `index.html`) states this after a save.
- `docs_v2/07_AI/AI_PROMPTS_AND_MODELS.md` §8: documents `voice_profile_tags`, the sampling algorithm and its seed, and where to set both fields.

**Out of scope:**
- Prompt wording, directives, sampling parameters (PUB-051)
- Candidate selection (PUB-052)
- Writing the corpus (owner, #179)
- An orchestrator write-back endpoint for the web setter — would need a new service-to-service contract on the orchestrator side; not attempted here (see AC5)

## Acceptance Criteria

- AC1: Given a 12-item `voice_profile` (short enough that none of it is dropped by the 500-token budget — see Risks) and a seed string, when `sample_voice_examples(...)` runs, then it returns between four and six examples (inclusive), all drawn from the profile, with no duplicates.
- AC2: Given the same seed string passed to `sample_voice_examples(...)` twice with the same profile, then the two calls return an identical list in the same order; given two different, deliberately-chosen seed strings with the same profile (chosen so a difference is guaranteed, not left to chance), then the two returned lists differ from each other in membership and/or order.
- AC3: Given a `voice_profile` and a `voice_profile_tags` mapping that tags enough examples for `platforms=["email"]` to fill the sample target on its own, when `sample_voice_examples(...)` runs with `platforms=["email"]` (a single platform), then every returned example is one of the email-tagged strings — non-email-tagged examples are excluded whenever the email-tagged pool is large enough to fill the target count. **Multi-platform note**: the real `workflow.py` call site always passes every currently-enabled platform's name in `platforms` (one shared prompt covers all of them at once — see Problem). "Preferring tagged examples" therefore means the sample prefers the *union* of examples tagged for any enabled platform, not per-platform differentiation within one call — a tenant with all three platforms enabled and a generously-tagged corpus will see little or no preference effect. This is an accepted, documented limitation of the shared-prompt architecture (out of scope to change here — see PUB-051/PUB-052), not a defect; `docs_v2/07_AI/AI_PROMPTS_AND_MODELS.md` §8 must state it in those terms.
- AC4: Given a runtime payload with `content.voice_profile` set (and, in a second case, `content.voice_profile_tags` also set with only one platform enabled, and in a third case with two enabled platforms and disjoint tags, to prove the union behavior described in AC3 rather than leaving it unverified), when a workflow run executes through the real `OrchestratorConfigSource` and `WorkflowOrchestrator` with a fake OpenAI client that records the outgoing chat messages, then the captured prompt's STYLE REFERENCES block contains example strings that `sample_voice_examples(...)` would return for that run's seed and platform set — not the full, untruncated profile.
- AC5: Given `GET` or `POST /api/config/voice-profile` is called, when the response is inspected, then it always includes `persisted: false` and `orchestrator_field: "content.voice_profile"` (this item does not add an orchestrator write-back path — see Scope and Outstanding Issues in the hardening report).
- AC6 (PR-authoring process gate, not a pytest AC — see Implementation Notes): given the PUB-049 harness has produced a snapshot both before and after this item's sampling change lands, when this item's PR body is written, then it contains that offline score table. Blocked on PUB-049 shipping; do not attempt to satisfy this with a test.

## Implementation Notes

- Sub-issue #190. Depends on #179 (corpus, owner-authored content, not code) and #189 (harness, PUB-049). Only AC6 needs #179/#189 to have produced real output; AC1–AC5 use fixture/constructed data and are implementable and testable independent of both.
- Order: this item does not call the orchestrator to write anything back, so there is no ordering hazard against the orchestrator's separate schema/corpus PR — it can land before, after, or in parallel. Once that orchestrator PR exists, link it from this item's PR body for traceability.
- **Seed**: `int.from_bytes(hashlib.sha256(seed_source.encode()).digest()[:8], "big")` fed into `random.Random(...)`. `seed_source` is `selected_content_hash or selected_hash` in `core/workflow.py`'s real publish/preview run (both already computed in scope there). In `web/service.py::_select_voice_examples`, prefer hashing `analysis_source` when it is already `bytes` (the `vision_max_dimension > 0` branch, the modern default — the bytes are already in hand, so this costs nothing extra); fall back to `filename` only when `analysis_source` is a presigned-URL string (`vision_max_dimension == 0`), since that path never downloads the image.
- **`sample_voice_examples` algorithm** (deterministic given `seed_source`; lives in `services/ai.py`):
  1. Dedup `examples`, preserving first-seen order, as the candidate pool.
  2. If `voice_profile_tags` and `platforms` are both given and non-empty, partition the pool into `preferred` (tagged for at least one platform in `platforms`) and `rest`, each preserving relative order. Otherwise `preferred = []`, `rest = pool`.
  3. `target = min(len(pool), rng.randint(4, 6))` using the seeded `random.Random`.
  4. Deterministically shuffle `preferred` then `rest` with the same `rng` (so different seeds vary both groups); take from `preferred` first, then `rest`, until `target` items are collected.
  5. Apply the existing `truncate_voice_profile_to_budget(...)` (500-token budget, drop-from-end) to the result. This is the one path that can legitimately return fewer than 4 examples if the sampled entries are unusually long — an accepted, pre-existing degradation mode (see Risks), not a new AC to satisfy.
- `voice_profile_tags: dict[str, list[str]] | None` — keys are platform names (`telegram`/`instagram`/`email`, matching `CaptionSpec.for_platforms()`'s registry), values are strings that must also appear in `voice_profile`. A tag entry whose text isn't in `voice_profile` is ignored, not an error — an edit that touches one list and not the other must not crash caption generation. Add the field to `config/schema.py::ContentConfig`, `config/orchestrator_models.py::OrchestratorContent`, `config/source.py::_build_app_config_v2`, and `config/loader.py`'s `CONTENT_SETTINGS` parsing and `REDACT_KEYS`, mirroring `voice_profile`'s existing plumbing at each of those four sites exactly.
- `CaptionSpec.for_platforms()` (`core/models.py`) is intentionally left as-is: it still assigns the full, unsampled profile into each spec's `examples` tuple, used only as the fallback inside `_build_multi_prompt` when a caller passes no explicit `voice_examples`. Both real call sites (`workflow.py`, `web/service.py`) always pass an explicit `voice_examples` (now sampled, or explicitly `None` when voice matching is off) — so this fallback branch is *reached but empty* in every production run, not unreachable dead code. Leave it alone; do not "clean it up" as part of this item, and do not describe it as unreachable in code comments (a later refactor could otherwise resurrect a path assumed impossible).
- AC5's `persisted`/`orchestrator_field` fields go on `VoiceProfileResponse` (`web/models.py`) and are returned by both the `GET` and `POST` handlers in `web/app.py`. The `index.html` status-line copy update (Scope) is an implementation task, not a separate pytest AC — this repo has no JS/UI test harness to assert against.
- AC6 is a PR-authoring gate, not a pytest target — mirrors PUB-049's own carve-out for its Success Metrics (`docs_v2/roadmap/PUB-049_caption-evaluation-harness.md`, Implementation Notes). Do not write a test for it and do not block the rest of this item's implementation on it; it can only be satisfied once PUB-049 has shipped and produced a real before/after snapshot.

## Risks

- A corpus that is too small or too uniform anchors as hard as the old static examples did; #179 asks for at least three per platform and two deliberately plain ones.
- `sample_voice_examples`'s 500-token budget can legitimately return fewer than four examples if the seeded sample happens to draw unusually long entries; this degrades the same way `truncate_voice_profile_to_budget` already does (drop from the end) rather than failing, but it means AC1's four-to-six guarantee assumes a corpus of reasonably short examples — which is what #179 asks for.

## Success Metrics

- Harness TF-IDF cosine to history and tells rate both improve against the PUB-049 baseline in the PR body.
- The owner's blind reading in PUB-052 prefers the post-corpus output.

## Related

- Tracker [#177](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/177); sub-issues [#190](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/190), [#179](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/179)
- [PUB-029: Brand Voice Matching](archive/PUB-029_brand-voice-matching.md) — introduced `voice_profile`
- [PUB-039: AI Caption Feature Flags & Voice Profile](archive/PUB-039_ai-caption-feature-flags.md) — the orchestrator field
- Prior fix #131 (voice matching default)

## Change Log

- 2026-09-25 — Spec hardened for Claude Code handoff (`/product-harden`). Verified all Problem-section line references and the shared-multi-platform-prompt architecture directly against the code. Added the `content.voice_profile_tags` schema field and a pinned `sample_voice_examples` algorithm to make ACs 1–3 concretely testable; resolved AC5's persistence branching to a single `persisted: false` outcome (flagged below); reclassified AC6 as a PR-authoring process gate, not a pytest AC (mirrors PUB-049's own carve-out). Independent architect review ran; its one Must-fix (AC3/AC4 did not state what "platform preference" degrades to once more than one platform is enabled in the shared-prompt architecture) was applied — AC3 now has an explicit multi-platform union-semantics note, AC4 gained a two-platform/disjoint-tags case, and the docs task now must state the same limitation. Its Should-improve findings were applied: Effort raised S → M given the true surface area; the `CaptionSpec.for_platforms()` fallback is now described as "reached but empty" rather than "dead code"; the web preview-path seed prefers already-in-hand image bytes over `filename` when available. Its Nice-to-have (inline the budget caveat into AC1 itself) was applied.

## Outstanding Issues (user decision needed)

- **AC5 / web setter persistence**: the original AC allowed two outcomes — always report `persisted: false`, *or* actually persist through the orchestrator. This hardening pass picked the first (no new orchestrator write-back endpoint, since that would be a new cross-repo service-to-service contract per `.cursor/rules/40-parent-orchestrator.mdc`, out of proportion for this item). If you actually want the setter to persist to the orchestrator, that needs its own item on the orchestrator side first (contract owner) before this one can consume it — please confirm the `persisted: false`-only reading is acceptable, or say so and this item will be re-scoped.
- **Effort raised S → M** (see Change Log) — confirm this is acceptable for scheduling purposes; no scope was added, only a more accurate estimate of the S-effort item's actual size.
