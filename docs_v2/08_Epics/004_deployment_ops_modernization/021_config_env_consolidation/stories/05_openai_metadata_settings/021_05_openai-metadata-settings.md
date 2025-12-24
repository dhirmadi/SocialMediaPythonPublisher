# Story: OpenAI and Metadata Settings

**Feature ID:** 021  
**Story ID:** 021-05  
**Name:** openai-metadata-settings  
**Status:** Proposed  
**Date:** 2025-12-22  
**Parent Feature:** 021_config_env_consolidation

## Summary

Implement JSON parsing for `OPENAI_SETTINGS`, `CAPTIONFILE_SETTINGS`, and `CONFIRMATION_SETTINGS` environment variables. These consolidate AI model configuration, caption file metadata options, and confirmation email behavior from the INI file.

## Scope

- Parse `OPENAI_SETTINGS` JSON: vision_model, caption_model, system_prompt, role_prompt, sd_caption_* options
- Parse `CAPTIONFILE_SETTINGS` JSON: extended_metadata_enabled, artist_alias
- Parse `CONFIRMATION_SETTINGS` JSON: confirmation_to_sender, confirmation_tags_count, confirmation_tags_nature
- Parse `CONTENT_SETTINGS` JSON: hashtag_string, archive, debug
- Apply to respective Pydantic config models
- Implement precedence: JSON env vars > INI sections

## Out of Scope

- OPENAI_API_KEY (remains as individual env var for security)
- Changes to AI service behavior
- Caption file format changes

## Acceptance Criteria

### OPENAI_SETTINGS

- Given `OPENAI_SETTINGS='{"vision_model": "gpt-4o", "caption_model": "gpt-4o-mini", "system_prompt": "Custom prompt", "role_prompt": "Write:"}'`, when config loads, then `OpenAIConfig` uses those values.
- Given `OPENAI_SETTINGS` provides only `vision_model`, when config loads, then defaults are used for other fields.
- Given `OPENAI_SETTINGS` is not set, when config loads, then fallback to INI `[openAI]` section occurs.

### CAPTIONFILE_SETTINGS

- Given `CAPTIONFILE_SETTINGS='{"extended_metadata_enabled": true, "artist_alias": "Eoel"}'`, when config loads, then `CaptionFileConfig` uses those values.
- Given `CAPTIONFILE_SETTINGS` is not set, when config loads, then fallback to INI `[CaptionFile]` section occurs.

### CONFIRMATION_SETTINGS

- Given `CONFIRMATION_SETTINGS='{"confirmation_to_sender": true, "confirmation_tags_count": 5, "confirmation_tags_nature": "short nouns"}'`, when config loads, then `EmailConfig` uses those values for confirmation fields.
- Given `CONFIRMATION_SETTINGS` is not set, when config loads, then fallback to INI `[Hashtags]`/`[Email]` sections occurs.

### CONTENT_SETTINGS

- Given `CONTENT_SETTINGS='{"hashtag_string": "#art #photography", "archive": true, "debug": false}'`, when config loads, then `ContentConfig` uses those values.
- Given `CONTENT_SETTINGS` is not set, when config loads, then fallback to INI `[Content]` section occurs.

## Technical Notes

`OPENAI_SETTINGS` schema:
```json
{
  "vision_model": "gpt-4o",
  "caption_model": "gpt-4o-mini",
  "system_prompt": "...",
  "role_prompt": "...",
  "sd_caption_enabled": true,
  "sd_caption_single_call_enabled": true,
  "sd_caption_model": null,
  "sd_caption_system_prompt": null,
  "sd_caption_role_prompt": null
}
```

Note: `OPENAI_API_KEY` remains a separate env var (not in JSON) for security and simplicity.

`CAPTIONFILE_SETTINGS` schema:
```json
{
  "extended_metadata_enabled": false,
  "artist_alias": "Artist Name"
}
```

`CONFIRMATION_SETTINGS` schema:
```json
{
  "confirmation_to_sender": true,
  "confirmation_tags_count": 5,
  "confirmation_tags_nature": "short, lowercase, human-friendly topical nouns; no hashtags; no emojis"
}
```

## Dependencies

- Story 01: JSON Parser Infrastructure
- Story 02/03: CONFIRMATION_SETTINGS fields are added to EmailConfig (which is instantiated in Story 02 using EMAIL_SERVER from Story 03)

