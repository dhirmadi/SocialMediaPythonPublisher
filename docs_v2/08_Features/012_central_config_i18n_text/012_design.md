<!-- docs_v2/08_Features/08_02_Feature_Design/012_central-config-i18n-text_design.md -->

# Centralized Configuration & Internationalizable Text — Feature Design

**Feature ID:** 012  
**Feature Name:** central-config-i18n-text  
**Design Version:** 1.0  
**Date:** 2025-11-22  
**Status:** Design Review  
**Author:** Architecture Team  

---

## 1. Summary

### Problem
V2 currently mixes three distinct classes of "configuration" across multiple layers:

- **Secrets** (Dropbox/OpenAI/SMTP/Telegram/Instagram/web auth) in `.env` / environment
- **Dynamic configuration** (feature flags, platform enablement, folders, model choices) in env + INI
- **Static text and rules** (AI prompts, platform limits, preview strings, web UI strings, service limits) hard-coded in Python and HTML

This blending makes it harder to:

- Safely reason about which values are secrets vs. tunables vs. static text
- Adjust prompts, platform rules, and limits without a code change and redeploy
- Prepare for internationalization (all user-facing strings are embedded in code/templates)

### Goals
1. Define a **clear separation** between secrets, dynamic configuration, and static text/rules.
2. Introduce a **static configuration layer** for AI prompts, platform limits, preview text, web UI strings, and service limits.
3. Allow **prompt and rule overrides without code changes** by reading from YAML static config.
4. Extract web UI and preview user-facing text into **language-aware config**, with English defaults.
5. Maintain **full backward compatibility** when static config is absent or partial.

### Non-Goals
- Changing the overall workflow orchestration or the shape of public CLI/web APIs.
- Altering the set of required environment variables or INI sections/keys.
- Implementing a complete i18n system (no runtime locale negotiation or language switcher).
- Moving every minor string or log message into static config (focus on major user-facing and AI-facing text).

---

## 2. Context & Assumptions

### Current State

- **Secrets:**
  - Loaded from `.env` / environment in `publisher_v2.config.loader.load_application_config`.
  - Examples: `DROPBOX_APP_KEY`, `OPENAI_API_KEY`, `EMAIL_PASSWORD`, `WEB_AUTH_TOKEN`, `WEB_AUTH_USER`, `WEB_AUTH_PASS`, `web_admin_pw`, etc.
- **Dynamic configuration:**
  - INI (`configfiles/*.ini`) for Dropbox folders, Content, Email, OpenAI models/flags, etc.
  - Environment feature flags via `FeaturesConfig` and `parse_bool_env`:
    - `FEATURE_ANALYZE_CAPTION`, `FEATURE_PUBLISH`, `FEATURE_KEEP_CURATE`, `FEATURE_REMOVE_CURATE`, `AUTO_VIEW`.
  - Web config (`WebConfig`) largely driven by env (`WEB_DEBUG`, `WEB_ADMIN_COOKIE_TTL_SECONDS`, etc.).
- **Static text & prompts:**
  - AI analysis prompts in `publisher_v2.services.ai.VisionAnalyzerOpenAI.analyze` (system + user instructions).
  - Caption prompts and SD-caption prompts in `CaptionGeneratorOpenAI` (system_prompt, role_prompt, sd_caption_role_prompt).
  - Platform behavior hints in `utils.preview.print_platform_preview` and possibly publishers (resize hints, hashtag limits).
  - Preview labels and headings in `publisher_v2.utils.preview`.
  - Web UI strings in `publisher_v2.web.templates.index.html` (titles, button labels, status text).
  - Service limits and retries:
    - OpenAI rate limiter (20 RPM) in `AIService`.
    - Tenacity retries/backoff in AI methods.
    - Platform-specific limits (Instagram hashtag 30 cap, resize hints) in preview and publishers.

### Constraints

