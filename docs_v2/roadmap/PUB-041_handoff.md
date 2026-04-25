# Implementation Handoff: PUB-041 — Vision Cost Optimization & Richer Caption Inputs

**Hardened:** 2026-04-25
**Status:** Ready for implementation

## For Claude Code

### Test-first targets

| AC | Test file | Key test cases |
|----|-----------|----------------|
| AC-01 | `publisher_v2/tests/test_vision_cost_optimization.py` | Mock httpx download + mock OpenAI; assert data URL sent, image dims ≤1024 |
| AC-02 | same | Assert `detail` in `image_url` dict matches config |
| AC-03 | same | `vision_max_dimension=0` → presigned URL passed directly, no download |
| AC-04 | same | Small image (800×600, max=1024) → no upscale but still JPEG data URL |
| AC-05 | same | 4000×6000 input → 683×1024 output (aspect preserved) |
| AC-06 | `publisher_v2/tests/test_utils_images.py` | `resize_image_bytes` unit tests: resize, no-upscale, PNG→JPEG, quality |
| AC-07 | `publisher_v2/tests/test_vision_cost_optimization.py` | Primary fails AIServiceError + fallback enabled → fallback called with higher settings |
| AC-08 | same | Fallback fires → `vision_fallback_triggered` in caplog at WARNING |
| AC-09 | same | Fallback disabled → AIServiceError raised directly; fallback also fails → same |
| AC-10 | same | Fallback produces at most 1 additional OpenAI call chain (mock call counts) |
| AC-11 | same | Both primary and fallback `AIUsage` returned in tuple |
| AC-12 | `publisher_v2/tests/test_analysis_context.py` | `build_analysis_context` includes lighting/composition/etc when non-None |
| AC-13 | same | `None` fields omitted from output string |
| AC-14 | same | Long strings truncated at 50 chars; aesthetic_terms capped at 10 |
| AC-15 | same | nsfw/safety_labels/camera/clothing/background/subject never in output |
| AC-16 | same | Grep all three call sites use `build_analysis_context` (integration) |
| AC-17 | `publisher_v2/tests/test_vision_cost_optimization.py` | `OpenAIConfig()` defaults: max_dim=1024, detail="low", fallback_enabled=True |
| AC-18 | same | `OpenAIConfig(vision_detail="bad")` → `ValidationError` |
| AC-19 | same | Orchestrator v2 payload with vision fields → mapped into `OpenAIConfig` |
| AC-20 | same | `OPENAI_SETTINGS` JSON with vision fields → standalone mode parses correctly |
| AC-21 | same | `vision_max_dimension=0, vision_detail="high"` → presigned URL, no resize (pre-PUB-041 behavior) |

### Mock boundaries

| External service | Mock strategy | Existing fixture |
|-----------------|---------------|------------------|
| OpenAI Chat Completions | `unittest.mock.AsyncMock` on `AsyncOpenAI().chat.completions.create` | Existing pattern in AI tests |
| Image download (httpx) | `unittest.mock.AsyncMock` or `httpx.MockTransport` | Return fixture JPEG bytes |
| Storage (for web path) | `unittest.mock.AsyncMock` on `get_temporary_link` | Existing storage mocks |
| Orchestrator runtime API | `unittest.mock.AsyncMock` on `OrchestratorClient` | `config/test_orchestrator_usage.py` pattern |
| Environment variables | `monkeypatch.setenv` / `monkeypatch.delenv` | Standard pytest |
| Pillow | Real (not mocked) — use small test fixtures | Create 100×200 and 2000×3000 test JPEG fixtures |

### Files likely touched

| Area | Files to modify | Files to create |
|------|-----------------|-----------------|
| AI service | `publisher_v2/src/publisher_v2/services/ai.py` | — |
| Image utils | `publisher_v2/src/publisher_v2/utils/images.py` | — |
| Config models | `publisher_v2/src/publisher_v2/config/schema.py` | — |
| Orchestrator models | `publisher_v2/src/publisher_v2/config/orchestrator_models.py` | — |
| Orchestrator parsing | `publisher_v2/src/publisher_v2/config/source.py` | — |
| Standalone loader | `publisher_v2/src/publisher_v2/config/loader.py` | — |
| Tests | — | `publisher_v2/tests/test_vision_cost_optimization.py`, `publisher_v2/tests/test_analysis_context.py` |
| Test fixtures | — | Small JPEG fixture files in tests dir (optional, can generate in-memory) |

### Implementation sequence

**Phase 1: Config + Resize foundation**
1. Add 5 vision fields to `OpenAIConfig` with validators (AC-17, AC-18)
2. Add fields to `OrchestratorAI`, wire `_build_app_config_v2` mapping (AC-19)
3. Add fields to `_load_openai_settings_from_env` in loader (AC-20)
4. Implement `resize_image_bytes()` in `utils/images.py` (AC-06)

