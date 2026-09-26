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

### Caption-facing fields (#138, PUB-051)
The same vision call also returns two fields written **for the caption writer, not the dataset**:
`sensory_detail` (2–3 concrete details a person in the room would feel or notice) and `mood_note`
(one first-person sentence). They lead the caption prompt's analysis paragraph and are **never**
written to the SD/sidecar metadata, which stays neutral.

PUB-051 made this one call with **two registers**: the system message is the unchanged neutral
`vision.system` prompt, followed by a section opening with the fixed marker `OWNER-VOICE SECTION:`
(`services/ai.py` `OWNER_PERSONA_MARKER`) that governs only those two fields, in the owner's voice.
That section offers a **senses pool** (4 of 12 senses) chosen by a seed from the first 8 bytes of
the SHA-256 of the image bytes, so the fields stop circling the same five nouns. When vision only
has a URL, the seed is hashed from the URL string: a presigned URL changes on every request, so
that seed is stable per URL string, not per image. When the tenant has its own caption persona
(`OpenAIConfig.system_prompt` differs from the schema default — the same rule the caption
generator uses), the owner section quotes it, flattened to one line, with instruction-injection
markers redacted and cut to 600 characters; without one it describes the default owner voice.
The neutral `vision.system` text always comes first and is never changed by the persona. Because
both registers share one completion, the persona can still influence the neutral fields
(`nsfw`, `safety_labels`, `alt_text`, `sd_caption`) — the same authority a tenant already has
through its caption `system_prompt`; nothing gates publishing on those fields.

The same neutral call also returns **`sd_caption`**, the Stable Diffusion prompt written to the
sidecar, but only when `sd_caption_enabled` is true: the request is the `vision.sd_caption` text in
`ai_prompts.yaml`, appended to `vision.user` only then. With SD prompts off, vision is never asked
for `sd_caption` and no `vision_sd_caption_missing` warning is logged. The caption completion no
longer produces it: the workflow logs one INFO `sd_caption_from_vision` event (correlation id only,
no content) when the SD prompt comes from vision, and the old `sd_caption_start` /
`sd_caption_complete` events around the caption call are gone. Consequently:

- `sd_caption_single_call_enabled` no longer affects the multi-platform path;
- `sd_caption_model`, `sd_caption_system_prompt` and `sd_caption_role_prompt` apply only to the
  single-platform fallback (`generate_with_sd`);
- multi-platform captions use `model`.

A reply that is not JSON is asked for once more at the same resolution and detail before the
fallback pass runs.