1. **Python 3.9–3.12** support; no 3.12-only features.
2. **Backward compatibility:** CLI and web flows must behave identically when static config is missing.
3. **No secrets in static config files**: YAMLs must only contain prompts, labels, and non-sensitive numeric limits.
4. **Minimal blast radius:** Avoid large refactors of orchestrator, publishers, or web services.
5. **No additional external dependencies** beyond what is already in `pyproject.toml`.

### Assumptions

1. Static config will be **read-only at runtime** and loaded at startup (no hot reload).
2. Static config errors (file missing, malformed keys) should **fall back to in-code defaults**, not crash the app.
3. For i18n, a **single locale** will be active (e.g., `en`); multi-locale routing is future work.
4. Existing env/INI-based prompts (`[openAI].system_prompt`, `[openAI].role_prompt`) remain supported, but static config can **override code defaults** for prompts that are currently hard-coded only.

---

## 3. Requirements

### Functional Requirements

**FR1: Secret vs Dynamic vs Static Modeling**
- Define and document three categories:
  - **Secrets:** Only from env (`.env`), never written to INI/YAML.
  - **Dynamic:** Env + INI tunables (feature flags, folder names, model names, enablement flags).
  - **Static:** Prompts, user-facing text, platform rules, and service limits.
- Ensure new static config files do not include fields that *should* be secrets (e.g., API keys, passwords, tokens).

**FR2: Static Config Layer**
- Add a small static config layer under `publisher_v2.config.static`:
  - Directory: `publisher_v2/src/publisher_v2/config/static/`
  - Files (YAML, checked into repo):
    - `ai_prompts.yaml`
    - `platform_limits.yaml`
    - `preview_text.yaml`
    - `web_ui_text.en.yaml`
    - `service_limits.yaml`
- Implement a `StaticConfig` adapter with:
  - Typed Pydantic models (or nested models) for each static config domain.
  - A `load_static_config` function that:
    - Reads YAMLs from a base directory (defaulting to the packaged `config/static` directory).
    - Merges each file with in-code defaults.
    - Catches and logs parse errors while returning defaults.

**FR3: AI Prompts Static Configuration**
- Move the **major AI prompts** from code into `ai_prompts.yaml`:
  - Vision analysis:
    - System prompt (fine-art analyst).
    - User instructions block with schema and constraints.
  - Caption generation:
    - System prompt (senior social media copywriter).
    - Role/user prompt template.
  - SD-caption single-call generation:
    - System prompt (if distinct from caption).
    - Role/user prompt template describing `{caption, sd_caption}` JSON output.
- Behavior:
  - If `ai_prompts.yaml` is present and valid, `VisionAnalyzerOpenAI` and `CaptionGeneratorOpenAI` must use prompts from it.
  - If entries are missing or file is absent, they must use the current in-code fallback prompts and INI overrides.

**FR4: Platform Limits Static Configuration**
- Move primary platform rules into `platform_limits.yaml`:
  - Per-platform caption length limits (e.g., Instagram, Telegram, Email/FetLife).
  - Maximum hashtag counts per platform (e.g., Instagram 30).
  - Resize widths for Telegram and Instagram previews (currently only described in preview text).
  - Email/FetLife-specific constraints (approx 240-char subject guidance; no hashtags).
- Behavior:
  - `CaptionSpec` construction and caption formatting must read max lengths and hashtag limits from platform limits instead of hard-coded numbers.
  - Preview-only hints in `print_platform_preview` should reflect values from config (e.g., 1080px width, 1280px width, hashtag limit).
  - Defaults must exactly match current behavior when `platform_limits.yaml` is missing.

**FR5: Web UI Text Static Configuration**
- Extract key user-facing strings from `index.html` into `web_ui_text.en.yaml`, including:
  - Page title, header title.
  - Button labels: "Next image", "Admin", "Logout", "Analyze & caption", "Publish", "Keep", "Remove".
  - Panel titles: "Caption", "Administration", "Activity".
  - Common status messages and placeholders: "No image loaded yet.", "Ready.", "Admin mode: off/on", login dialog text.
