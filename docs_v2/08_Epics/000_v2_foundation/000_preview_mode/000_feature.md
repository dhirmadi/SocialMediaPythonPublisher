# Preview Mode Guide — Publisher V2

Version: 2.2  
Last Updated: December 21, 2025

## Overview

Preview mode allows you to test your configuration and see exactly what will be published **without taking any actions**. Perfect for:
- Tuning AI prompts and seeing results
- Verifying which platforms are enabled
- Checking caption quality before posting
- Testing new configurations safely

---

## Quick Start

```bash
# Using Makefile (easiest)
make preview-v2 CONFIG=configfiles/fetlife.ini

# Direct command
PYTHONPATH=publisher_v2/src uv run python publisher_v2/src/publisher_v2/app.py \
  --config configfiles/fetlife.ini \
  --preview

# Preview specific image
make preview-v2 CONFIG=configfiles/fetlife.ini SELECT=sunset.jpg
```

---

## What Preview Mode Shows

### 1. Configuration Summary
- Config file path
- Vision model being used (e.g., gpt-4o)
- Caption model being used (e.g., gpt-4o-mini)

### 2. Image Details
- Selected filename
- Dropbox folder path
- SHA256 hash (truncated)
- Dropbox temporary URL
- Status (new/previously posted)

### 3. AI Vision Analysis
- Full description (from vision model)
- Detected mood
- Extracted tags (all of them)
- NSFW flag
- Safety labels (if any)

### 4. Generated Caption
- Platform target
- Caption style
- Maximum length
- Full caption text
- Character count
- Hashtag count

### 5. Platform Preview
- Which platforms are enabled/disabled
- Caption for each platform (with platform-specific formatting)
- Platform-specific constraints (e.g., Instagram hashtag limit)
- Image resizing info (e.g., Telegram 1280px)
- Email/FetLife specifics: caption placement (subject/body/both), subject mode (normal/private/avatar), subject preview

---

## Example Output

```
══════════════════════════════════════════════════════════════════
  PUBLISHER V2 - PREVIEW MODE
══════════════════════════════════════════════════════════════════

⚙️  CONFIGURATION
──────────────────────────────────────────────────────────────────
  Config File:    configfiles/fetlife.ini
  Vision Model:   gpt-4o
  Caption Model:  gpt-4o-mini

📸 IMAGE SELECTED
──────────────────────────────────────────────────────────────────
  File:        vintage_portrait.jpg
  Folder:      /Photos/bondage_fetlife
  SHA256:      a3f2b8c9d4e5... (truncated)
  Dropbox URL: https://dl.dropboxusercontent.com/temp/xyz123...
  Status:      ✓ New (not previously posted)

🔍 AI VISION ANALYSIS (gpt-4o)
──────────────────────────────────────────────────────────────────
  Description: Contemplative portrait with dramatic chiaroscuro
               lighting, subject in vintage crimson gown against
               textured stone backdrop

  Mood:        nostalgic, ethereal, contemplative

  Tags:        portrait, chiaroscuro, vintage, fashion,
               architecture, golden_hour, editorial,
               dramatic_lighting

  NSFW:        false
  Safety:      None

✍️  AI CAPTION GENERATION (gpt-4o-mini)
──────────────────────────────────────────────────────────────────
  Platform:    generic
  Style:       minimal_poetic
  Max Length:  2200 chars

  Caption:
  "Lost in the timeless dance of light and shadow. Every
  "moment captured tells a story beyond words. follow me on my
  "patreon (evertphotography) for more content #modelnotonfet
  "#portrait #vintage #editorial"

  Length:      152 characters
  Hashtags:    4

📤 PUBLISHING PREVIEW
──────────────────────────────────────────────────────────────────
  ✓ Telegram   (ENABLED)
     → Image will be resized to max 1280px width
     Caption: "Lost in the timeless dance of light and shadow..."

  ✓ Email      (ENABLED)
     → Subject: "Lost in the timeless dance of light and shadow..."
     Caption: Full caption as above

  ✗ Instagram  (DISABLED)

  Summary: 2 enabled, 1 disabled

⚠️  PREVIEW MODE - NO ACTIONS TAKEN
──────────────────────────────────────────────────────────────────
  • No content published to any platform
  • No images moved or archived on Dropbox
  • No state/cache updates

  To publish for real, run without --preview flag.
══════════════════════════════════════════════════════════════════
```

