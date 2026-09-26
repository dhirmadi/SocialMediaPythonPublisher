# AI Models and Prompting — Social Media Publisher V2

Version: 2.1
Last Updated: November 8, 2025

## 1. Model Strategy (2025)
- OpenAI only (MaaS): GPT‑4o / GPT‑4.1 family for all multimodal tasks
- **Separate models for vision and caption** (v2.1+):
  - **Vision analysis:** gpt-4o (superior quality for image understanding)
  - **Caption generation:** gpt-4o-mini (cost-effective, excellent output)
- Backward compatible: single `model` field still supported
- Optional future: local embeddings for deduplication (out of scope for V2)

### Cost-Quality Trade-offs:
- **Recommended:** `vision_model=gpt-4o` + `caption_model=gpt-4o-mini` (~$4.55 per 1K images) ⭐
- **Budget:** `model=gpt-4o-mini` for both (~$0.32 per 1K images)
- **Premium:** Both gpt-4o (~$6.50 per 1K images, not recommended)

## 2. Vision Analysis Prompt (OpenAI)
System:
“You are an expert vision curator for social media and AI art datasets. Produce a detailed but structured breakdown suitable for downstream captioning and SD prompts. Return strict JSON only; no prose.”

User (with image input):
“Analyze this image and return strict JSON with keys:
description, mood, tags (array), nsfw (boolean), safety_labels (array),
subject, style, lighting, camera, clothing_or_accessories,
aesthetic_terms (array), pose, composition, background, color_palette.
Description ≤ 30 words. If unknown, use null or empty array. No extra text.”

Expected JSON:
```json
{
  "description": "A subject ...",
  "mood": "serene, nostalgic",
  "tags": ["portrait", "film", "golden_hour", "..."],
  "nsfw": false,
  "safety_labels": [],
  "subject": "single adult subject, torso framed, facing camera",
  "style": "fine-art editorial, monochrome",
  "lighting": "soft directional, high-contrast",
  "camera": "50mm equivalent, shallow depth of field",
  "clothing_or_accessories": "rope harness (body-form)",
  "aesthetic_terms": ["minimalist", "graphic"],
  "pose": "upright stance, shoulders squared, chin lifted",
  "composition": "center-weighted portrait, negative space around subject",
  "background": "plain studio backdrop",
  "color_palette": "black, white, gray"
}
```

### Caption-facing fields (#138)
The same vision call also returns two fields written **for the caption writer, not the dataset**:
`sensory_detail` (2–3 concrete, evocative details: texture, tension, temperature, gaze, breath; warm
adult register, no explicit acts) and `mood_note` (one sentence in the voice of someone who finds
the image beautiful). They lead the caption prompt's analysis context and are **never** written to
the SD/sidecar metadata, which stays neutral.