- Behavior:
  - Inject a `web_ui_text` JSON blob into the rendered template via Jinja context.
  - Replace hard-coded text literals in HTML/JS with references into this blob.
  - When config entries are missing, fall back to the existing hard-coded English strings.

**FR6: Preview Text Static Configuration**
- Extract major preview labels and headings from `publisher_v2.utils.preview` into `preview_text.yaml`:
  - Section headers: "PUBLISHER V2 - PREVIEW MODE", "IMAGE SELECTED", "AI VISION ANALYSIS", "AI CAPTION GENERATION", "PUBLISHING PREVIEW", "EMAIL CONFIRMATION", "CONFIGURATION", "PREVIEW MODE - NO ACTIONS TAKEN", etc.
  - Key inline messages: "No caption yet.", "Analysis skipped (FEATURE_ANALYZE_CAPTION=false)", "Publish feature disabled (FEATURE_PUBLISH=false)", etc.
- Behavior:
  - Public preview functions must call into a `PreviewTextConfig` helper to fetch label strings.
  - When config entries are missing, behavior reverts to existing text.

**FR7: Service Limits Static Configuration**
- Define service limit knobs in `service_limits.yaml`:
  - OpenAI:
    - `ai.rate_per_minute` (default 20).
    - Retry attempts and backoff caps for analysis/caption (mirroring current tenacity values).
  - Email/SMTP:
    - SMTP timeout seconds (if not already configured elsewhere).
  - Instagram:
    - `delay_range_min_seconds`, `delay_range_max_seconds` used by the Instagram publisher.
  - Web:
    - Image cache TTL or related performance parameters, if currently hard-coded.
- Behavior:
  - `AIService` must read rate-per-minute and optionally retry parameters from static config, with the current values as defaults.
  - Publishers and web services using these limits must read them via helper functions instead of hard-coded constants.
  - Allow **environment overrides** for critical tunables (e.g., `AI_RATE_PER_MINUTE`) by layering env on top of static config.

**FR8: Single Dynamic Config Reference Document**
- Update `docs_v2/05_Configuration/CONFIGURATION.md` to:
  - Enumerate all **dynamic env + INI variables** in a table:
    - Name, type, default, allowed values, description, category (env/INI).
  - Add a distinct section that lists **secrets** vs **non-secret dynamic variables**.
  - Reference static config files and document their purpose and override behavior.

### Non-Functional Requirements

- **NFR1: Performance**
  - Static config loading happens once at process startup; no per-request disk I/O.
  - Runtime access to static config is O(1) (in-memory structures or cached lookups).
- **NFR2: Reliability**
  - Corrupt or missing static config files must not crash the app; fall back to sane defaults and log a warning.
- **NFR3: Maintainability**
  - Static config models and loaders are small, focused, and documented.
  - Existing modules (AI, preview, web) are only lightly touched to replace literals with lookups.

---

## 4. Architecture & Design

### 4.1 Static Config Module & Models

**New module:** `publisher_v2.config.static_loader`

Responsibilities:

- Define Pydantic models for static config domains:
  - `AIPromptsConfig`
  - `PlatformLimitsConfig`
  - `PreviewTextConfig`
  - `WebUITextConfig`
  - `ServiceLimitsConfig`
  - `StaticConfig` (root aggregator)
- Provide a `load_static_config(base_dir: str | None = None) -> StaticConfig` function:
  - Determine base directory:
    - If `PV2_STATIC_CONFIG_DIR` env var is set, use that as root.
    - Else, use the packaged `publisher_v2/config/static` directory (via `Path(__file__).with_name("static")`).
  - For each YAML file (`*.yaml`):
    - Attempt to load using `yaml.safe_load`.
    - Merge with in-code defaults baked into the corresponding Pydantic model.
    - On any error (file missing, parse error), log a warning and instantiate the model with its defaults.
