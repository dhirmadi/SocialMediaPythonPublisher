# Configuration — Social Media Publisher V2

Version: 2.3  
Last Updated: November 21, 2025

## 1. Environment (.env)
Required:
- DROPBOX_APP_KEY=...
- DROPBOX_APP_SECRET=...
- DROPBOX_REFRESH_TOKEN=...
- OPENAI_API_KEY=...

Optional:
- TELEGRAM_BOT_TOKEN=...
- TELEGRAM_CHANNEL_ID=...
- INSTA_PASSWORD=... (if using instagrapi)
- EMAIL_PASSWORD=... (Gmail app password)
- SMTP_SERVER="smtp.gmail.com"
- SMTP_PORT=587
- FEATURE_ANALYZE_CAPTION=true|false (default: true)
- FEATURE_PUBLISH=true|false (default: true)
- FEATURE_KEEP_CURATE=true|false (default: true)
- FEATURE_REMOVE_CURATE=true|false (default: true)
- folder_keep=<keep-subfolder-name> (overrides [Dropbox].folder_keep)
- folder_remove=<remove-subfolder-name> (overrides [Dropbox].folder_remove)

### Feature Toggles (v2.5+)

Environment variables provide coarse-grained feature switches without editing INI files:

| Variable | Default | Behavior |
| --- | --- | --- |
| `FEATURE_ANALYZE_CAPTION` | `true` | When `false`, the workflow skips OpenAI vision analysis, caption generation, and sidecar writes. Preview/output will show “Analysis skipped”. |
| `FEATURE_PUBLISH` | `true` | When `false`, no publishers are invoked (CLI + web). The workflow still analyzes/captions (if enabled) but skips publish + archive. Web `/publish` returns HTTP 403. |
| `FEATURE_KEEP_CURATE` | `true` | When `false`, the Keep curation action is disabled in both CLI and web flows; Keep buttons are hidden and `/keep` returns HTTP 403. |
| `FEATURE_REMOVE_CURATE` | `true` | When `false`, the Remove curation action is disabled; Remove buttons are hidden and `/remove` returns HTTP 403. |

Accepted values: `true/false`, `1/0`, `yes/no`, `on/off` (case-insensitive). Any other value raises `ConfigurationError`.

Storage/Dropbox integration is always enabled—there is no toggle for the base storage feature.

## 2. INI Schema

**Note:** The config parser supports inline comments with `;` or `#`. Values are automatically stripped of trailing comments.

```ini
[Dropbox]
image_folder = /Photos/to_post
archive = archive
; Optional curation subfolders (relative to image_folder)
folder_keep = approve
folder_remove = remove          ; legacy configs may still use folder_reject

[Content]
hashtag_string = #photography #portrait   ; Note: ignored for Email/FetLife in V2
archive = true
debug = false

[openAI]
; Recommended: Separate models for optimal quality/cost balance
vision_model = gpt-4o           ; High-quality vision analysis
caption_model = gpt-4o-mini     ; Cost-effective caption generation

; OR use legacy single model (backward compatible):
; model = gpt-4o-mini           ; Use same model for both tasks

system_prompt = You are a senior social media copywriter...
role_prompt = Write a caption for:

[; Stable-Diffusion sidecar (optional, defaults shown)]
sd_caption_enabled = true
sd_caption_single_call_enabled = true
; sd_caption_model = gpt-4o-mini
; sd_caption_system_prompt = You are a fine-art photography curator...
; sd_caption_role_prompt = Write two outputs (caption, sd_caption) as JSON:

[Instagram]
name = my_username

[Email]
sender = me@gmail.com
recipient = someone@example.com
smtp_server = smtp.gmail.com
smtp_port = 587
; FetLife email behavior (caption placement and subject prefix)
caption_target = subject         ; subject | body | both
subject_mode = normal            ; normal | private | avatar
; Confirmation back to sender with tags
confirmation_to_sender = true
confirmation_tags_count = 5
confirmation_tags_nature = short, lowercase, human-friendly topical nouns; no hashtags; no emojis
```

