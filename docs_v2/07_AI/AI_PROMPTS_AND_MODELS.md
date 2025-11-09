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

## 3. Caption Prompt (OpenAI)
System:
“You are a senior social media copywriter. Write authentic, concise, platform‑aware captions that feel human and avoid generic clichés.”

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


