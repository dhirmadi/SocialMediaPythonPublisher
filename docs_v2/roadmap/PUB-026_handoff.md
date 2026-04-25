# Implementation Handoff: PUB-026 — AI Alt Text Generation

**Hardened:** 2026-04-25
**Status:** Ready for implementation

## For Claude Code

### Test-first targets

| AC | Test file | Key test cases |
|----|-----------|----------------|
| AC-01 | `publisher_v2/tests/test_alt_text.py` | `ImageAnalysis(description="x", mood="y")` works without `alt_text`; `ImageAnalysis(..., alt_text="test")` stores value |
| AC-02 | same | Assert `alt_text` appears in `_DEFAULT_VISION_SYSTEM_PROMPT` and `_DEFAULT_VISION_USER_PROMPT` |
| AC-03 | same | Mock OpenAI returning `{"alt_text": "A woman..."}` → `analysis.alt_text == "A woman..."` |
| AC-04 | same | Mock OpenAI returning garbage → fallback dict has `alt_text=None`, no crash |
| AC-05 | same | Mock OpenAI returning valid JSON but no `alt_text` key → `analysis.alt_text is None` |
| AC-06 | same | `features.alt_text_enabled=True` + `analysis.alt_text="test"` → context has `"alt_text": "test"` |
| AC-07 | same | `features.alt_text_enabled=False` → context does NOT have `"alt_text"` key |
| AC-08 | `publisher_v2/tests/test_publishers_platforms.py` | Telegram + Email mocks: publish with `context={"alt_text": "x"}` → success, no error |
| AC-09 | `publisher_v2/tests/test_alt_text.py` | `build_metadata_phase2(analysis_with_alt)` → dict contains `"alt_text"` |
| AC-10 | same | `build_metadata_phase2(analysis_without_alt)` → dict does NOT contain `"alt_text"` |
| AC-11 | same | `AnalysisResponse` model has `alt_text` field; mock web service returns it |
| AC-12 | same | `print_vision_analysis` with `alt_text` → captured stdout contains "Alt text:" |
| AC-13 | (all existing tests) | `uv run pytest -v` passes without modification |

### Mock boundaries

| External service | Mock strategy | Existing fixture |
|-----------------|---------------|------------------|
| OpenAI Chat Completions | `unittest.mock.AsyncMock` on `AsyncOpenAI().chat.completions.create` | Pattern in `test_vision_cost_optimization.py`, `test_vision_analyzer_expanded_fields.py` |
| Storage | Not needed for this item | — |
| httpx (vision download) | `unittest.mock.AsyncMock` | Pattern in `test_vision_cost_optimization.py` |

### Files likely touched

| Area | Files to modify | Files to create |
|------|-----------------|-----------------|
| Core models | `publisher_v2/src/publisher_v2/core/models.py` | — |
| AI service | `publisher_v2/src/publisher_v2/services/ai.py` | — |
| AI prompts YAML | `publisher_v2/src/publisher_v2/config/static/ai_prompts.yaml` | — |
| Workflow | `publisher_v2/src/publisher_v2/core/workflow.py` | — |
| Sidecar / captions | `publisher_v2/src/publisher_v2/utils/captions.py` | — |
| Web models | `publisher_v2/src/publisher_v2/web/models.py` | — |
| Web service | `publisher_v2/src/publisher_v2/web/service.py` | — |
| Preview | `publisher_v2/src/publisher_v2/utils/preview.py` | — |
| Tests | — | `publisher_v2/tests/test_alt_text.py` |

### Implementation sequence

**Phase 1: Model + Prompt**
1. Add `alt_text: str | None = None` to `ImageAnalysis` dataclass (AC-01)
2. Extend `_DEFAULT_VISION_SYSTEM_PROMPT` and `_DEFAULT_VISION_USER_PROMPT` with `alt_text` key and constraints (AC-02)
3. Extend `ai_prompts.yaml` vision section with `alt_text` (AC-02)
4. Add `alt_text=self._opt_str(data.get("alt_text"))` to `analyze()` parser (AC-03)
5. Add `"alt_text": None` to the JSON decode error fallback dict (AC-04, AC-05)

**Phase 2: Publisher context**
6. Extend context dict in `workflow.py` to include `alt_text` when enabled (AC-06, AC-07)
7. Verify Telegram + Email are unaffected (AC-08)

**Phase 3: Sidecar + Web + Preview**
8. Add `alt_text` to `build_metadata_phase2()` in `captions.py` (AC-09, AC-10)
9. Add `alt_text` to `AnalysisResponse` and wire in `analyze_and_caption` (AC-11)
10. Add `alt_text` display in `print_vision_analysis()` (AC-12)

**Phase 4: Regression**
11. Run full test suite to verify no regressions (AC-13)

### Key implementation details

#### Vision prompt extension (ai.py)

Add to the key list in `_DEFAULT_VISION_SYSTEM_PROMPT`:

```
"  description, mood, tags, nsfw, safety_labels, subject, style, lighting, camera, "
"clothing_or_accessories, aesthetic_terms, pose, composition, background, color_palette, alt_text\n\n"
```

Add type constraint:

```
"- alt_text: string (≤125 characters, plain descriptive sentence for screen readers; "
"describe what is visually depicted, not mood or interpretation; no hashtags or promotional language)\n"
```

Similarly update `_DEFAULT_VISION_USER_PROMPT` to include `alt_text` in the key list.

#### ImageAnalysis parser (ai.py, in analyze())

```python
analysis = ImageAnalysis(
    # ... existing fields ...
    color_palette=self._opt_str(data.get("color_palette")),
    alt_text=self._opt_str(data.get("alt_text")),
)
```

#### Workflow context (workflow.py)

```python
ctx: dict[str, Any] = {"analysis_tags": analysis.tags} if analysis else {}
if analysis and config.features.alt_text_enabled and analysis.alt_text:
    ctx["alt_text"] = analysis.alt_text
context = ctx if ctx else None
```

#### Sidecar metadata (captions.py)

```python
# In build_metadata_phase2, after existing fields:
if getattr(analysis, "alt_text", None):
    meta["alt_text"] = analysis.alt_text
```

#### Web response (web/service.py)

```python
# In analyze_and_caption, when building AnalysisResponse:
alt_text=analysis.alt_text if config.features.alt_text_enabled else None,
```

### Non-negotiables for this item

- [ ] Preview mode: Alt text displayed in CLI preview; no side effects
- [ ] Secrets: N/A (no new secrets)
- [ ] Auth: N/A (no new web endpoints, existing analysis endpoint unchanged)
- [ ] Async hygiene: N/A (no new blocking calls)
- [ ] Backward compatibility: Existing `ImageAnalysis` constructors without `alt_text` must work (default `None`)
- [ ] Coverage: ≥80% on `services/ai.py`, `core/models.py`, `utils/captions.py`

### Claude Code command

```text
/implement docs_v2/roadmap/PUB-026_ai-alt-text.md
```