## 3. OpenAI Model Selection (v2.1+)

### Recommended Configuration (Optimal Quality/Cost):
```ini
vision_model = gpt-4o           ; Superior vision analysis
caption_model = gpt-4o-mini     ; Excellent captions at low cost
```
**Cost:** ~$4.55 per 1,000 images | **Quality:** ⭐⭐⭐⭐⭐

### Budget Configuration:
```ini
model = gpt-4o-mini             ; Good quality for both tasks
```
**Cost:** ~$0.32 per 1,000 images | **Quality:** ⭐⭐⭐⭐

### Cost Comparison (per 1,000 images):
- **Both gpt-4o-mini:** $0.32 (budget mode)
- **Split (gpt-4o + gpt-4o-mini):** $4.55 ⭐ RECOMMENDED
- **Both gpt-4o:** $6.50 (overkill, not recommended)

### When to Use Each:
- **Photography/Art:** Use `gpt-4o` for vision (subtle details matter)
- **Casual/Social:** `gpt-4o-mini` for both (budget-friendly)
- **Production:** Split configuration (best quality/cost ratio)

### Backward Compatibility:
- Legacy `model` field still supported
- If only `model` is specified, it's used for both vision and caption
- New configs should use `vision_model` and `caption_model`

## 4. Stable‑Diffusion Caption Sidecar (v2.4+)

Generate an additional fine‑art, PG‑13 training caption and write `<image>.txt` next to the image. On archive, the sidecar moves with the image.

```ini
[openAI]
sd_caption_enabled = true                 ; Master switch (default: true)
sd_caption_single_call_enabled = true     ; Single JSON call with {caption, sd_caption}
sd_caption_model = gpt-4o-mini            ; Optional override (defaults to caption_model)
sd_caption_system_prompt = ...            ; Optional override
sd_caption_role_prompt = ...              ; Optional override

[CaptionFile]
; Phase 2 extended contextual metadata in sidecar (PG-13, artistic/contextual)
extended_metadata_enabled = false
```

Behavior:
- When enabled, the caption generator prefers a single call returning `{caption, sd_caption}`.
- On error or if disabled, falls back to legacy caption‑only path.
- Sidecar write is skipped in preview/dry/debug modes and does not block publishing.
- Sidecar file format:
  - Line 1: the `sd_caption` only
  - Line 2: blank
  - Line 3: `# ---`
  - Subsequent lines: `# key: value` (`tags` and `moderation` as JSON arrays)

## 4. Validation Rules (pydantic)
- Dropbox folder must start with "/"
- OPENAI_API_KEY must start with "sk-"
- Model names must start with "gpt-4", "gpt-3.5", "o1", or "o3"
- If Telegram enabled, both token and channel id are required
- SMTP port int in {25,465,587}; default 587
- archive/debug booleans parsed strictly
- Email caption placement validation:
  - caption_target ∈ {subject, body, both}
  - subject_mode ∈ {normal, private, avatar}

## 5. Preview Mode (v2.2+)

Test your configuration without publishing or modifying anything:

```bash
# Preview with specific config
make preview-v2 CONFIG=configfiles/fetlife.ini

# Or direct command
PYTHONPATH=publisher_v2/src poetry run python publisher_v2/src/publisher_v2/app.py \
  --config configfiles/fetlife.ini \
  --preview

# Preview specific image
PYTHONPATH=publisher_v2/src poetry run python publisher_v2/src/publisher_v2/app.py \
  --config configfiles/fetlife.ini \
  --select image.jpg \
  --preview
```

**Preview Mode Guarantees:**
- ✅ Full AI pipeline runs (vision + caption)
- ✅ Human-readable output showing all details
- ✅ No content published to any platform
- ✅ No images moved/archived on Dropbox
- ✅ No state/cache updates
- ✅ Can preview same image multiple times