- Expose a cached accessor:
  - `@lru_cache(maxsize=1) def get_static_config() -> StaticConfig: ...`
  - This is the main entry point used by other modules (AI, preview, web).

**Static config directory layout (packaged):**

- `publisher_v2/config/static/ai_prompts.yaml`
- `publisher_v2/config/static/platform_limits.yaml`
- `publisher_v2/config/static/preview_text.yaml`
- `publisher_v2/config/static/web_ui_text.en.yaml`
- `publisher_v2/config/static/service_limits.yaml`

These files will contain **default English** content and numeric limits matching current behavior, making them both runtime defaults and human-readable reference.

### 4.2 AI Prompts Integration

**Model:** `AIPromptsConfig`

Conceptual shape:

- `vision.system`: string
- `vision.user`: string (the structured JSON schema instructions)
- `caption.system`: string
- `caption.role`: string
- `sd_caption.system`: string
- `sd_caption.role`: string

**Changes to `VisionAnalyzerOpenAI`:**

- In `__init__`, fetch static config:
  - `prompts = get_static_config().ai_prompts`
- Replace hard-coded system and user prompt strings with values from `prompts`:
  - System message content → `prompts.vision.system` (fallback to existing literal if missing).
  - User "Analyze this image and return strict JSON..." block → `prompts.vision.user` (fallback).
- The JSON schema and key list remain the same; they're just defined in static config.

**Changes to `CaptionGeneratorOpenAI`:**

- In `__init__`, fetch static config:
  - `prompts = get_static_config().ai_prompts`
- Use static config values with fallback layering:
  - `self.system_prompt`:
    - Prefer `prompts.caption.system`, else current `OpenAIConfig.system_prompt` (INI/env), else existing default.
  - `self.role_prompt`:
    - Prefer `prompts.caption.role`, else current `OpenAIConfig.role_prompt`, else existing default.
  - `self.sd_caption_system_prompt`:
    - Prefer `prompts.sd_caption.system`, else `self.system_prompt`.
  - `self.sd_caption_role_prompt`:
    - Prefer `prompts.sd_caption.role`, else existing sd-caption role literal.

**Retry & rate limits (interaction with ServiceLimitsConfig):**

- For tenacity decorators:
  - Keep current retry behavior in code for now, but allow `service_limits.ai` to define:
    - `max_attempts` (default 3).
    - `backoff_min_seconds` (default 1).
    - `backoff_max_seconds` (default 8).
  - In this iteration, we keep decorators static to avoid overcomplication; `ServiceLimitsConfig` is primarily used by `AIService` and publishers.

### 4.3 Platform Limits Integration

**Model:** `PlatformLimitsConfig`

Conceptual shape:

- `instagram.max_caption_length`
- `instagram.max_hashtags`
- `instagram.resize_width_px`
- `telegram.max_caption_length`
- `telegram.resize_width_px`
- `email.max_caption_length`
- `email.subject_max_length`

Usage:

- Introduce a small helper in the captions/formatting layer (where `CaptionSpec` is created) that:
  - Loads platform limits from `get_static_config().platform_limits`.
  - Applies `max_caption_length` and `max_hashtags` per platform.
- Update preview-only hints in `print_platform_preview` to use values from `PlatformLimitsConfig`:
  - Replace hard-coded "max 1280px" / "max 1080px" strings with values from config.
  - Replace the `>30` Instagram hashtags limit with `instagram.max_hashtags`.
- Ensure that existing behavior (lengths, hashtag limit, resize hints) is preserved by default via the YAML defaults.

### 4.4 Web UI Text Integration

**Model:** `WebUITextConfig`

Conceptual shape (partial, focused on high-impact strings):

- `title`: page `<title>`
- `header.title`: header `<h1>` text
- `buttons.next`, `buttons.admin`, `buttons.logout`, `buttons.analyze`, `buttons.publish`, `buttons.keep`, `buttons.remove`
- `panels.caption.title`, `panels.admin.title`, `panels.activity.title`
- `placeholders.image_empty`, `status.ready`, `admin.mode_on`, `admin.mode_off`
- `admin.dialog.title`, `admin.dialog.description`, `admin.dialog.password_placeholder`