---

## Common Use Cases

### 1. Testing New Prompts

Modify system_prompt or role_prompt in your config, then preview:

```bash
make preview-v2 CONFIG=configfiles/test.ini
```

Compare results and iterate until satisfied.

### 2. Verifying Platform Selection

Check which platforms will receive content:

```bash
make preview-v2 CONFIG=configfiles/fetlife.ini
```

Look for ✓/✗ marks in the Publishing Preview section.

### 3. Testing Model Combinations

Try different vision_model/caption_model combinations:

```ini
# Test 1: Both gpt-4o-mini (budget)
vision_model = gpt-4o-mini
caption_model = gpt-4o-mini

# Test 2: Split (recommended)
vision_model = gpt-4o
caption_model = gpt-4o-mini

# Test 3: Both gpt-4o (premium)
vision_model = gpt-4o
caption_model = gpt-4o
```

Preview each to compare vision analysis quality.

### 4. Checking Specific Images

Preview a particular image before posting:

```bash
PYTHONPATH=publisher_v2/src uv run python publisher_v2/src/publisher_v2/app.py \
  --config configfiles/fetlife.ini \
  --select risky_image.jpg \
  --preview
```

Check NSFW flag and caption appropriateness.

### 5. Debugging Vision Analysis

If captions seem off, preview to see what the vision model detected:

```bash
make preview-v2 CONFIG=configfiles/fetlife.ini
```

Look at Description, Mood, and Tags - these feed into caption generation.

---

## Guarantees

Preview mode **guarantees** that:

✅ **No Publishing**: Zero API calls to Telegram/Instagram/Email  
✅ **No Archiving**: Images stay in original Dropbox folder  
✅ **No State Changes**: Posted image cache not updated  
✅ **Repeatable**: Same image can be previewed multiple times  
✅ **Full AI**: Vision analysis and caption generation run for real  

---

## Differences from --debug and --dry-publish

| Feature | --preview | --debug | --dry-publish |
|---------|-----------|---------|---------------|
| Runs AI pipeline | ✅ | ✅ | ✅ |
| Publishes to platforms | ❌ | ❌ | ❌ |
| Archives images | ❌ | ❌ | ❌ |
| Updates cache | ❌ | ❌ | ❌ |
| Output format | Human-readable | JSON logs | JSON logs |
| Shows vision analysis | ✅ | Logs only | Logs only |
| Shows platform details | ✅ | ❌ | ❌ |
| Purpose | Content tuning | Development | Testing |

---

## Tips

1. **Start with Preview**: Always preview before first real run with new config
2. **Iterate Prompts**: Use preview to refine system_prompt until captions are perfect
3. **Test Images**: Preview NSFW/borderline content to verify safety detection
4. **Compare Models**: Preview same image with different model configs to see quality differences
5. **Document Results**: Save preview output to compare caption styles over time

---

## Troubleshooting

### "No images found"
- Check `image_folder` path in config
- Verify Dropbox credentials in `.env`
- Ensure folder contains .jpg/.jpeg/.png files

### "Selected file not found"
- Check filename spelling (case-sensitive)
- File must be in configured `image_folder`
- Don't include path, just filename

### Vision analysis seems wrong
- Try upgrading to `vision_model = gpt-4o`
- Check image quality (not corrupted)
- Verify Dropbox temporary link is accessible

### Caption doesn't match image
- Review vision analysis output first
- Adjust `system_prompt` to guide caption style
- Try different temperature in code (currently 0.7)

---

## Next Steps

After previewing and tuning:

1. **Remove --preview flag** to publish for real
2. **Monitor first few posts** to ensure quality
3. **Adjust config** if needed and preview again
4. **Automate** with cron/scheduler once satisfied

```bash
# After successful previews, publish for real:
make run-v2 CONFIG=configfiles/fetlife.ini
```

