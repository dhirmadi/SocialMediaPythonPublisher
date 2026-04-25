# Implementation Handoff: PUB-029 — Brand Voice Matching

**Hardened:** 2026-04-25  
**Status:** Ready for implementation

This handoff focuses on the **remaining work** after PUB-039, which already introduced:
- `content.voice_profile` (1–20 examples) in config schema + env/orchestrator loading
- `features.voice_matching_enabled` flag
- voice examples prepended into `CaptionSpec.examples` when enabled
- config logging redacts `voice_profile`

---

## Test-first targets

| AC | Test file | Key test cases |
|----|-----------|----------------|
| AC-01 | `publisher_v2/tests/test_voice_matching.py` | Truncates voice examples to budget deterministically (preserve order, drop from end); default budget path |
| AC-02 | same | Prompt contains voice block delimiters + “style references only” instruction when enabled |
| AC-03 | same | Multi-platform prompt still contains per-platform blocks and includes (truncated) voice examples in each block |
| AC-04 | same | When disabled or empty profile: prompt contains **no** voice block (string equality / snapshot) |
| AC-05 | `publisher_v2/tests/config/test_loader_integration.py` | INI `[Content] voice_profile = ["a","b"]` parsed; invalid JSON raises ConfigurationError |
| AC-06 | `publisher_v2/tests/web/test_web_settings_voice_profile.py` | Admin-only endpoint/UI path updates in-memory voice profile; non-admin cannot access |
| AC-07 | `publisher_v2/tests/test_preview_voice_matching.py` | Preview output indicates applied voice matching + count, without printing the examples |

---

## Likely code changes

### 1) Token budget + injection-hardening block (core)
- `publisher_v2/src/publisher_v2/services/ai.py`
  - Add a helper to build a bounded “voice examples” block (rough tokens \(~ chars/4\))
  - Integrate it into the multi-platform prompt builder used by caption generation

### 2) INI support
- `publisher_v2/src/publisher_v2/config/loader.py`
  - In the INI fallback branch for `[Content]`, parse optional `voice_profile` JSON string and set `ContentConfig.voice_profile`

### 3) Web UI editor
- `publisher_v2/src/publisher_v2/web/`
  - Add an admin-only API route to set `voice_profile` at runtime (session/tenant service instance)
  - Add a minimal settings section in the single-page UI (textarea + save button)

### 4) Preview output
- `publisher_v2/src/publisher_v2/utils/preview.py`
  - Print whether voice matching enabled and how many examples were applied after truncation (do **not** print the examples)

---

## Non-negotiables

- **No secrets/personal text in logs**: do not log `voice_profile` contents or the constructed examples block.
- **Backward-compatible**: feature off or empty profile must be identical prompt behavior to today.
- **Preview safety**: display-only; no publish/archive/state changes.