Template changes:

- Extend `index` route in `web.app` to pass `web_ui_text` into the Jinja context:
  - Load via `get_static_config().web_ui_text` with fallback to a built-in English dict.
- In `index.html`:
  - Add a small `<script>` block that reads a server-rendered `window.WEB_UI_TEXT` JSON (from a Jinja variable).
  - Replace hard-coded literals with lookups into `WEB_UI_TEXT`:
    - E.g., `document.title`, header `<h1>`, button `.textContent`, placeholders, and common status strings.
- Keep current English text in the template as fallback where reasonable (e.g., use Jinja `{{ web_ui_text.buttons.next or "Next image" }}`).

### 4.5 Preview Text Integration

**Model:** `PreviewTextConfig`

Conceptual shape:

- `headers.preview_mode`, `headers.image_selected`, `headers.vision_analysis`, `headers.caption_generation`, `headers.publishing_preview`, `headers.email_confirmation`, `headers.configuration`, `headers.preview_footer`
- `messages.no_caption_yet`, `messages.analysis_skipped`, `messages.publish_disabled`, `messages.preview_footer_lines` (list)

Changes to `publisher_v2.utils.preview`:

- At module level or at function entry, fetch `preview_text = get_static_config().preview_text`.
- Replace hard-coded header strings and key messages with values from `preview_text`, with in-code defaults as fallbacks.
- Keep console emoji and visual formatting (lines, spacing) unchanged to preserve UX.

### 4.6 Service Limits Integration

**Model:** `ServiceLimitsConfig`

Conceptual shape:

- `ai.rate_per_minute`
- `ai.max_attempts`
- `ai.backoff_min_seconds`
- `ai.backoff_max_seconds`
- `smtp.timeout_seconds`
- `instagram.delay_min_seconds`
- `instagram.delay_max_seconds`
- `web.image_cache_ttl_seconds` (if applicable)

Changes:

- `AIService`:
  - Replace the hard-coded `AsyncRateLimiter(rate_per_minute=20)` with:
    - `rate = service_limits.ai.rate_per_minute` layered with `AI_RATE_PER_MINUTE` env override.
    - Instantiate `AsyncRateLimiter(rate_per_minute=rate)`.
- Instagram publisher (where delays are currently configured):
  - Read delay range from `service_limits.instagram` (with env override if an appropriate variable already exists or is added).
- SMTP usage (if using a library that supports timeout):
  - Read timeout from `service_limits.smtp.timeout_seconds` and pass to SMTP client where feasible.
- Keep tenacity decorators for AI methods as-is for this iteration; document that future work may move retry config fully into `ServiceLimitsConfig`.

### 4.7 Documentation & Config Reference

- Update `docs_v2/05_Configuration/CONFIGURATION.md`:
  - Add a "Configuration Model" section explaining Secrets vs Dynamic vs Static.
  - Add tables listing:
    - All secret environment variables (name, where used, description).
    - All dynamic env + INI variables (name, type, default, allowed values, description).
  - Add a subsection for each static config file:
    - Path, purpose, and example snippet.
- Update `docs_v2/03_Architecture/ARCHITECTURE.md` (and/or `SYSTEM_DESIGN.md`) to mention:
  - The static config layer and which modules read from it.
  - How static config interacts with existing env + INI configuration.

---

## 5. Data Model Changes

- **New models (static):**
  - `AIPromptsConfig`
  - `PlatformLimitsConfig`
  - `PreviewTextConfig`
  - `WebUITextConfig`
  - `ServiceLimitsConfig`
  - `StaticConfig`
- **Existing models (dynamic):**
  - No changes to `ApplicationConfig` fields for this feature (static config accessed via `static_loader` rather than embedded).
- **No persisted storage changes:** All static config is file-based YAML; no database changes.