## 3. Caption Prompt (OpenAI)
System (shipped default, `config/static/ai_prompts.yaml` `caption.system`, #138):
“You write in the account owner's voice; adult, warm, specific, unhurried. …” followed by the
BANNED CONSTRUCTIONS list. User prompt opens with the one-sentence brief “Write one caption per
platform below about this photograph, in the account owner's voice.” and ends with one
`Constraints:` line carrying every platform's hard length limit.

User:
- Inputs:
  - description (≤30 words), mood, tags
  - platform: instagram|telegram|email
  - style: “minimal poetic” | “friendly promotional” | “documentary”
  - hashtag_string: appended raw hashtags
  - max_length: platform constraint
Instruction:
“Write one caption. Prioritize authenticity, specificity, and imagery. 1–2 short sentences. Respect max_length. Avoid emojis unless the style requires them. No quotes around the output. Do not include platform names. If platform=email (FetLife), do not use hashtags.”

Post‑Processing:
- Trim whitespace
- Enforce length (truncate with unicode ellipsis if needed)
- Normalize spacing before hashtags

## 4. Hashtag Guidance
- Use provided `hashtag_string` from config to ensure consistency (except Email/FetLife)
- Email/FetLife: never include hashtags (formatter strips them and enforces ≤240 chars)
- Instagram: do not exceed 30 hashtags (enforced post‑processing)

## 5. Safety and NSFW
- If `nsfw` true or safety_labels non‑empty:
  - Avoid sexual explicitness in copy
  - Respect platform policies (may skip Instagram publish by config)
  - Always allow Telegram/email unless configured otherwise

## 6. Evaluation and Tuning
- Keep a small golden set of images and expected captions
- Monthly prompt refinements based on engagement (future)

## 7. Tone Control (FetLife)
- Set tone via `system_prompt` and `role_prompt` in the INI:
  - Example: “kinky, playful, respectful; consent‑forward; no hashtags or emojis; ≤240 chars; end with an open question”
- Prompts can be iterated safely with `--preview` to audition variations

## 8. Voice Examples and Caption Diversity (#82, #138)

- **Tenant voice profile is the only source of examples (#138).** No static example captions
  ship with the app. An `examples` key left in a `PV2_STATIC_CONFIG_DIR` override is **stripped
  with a `static_caption_examples_ignored` warning**, not rejected — that directory is a
  fleet-wide override read at startup, so refusing it would take every instance down for a key
  whose contents never reach a prompt. A tenant without a `content.voice_profile` gets no
  few-shot examples at all. The examples are rendered **once**, in the hardened STYLE REFERENCES
  block; they used to be repeated inside every platform block as well.
- **Default persona is tenant-neutral (#138).** The shipped `caption.system` is the persona
  only — "You write in the account owner's voice; adult, warm, specific, unhurried." A tenant
  `system_prompt` replaces that persona, and the banned-constructions list under
  `caption.rules` is **appended automatically to whichever persona is in force**, so you do not
  copy it by hand and cannot lose it by writing your own. (A hand-written
  `PV2_STATIC_CONFIG_DIR` override replaces `ai_prompts.yaml` wholesale, so one without a
  `caption.rules:` key does lose them — keep the key when you override that file.) For example
  (the persona you would set):

  > You are the artist writing about your own fine-art rope and figure photography, speaking to
  > an adult audience of collectors and kink-aware art lovers. Voice: first person, concrete,
  > unhurried, confident; specific sensory detail over abstraction.

- **Platform briefs state register and length, not shape (#138).** The email brief is "30 to 35
  words, one moment, first person, no hashtags"; it no longer mandates a closing question.
  `platform_captions.<name>.closing` (`question` | `statement` | `any`, default `any`) can
  mandate a closing; when it does, that platform's "closing pattern to avoid" line is skipped.
  Hard length limits appear once, in a trailing `Constraints:` line. Platforms whose style has
  `hashtags: false` get no hashtag-generation instruction.
- `features.voice_matching_enabled` now defaults to **true when `content.voice_profile` is
  non-empty**; an explicit value in config always wins.
- Caption history reaches the prompt as **constraints, not examples**: the first six words of
  each recent caption ("openings to avoid") and its closing pattern (question / statement /
  fragment). Full historical captions are never quoted into a prompt. Window default: 3.
- Each platform block with history carries a rotated **structure directive** (declarative /
  sensory fragment / second person / quiet observation / short line), picked least-recently-used
  against the history.
- A **similarity gate** compares each generated caption against that platform's history using
  word-trigram Jaccard; above 0.45 it regenerates once with a must-differ clause. Each
  offending platform gets a new directive picked with the rejected draft as the most recent
  entry, and that directive replaces the platform's original one: a prompt never carries two
  structure directives for the same platform (#138). Every run logs a `caption_similarity` event per platform
  (`platform`, `max_similarity`, `regenerated`) — preview mode included.

### 8.1 Per-image sampling of the voice corpus (PUB-050)

The STYLE REFERENCES block no longer carries the whole `content.voice_profile` in the same order
on every call. `sample_voice_examples()` (`services/ai.py`) picks a **4–6 example** subset per
image, so a ten-to-twenty-line corpus reads as a voice rather than as a fixed template.

**Algorithm** (pure and deterministic):

1. Dedup the profile, preserving first-seen order, as the candidate pool.
2. If `content.voice_profile_tags` and the platform list are both non-empty, partition the pool
   into `preferred` (tagged for at least one of those platforms) and `rest`, each preserving
   **pool** order. Otherwise `preferred` is empty and `rest` is the whole pool.
3. Seed `random.Random` with `int.from_bytes(sha256(seed_source).digest()[:8], "big")` and draw
   `target = min(len(pool), rng.randint(4, 6))`.
4. Shuffle `preferred`, then `rest`, with that same generator; take from `preferred` first, then
   `rest`, until `target` items are collected.
5. Apply the existing 500-token budget truncation (drop from the end). This is the one path that
   can legitimately yield fewer than four examples, for an unusually long corpus.

**How short is "reasonably short"?** Step 5 is a hard ~2000-character ceiling on the *whole*
sample, so the corpus's average example length decides whether the 4–6 target survives it.
Measured on a 12-item pool: examples averaging **under ~300 characters** never drop the result
below four; at **~400 characters** every sample is capped at exactly four; at **500 characters or
more** every sample returns fewer than four. Aim for examples in the 150–300 character range —
that is also the length a real caption tends to be.

**Determinism assumption (worth knowing before you rely on it).** Reproducibility here rests on
`random.Random.randint` and `random.Random.shuffle` behaving identically across interpreters.
CPython only *guarantees* that for `random()` and `getrandbits()`; `randint`/`shuffle` are
explicitly excluded from its compatibility promise. Verified byte-identical on CPython 3.10, 3.11,
3.12, 3.13 and 3.14a3 as of 2026-09, so there is no live problem — but a future CPython change to
either method would silently re-roll every image's sample, with no error and no log line. If
per-image stability ever has to be guaranteed across interpreter upgrades, the fix is to replace
those two calls with arithmetic over `getrandbits`, not to pin the interpreter.

**Seed sources** — same image, same examples; different images, different examples:

| Call site | `seed_source` |
|-----------|---------------|
| `core/workflow.py` (cron publish / preview) | `selected_content_hash or selected_hash` |
| `web/service.py::WebImageService.analyze_and_caption` | `sha256` of the image bytes when `openai.vision_max_dimension > 0` (the modern default), else the filename (the presigned-URL path never downloads the image) |

**`content.voice_profile_tags`** is an optional `dict[str, list[str]]` mapping a platform name
(`telegram` / `instagram` / `email`) to the subset of `voice_profile` strings preferred for that
platform. A tag whose text is no longer in `voice_profile` is **ignored, never an error** — an
edit that touches one list and not the other must not break caption generation. Omitting the
field entirely keeps the previous behaviour: uniform seeded sampling with no platform preference.

A **key** that names no currently-enabled platform (the classic case: the publisher *type*
`fetlife` instead of the platform name `email`) buys the tenant nothing, so it is not silent: when
*no* tag key matches any enabled platform, `sample_voice_examples` logs a `WARNING`
`voice_profile_tags_matched_no_enabled_platform` carrying the tag key names **truncated to 32
characters** (a plain prefix, no ellipsis) and the enabled platform names — never the tagged text.
At most **10 keys** are listed, sorted; the payload's `tag_key_count` always carries the real
number of keys, so a truncated list is recognisable as one and the true scale of the
misconfiguration stays visible (`voice_profile_tags` has no size cap of its own).
Expect to see a cut key in your logs: the keys are unvalidated free text, so an inverted mapping
(`{"<a whole example caption>": ["telegram"]}`) would otherwise spill caption text into tenant
logs once per image; 32 characters is far too short to carry a caption and far more than enough to
name any real platform intact. It is diagnostic only — captioning continues normally on
the untagged path. Note the asymmetry: a key that *does* match but whose listed **text** is no
longer in `voice_profile` is ignored silently by design, and produces no log line.

**Tag at least six examples per platform.** The target count is drawn *before* `preferred` is
consulted (step 3 precedes step 4), so a tagged pool smaller than the largest possible target
cannot fill every draw and the remainder is topped up from untagged examples. The leak rate is not
an empirical curiosity — it is exactly `P(target > tagged)`, and `target` is uniform over {4, 5, 6}:
**3 tagged → 100%**, **4 tagged → 2/3**, **5 tagged → 1/3**, **6 or more tagged → 0%**. (Measured
over 2000 seeds on a 12-item pool: 100%, 67%, 34%, 0% — matching the arithmetic.) So
"four to six examples" is *not* the number to tag: tagging four looks like it should be enough and
leaks on two runs in three. Six per platform (or per union of enabled platforms — see below) is
the point where preference is guaranteed.

**Multi-platform semantics — do not overread the tags.** One shared prompt covers every enabled
platform at once, so the workflow passes *all* currently-enabled platform names in one call.
Tag preference is therefore the **union** of the examples tagged for any enabled platform, not
per-platform differentiation: a tenant with telegram, instagram and email all enabled and a
generously-tagged corpus will see little or no preference effect, because the union is close to
the whole corpus. Tagging buys a real narrowing only for a tenant running a single platform, or
one whose tags cover a small slice of the corpus. This is an accepted limitation of the
shared-prompt architecture, not a defect.

**Where to set both fields:** `content.voice_profile` and `content.voice_profile_tags` in the
orchestrator runtime config (schema v2), or in the `CONTENT_SETTINGS` JSON environment variable
for a standalone instance. Both are treated as sensitive free text and are listed in
`config/loader.py`'s `REDACT_KEYS` for config-dump redaction — note that this is a narrow
guarantee: `REDACT_KEYS` is consumed only by `_safe_log_config`, which has no production callers
today and matches top-level keys only, so a nested `{"content": {...}}` dump would not be redacted
by it. The one place the field is actually logged today is the unmatched-key warning above, which
protects it directly by truncating keys and never logging values. `POST /api/config/voice-profile` edits the profile **for one process
only** — it answers `persisted: false` and names `content.voice_profile` as the orchestrator
field to set for the change to survive a restart or reach the cron publisher.
