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
  ship with the app; `PlatformCaptionStyle` rejects an `examples` key. A tenant without a
  `content.voice_profile` gets no few-shot examples at all.
- **Default persona is tenant-neutral (#138).** The shipped `caption.system` is "You write in
  the account owner's voice; adult, warm, specific, unhurried." plus the banned-constructions
  list. A tenant's own persona belongs in its `system_prompt`. A tenant `system_prompt`
  **replaces the whole shipped `caption.system`**, so copy the BANNED CONSTRUCTIONS list from
  `config/static/ai_prompts.yaml` into it. For example (persona part):

  > You are the artist writing about your own fine-art rope and figure photography, speaking to
  > an adult audience of collectors and kink-aware art lovers. Voice: first person, concrete,
  > unhurried, confident; specific sensory detail over abstraction.

- **Platform briefs state register and length, not shape (#138).** The email brief is "30 to 35
  words, one moment, first person, no hashtags"; it no longer mandates a closing question.
  `platform_captions.<name>.closing` (`question` | `statement` | `any`, default `any`) can
  mandate a closing; when it does, that platform's "closing patterns to avoid" line is skipped.
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
