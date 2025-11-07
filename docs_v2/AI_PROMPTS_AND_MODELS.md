# AI Models and Prompting — Social Media Publisher V2

Version: 2.0  
Last Updated: November 7, 2025

## 1. Model Strategy (2025)
- Primary: OpenAI GPT‑4o / GPT‑4.1 family (multimodal; fast and cost‑effective variants: gpt‑4o‑mini)
- Fallback: Replicate BLIP‑2 or newer VLM for description and tags
- Optional: Local CLIP embedding for duplicate/similarity detection (future)

## 2. Vision Analysis Prompt (OpenAI)
System:
“You are an expert vision curator for social media. Extract concise description, mood, tags, and safety flags suitable for downstream captioning.”

User (with image input):
“Analyze this image for: description (≤30 words), mood (single phrase), 8‑12 tags (single words), and safety flags (nsfw categories if any). Output strict JSON with fields: description, mood, tags, nsfw, safety_labels.”

Expected JSON:
```json
{
  "description": "A subject ...",
  "mood": "serene, nostalgic",
  "tags": ["portrait", "film", "golden_hour", "..."],
  "nsfw": false,
  "safety_labels": []
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
“Write one caption. Prioritize authenticity, specificity, and imagery. 1–2 short sentences. End with provided hashtags verbatim. Respect max_length. Avoid emojis unless the style requires them. No quotes around the output. Do not include platform names.”

Post‑Processing:
- Trim whitespace
- Enforce length (truncate with unicode ellipsis if needed)
- Normalize spacing before hashtags

## 4. Hashtag Guidance
- Use provided `hashtag_string` from config to ensure consistency
- Optionally auto‑append 2–3 tags from analysis if space allows
- Do not exceed Instagram 30 hashtag rule (enforced post‑processing)

## 5. Safety and NSFW
- If `nsfw` true or safety_labels non‑empty:
  - Avoid sexual explicitness in copy
  - Respect platform policies (may skip Instagram publish by config)
  - Always allow Telegram/email unless configured otherwise

## 6. Evaluation and Tuning
- Keep a small golden set of images and expected captions
- Monthly prompt refinements based on engagement (future)