## 3. Caption Prompt (OpenAI)
System (shipped default, `config/static/ai_prompts.yaml` `caption.system`, PUB-051): the persona is
written as a person ("You made these photographs, and you are writing about your own work for the
people who follow it. …"), followed by `caption.rules`: the BANNED CONSTRUCTIONS list and one
"write X instead of Y" line for every pattern in `utils/caption_metrics.DEFAULT_TELLS_LEXICON`.
User prompt: the one-sentence brief, the STYLE REFERENCES block, one block per platform (stance,
hashtags, guidance, one content angle, at most two openings to avoid), the analysis as a short
prose paragraph (`Photo: …`, capped at 260 characters, ~65 tokens; no tags, colour palette or
aesthetic terms), one `Constraints:` line with every hard length limit, and the JSON key list —
the platforms only. A platform with smart hashtags also gets one `Topics:` line: up to five of the
vision tags as plain words (underscores become spaces), sanitized like the other analysis fields
and deduplicated; other platforms get no topics. On the PUB-051 test fixture (history plus six
~60-character voice examples) it measures about 470 tokens by `len(prompt) / 4` (an approximation
of the tokenizer, not an exact count). Voice examples dominate the size: the voice-profile budget
(`DEFAULT_VOICE_PROFILE_TOKEN_BUDGET`, 500 tokens) alone can exceed that, so a tenant with long
examples or seed hashtags gets a larger prompt (a heavy fixture measures about 570). The call samples at temperature 0.9,
`frequency_penalty` 0.3, `presence_penalty` 0.6 (an all-short-platform call keeps 0.5).

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
  only — since PUB-051 written as a person ("You made these photographs, and you are writing
  about your own work for the people who follow it…"; see `ai_prompts.yaml`). A tenant
  `system_prompt` replaces that persona, and the banned-constructions list under
  `caption.rules` is **appended automatically to whichever persona is in force**, so you do not
  copy it by hand and cannot lose it by writing your own. (A hand-written
  `PV2_STATIC_CONFIG_DIR` override replaces `ai_prompts.yaml` wholesale, so one without a
  `caption.rules:` key does lose them — keep the key when you override that file.) For example
  (the persona a rope-art tenant would set; PUB-051 keeps anything rope-specific out of the
  shipped default):

  > You are the artist behind this fine-art rope and figure photography, writing about your own
  > work for an adult audience of collectors and kink-aware art lovers. You were in the room: write
  > in the first person about what you saw, felt and chose — the jute, the light, the patience of
  > the tie — concrete, unhurried and confident, with the image left to carry the feeling.

- **Platform briefs are stances (PUB-051).** Each `platform_captions.<name>.style` names who is
  speaking to whom (telegram: you, to your channel's regulars, after a session; instagram: you, to
  strangers scrolling past; email: you, privately, to one reader who asked to hear from you).
  The email guidance is "FetLife email subject. 30 to 35 words, one moment, first person"; it does
  not mandate a closing question. `platform_captions.<name>.closing` (`question` | `statement` |
  `any`, default `any`) can mandate a closing. Hard length limits appear once, in a trailing
  `Constraints:` line. Platforms whose style has `hashtags: false` get no hashtag-generation
  instruction.
- `features.voice_matching_enabled` now defaults to **true when `content.voice_profile` is
  non-empty**; an explicit value in config always wins.
- Caption history reaches the prompt as **constraints, not examples**: the first six words of
  the **two most recent** captions ("openings to avoid"), after emoji and hashtags are stripped.
  There is no closing-pattern line (PUB-051: "avoid: statement" pushed plain sentences toward
  questions). Full historical captions are never quoted into a prompt.
- Every platform block carries exactly one **content angle** (PUB-051, `utils/captions.CONTENT_ANGLES`:
  sensation, moment, detail, craft, atmosphere, direct_address) naming what the caption dwells on.
  The angle is stored with each history row (`pv2_caption_history.angle`, migration 004) and
  picked per platform, least-recently-used over that platform's stored angles, ties broken by
  pool order; rows without one count as never used. Within one call platforms get **distinct
  angles** while the pool allows: platforms are taken in spec order, and each skips (in its own
  LRU order) angles an earlier platform already took; if every candidate is taken it falls back to
  its plain LRU pick rather than failing. The web Analyze path reads the same stored angles
  (`fetch_recent_with_angles_by_platform`), so both paths feed one rotation. `excluded_directives` is kept as the hook for
  removing angles a brief contradicts, but returns an empty set today: no angle conflicts with a
  platform brief the way the old "under 12 words" and "no questions" directives did.
- A **similarity gate** compares each generated caption against that platform's history using
  word-trigram Jaccard; above 0.45 it regenerates once with a must-differ clause. Each offending
  platform gets a new angle, never the rejected draft's, picked with that angle as the most recent
  entry and preferring one no other platform in the call holds (a soft preference); a prompt never
  carries two angles for the same platform. Every run logs a
  `caption_similarity` event per platform (`platform`, `max_similarity`, `regenerated`) — preview
  mode included.
- The sidecar records the angles next to the captions: `caption_angles` maps each platform to
  the angle key its `caption_generated` caption was written under (metadata only, written by the
  workflow and by web Analyze; on read, values that are not pool keys are dropped).
- Caption history records only the platforms a run **published successfully**. A retry of a
  partial publish reads the captions the first run wrote to the sidecar (`caption_generated`)
  and makes no OpenAI call; the rows it adds carry the sidecar's `caption_angles` for each
  platform, and the retry never rewrites the sidecar. A publish with operator overrides
  (`caption_source = manual_override`) reads the sidecar once: a platform whose published override
  equals `caption_generated[platform]` (both stripped) keeps `caption_angles[platform]`; an edited
  one, or any read failure, records no angle.