**Phase 2: Vision analyzer rework**
5. Refactor `VisionAnalyzerOpenAI.__init__` to read new config fields
6. Implement resize-and-data-URL path in `analyze()` (AC-01, AC-02, AC-04, AC-05)
7. Implement `vision_max_dimension=0` legacy path (AC-03)
8. Add `detail` parameter to image_url dict in both paths

**Phase 3: Fallback**
9. Extract core analysis into `_analyze_core()` (internal, retried)
10. Implement fallback wrapper in `analyze()` (AC-07, AC-08, AC-09, AC-10, AC-11)
11. Add structured log events (AC-08)

**Phase 4: Richer caption prompts**
12. Implement `build_analysis_context()` helper (AC-12, AC-13, AC-14, AC-15)
13. Replace inline prompt construction in `generate()`, `generate_with_sd()`, `_build_multi_prompt()` (AC-16)

**Phase 5: Backward compat verification**
14. Verify `vision_max_dimension=0, vision_detail="high"` matches pre-PUB-041 behavior (AC-21)

### Key implementation details

#### `resize_image_bytes()` (utils/images.py)

```python
def resize_image_bytes(data: bytes, max_dimension: int, quality: int = 85) -> bytes:
    """Resize image bytes so longest side ≤ max_dimension. Returns JPEG bytes."""
    from io import BytesIO
    from PIL import Image

    img = Image.open(BytesIO(data))
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")

    w, h = img.size
    if max(w, h) > max_dimension:
        scale = max_dimension / max(w, h)
        new_w, new_h = int(w * scale), int(h * scale)
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()
```

#### Data URL construction in `analyze()` (services/ai.py)

```python
import base64
import httpx

async def _download_and_resize(self, url: str) -> str:
    """Download image, resize, return base64 data URL."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, timeout=30.0)
        resp.raise_for_status()

    resized = await asyncio.to_thread(
        resize_image_bytes, resp.content, self._vision_max_dimension
    )
    b64 = base64.b64encode(resized).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"
```

#### `image_url` dict with detail parameter

```python
# In the user_content construction:
ChatCompletionContentPartImageParam(
    type="image_url",
    image_url={"url": image_url, "detail": self._vision_detail},
)
```

#### `build_analysis_context()` (services/ai.py)

```python
def build_analysis_context(analysis: ImageAnalysis, max_field_len: int = 50) -> str:
    """Build a bounded analysis context string for caption prompts."""
    def _trunc(s: str | None) -> str | None:
        if s is None:
            return None
        s = s.strip()
        return s[:max_field_len] if len(s) > max_field_len else s if s else None

    parts = [
        f"description='{_trunc(analysis.description)}'",
        f"mood='{_trunc(analysis.mood)}'",
        f"tags={analysis.tags}",
    ]

    if _trunc(analysis.lighting):
        parts.append(f"lighting='{_trunc(analysis.lighting)}'")
    if _trunc(analysis.composition):
        parts.append(f"composition='{_trunc(analysis.composition)}'")
    if _trunc(analysis.pose):
        parts.append(f"pose='{_trunc(analysis.pose)}'")
    if analysis.aesthetic_terms:
        terms = analysis.aesthetic_terms[:10]
        parts.append(f"aesthetic_terms={terms}")
    if _trunc(analysis.color_palette):
        parts.append(f"color_palette='{_trunc(analysis.color_palette)}'")
    if _trunc(analysis.style):
        parts.append(f"style='{_trunc(analysis.style)}'")

    return ", ".join(parts)
```

#### Fallback structure in `analyze()`

```python
async def analyze(self, url_or_bytes: str | bytes) -> tuple[ImageAnalysis, AIUsage | None]:
    primary_usage: AIUsage | None = None
    try:
        result, primary_usage = await self._analyze_core(
            url_or_bytes, self._vision_max_dimension, self._vision_detail
        )
        return result, primary_usage
    except AIServiceError as primary_err:
        if not self._vision_fallback_enabled:
            raise
        log_json(self.logger, logging.WARNING, "vision_fallback_triggered",
            original_error=str(primary_err))
        fallback_result, fallback_usage = await self._analyze_core(
            url_or_bytes, self._vision_fallback_max_dimension, self._vision_fallback_detail
        )
        # Combine usages
        combined = _combine_usages(primary_usage, fallback_usage)
        return fallback_result, combined
```

### Non-negotiables for this item

- [ ] Preview mode: No special handling needed — resize + low is cost-only, no side-effect change
- [ ] Secrets: No new secrets. Presigned URLs are not logged; base64 image data is not logged.
- [ ] Auth: N/A (no web endpoint changes)
- [ ] Async hygiene: Pillow resize is blocking — must use `asyncio.to_thread()`. httpx download is async natively.
- [ ] Coverage: ≥80% on `services/ai.py`, `utils/images.py`, `config/schema.py`
- [ ] Backward compatibility: `vision_max_dimension=0, vision_detail="high"` must restore pre-PUB-041 behavior

### Claude Code command

```text
/implement docs_v2/roadmap/PUB-041_vision-cost-optimization.md
```