---

## 6. API & Behavior Changes

### CLI

- No new CLI flags.
- Behavior when static config files are missing:
  - Identical to current behavior (same prompts, limits, and preview text).
- Behavior when static config files are present:
  - AI prompts, platform limits, and preview text may change according to config content.

### Web API

- `GET /`:
  - Template context extended with `web_ui_text` and possibly a `static_config_version` indicator.
- Other API endpoints:
  - No shape changes; responses stay the same.
- Indirect behavior changes:
  - Captions and prompt-driven analysis content may differ if prompts are updated via static config.

### Internal APIs

- `VisionAnalyzerOpenAI` and `CaptionGeneratorOpenAI` now depend on `get_static_config()` to resolve prompts, but their public signatures remain unchanged.
- `AIService` now uses `ServiceLimitsConfig` to determine `AsyncRateLimiter` throughput.
- `utils.preview` and `web.templates.index.html` use `PreviewTextConfig` / `WebUITextConfig` instead of inlined strings.

---

## 7. Error Handling

- Static config loading:
  - If a YAML file is missing:
    - Log a warning (`static_config_file_missing`) and use model defaults.
  - If a YAML file is malformed or fields are invalid:
    - Log a warning (`static_config_parse_error`) including filename and error summary.
    - Use model defaults for that domain.
- Runtime:
  - If a static config value is missing at lookup time:
    - Use a hard-coded fallback string or limit consistent with current behavior.
  - No new user-visible error responses are introduced by this feature.

---

## 8. Testing Strategy

### Unit Tests

- `publisher_v2/tests/test_static_config_loader.py`:
  - Loading from packaged defaults returns expected English text and numeric limits.
  - Missing files fall back to defaults and log a warning.
  - Invalid YAML content in one file does not prevent others from loading.
- AI prompt resolution:
  - Tests verifying that `VisionAnalyzerOpenAI` and `CaptionGeneratorOpenAI` read prompts from `AIPromptsConfig` when provided.
  - Tests verifying fallback to existing defaults when config values are missing.
- Platform limits:
  - Tests verifying that caption max lengths and hashtag limits come from `PlatformLimitsConfig`.
- Service limits:
  - Tests verifying that `AIService` uses the configured rate-per-minute (with env override).

### Integration & E2E Tests

- Web interface:
  - Extend existing `test_e2e_web_interface_mvp.py` to assert key strings are rendered from `web_ui_text` while remaining English by default.
- Preview:
  - Extend preview tests to assert that header text and key messages match `preview_text` defaults.
- AI behavior:
  - Reuse existing AI tests to ensure behavior does not regress when static config is loaded.

### Non-Regression

- Run the full pytest suite with and without custom static config overrides to ensure:
  - No change in behavior when static config is absent.
  - Predictable changes only where config has been customized.

---

## 9. Migration & Rollout

### Migration Path

1. Add static config loader and default YAML files under `publisher_v2/config/static`.
2. Wire AI, preview, and web UI modules to static config, with strong fallbacks to existing behavior.
3. Update documentation to describe the new configuration model and static files.

### Rollout Plan

1. Deploy to development with default static config:
  - Validate that behavior is unchanged.
2. Experiment with modified prompts and limits via static config in staging.
3. Deploy to production with defaults, then gradually introduce config tweaks as needed.

### Rollback Plan

- If issues arise:
  - Revert code changes and static YAML files.
  - Because defaults mirror current behavior and static config is optional, rollback is straightforward.

---

## 10. Success Criteria

- All tests pass with static config present and absent.
- AI prompts and platform rules can be tuned via YAML without code changes.
- Web UI and preview strings are sourced from static text config by default, but remain English and unchanged when config is not customized.
- Operators have clear documentation separating secrets, dynamic tunables, and static text/rules.
- Future i18n is achievable by adding `web_ui_text.<locale>.yaml` (and, optionally, `preview_text.<locale>.yaml`) without additional code changes beyond locale selection.

