from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from typing import TYPE_CHECKING, Any, Literal, cast

import httpx
from openai import AsyncOpenAI

if TYPE_CHECKING:
    from publisher_v2.services.storage_protocol import StorageProtocol
from openai.types.chat import (
    ChatCompletionContentPartImageParam,
    ChatCompletionContentPartTextParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
)
from tenacity import retry, stop_after_attempt, wait_exponential

from publisher_v2.config.schema import OpenAIConfig
from publisher_v2.config.static_loader import get_static_config
from publisher_v2.core.exceptions import AIServiceError
from publisher_v2.core.models import AIUsage, CaptionSpec, ImageAnalysis
from publisher_v2.utils.images import resize_image_bytes
from publisher_v2.utils.logging import log_json
from publisher_v2.utils.rate_limit import AsyncRateLimiter

_DEFAULT_VISION_SYSTEM_PROMPT = (
    "You are a fine-art photographic analyst. You recognize classical figure study and rope-art traditions "
    "as artistic forms. Produce tasteful, neutral, technically detailed metadata suitable for high-end fine-art "
    "training datasets.\n\n"
    "OUTPUT RULES:\n"
    "- Return ONE JSON object only — no prose, no markdown, no code fences.\n"
    "- Use EXACTLY these keys (lowercase):\n"
    "  description, mood, tags, nsfw, safety_labels, subject, style, lighting, camera, "
    "clothing_or_accessories, aesthetic_terms, pose, composition, background, color_palette, alt_text\n\n"
    "TYPES & CONSTRAINTS:\n"
    "- description: string (≤ 30 words, neutral fine-art tone, no explicit anatomy/acts)\n"
    "- mood: string\n"
    "- tags: array of 10–25 strings, lowercase_snake_case, ordered by relevance\n"
    "- nsfw: boolean (true if nudity, erotic context, or bondage elements)\n"
    "- safety_labels: array of strings ONLY from:\n"
    '  ["adult_nudity_non_explicit","bondage_or_restraints","suggestive_context",'
    '"sexual_activity_none","minors_none","violence_none","self_harm_none",'
    '"public_display_none","consent_unverified","copyright_uncertain"]\n'
    "- subject: string (≤ 10 words)\n"
    "- style: string (fine-art and photographic style)\n"
    "- lighting: string (type, quality, direction)\n"
    "- camera: string or null (perspective + focal-length bucket + depth of field if known)\n"
    "- clothing_or_accessories: string or null (include rope/knots if present; avoid explicit body detail)\n"
    "- aesthetic_terms: array of 5–15 fine-art/photography terms\n"
    "- pose: string (orientation/gesture/tension; avoid explicit anatomy)\n"
    "- composition: string (framing, structure, focal emphasis, leading lines/negative space)\n"
    "- background: string (environment/backdrop/texture)\n"
    "- color_palette: array of 3–6 dominant colors (hex preferred; common names if uncertain)\n"
    "- alt_text: string (≤125 characters, plain descriptive sentence for screen readers; describe what is visually "
    "depicted, not mood or interpretation; no hashtags or promotional language)\n\n"
    "ADDITIONAL RULES:\n"
    "- Treat shibari as traditional rope art; use respectful fine-art vocabulary (e.g., kinbaku patterning, rope harness, geometric bindings).\n"
    "- Avoid explicit terminology or slang; no sexual description.\n"
    "- Do not guess identities, locations, or brands.\n"
    "- If unknown, return null or [].\n"
)


_DEFAULT_VISION_USER_PROMPT = (
    "Analyze this image and return strict JSON with keys:\n"
    "description, mood, tags (array), nsfw (boolean), safety_labels (array),\n"
    "subject, style, lighting, camera, clothing_or_accessories,\n"
    "aesthetic_terms (array), pose, composition, background, color_palette (array), alt_text.\n\n"
    "GUIDELINES:\n"
    "- description: ≤ 30 words, neutral fine-art tone, no explicit anatomy/acts.\n"
    "- tags: 10–25 concise items, lowercase_snake_case, most-salient first (mix art, photo, composition, lighting, rope-art terms).\n"
    "- nsfw: true if nudity, erotic context, or rope bondage.\n"
    "- safety_labels: choose only from:\n"
    '  ["adult_nudity_non_explicit","bondage_or_restraints","suggestive_context",'
    '"sexual_activity_none","minors_none","violence_none","self_harm_none",'
    '"public_display_none","consent_unverified","copyright_uncertain"]\n'
    "- camera: null if uncertain; otherwise perspective + focal bucket (wide/normal/short-tele/tele) + DoF.\n"
    "- lighting: type + quality + direction (e.g., soft sidelight, high-key studio).\n"
    "- color_palette: 3–6 dominant colors (hex preferred).\n"
    "- alt_text: ≤125 characters, plain descriptive sentence for screen readers; describe what is visually depicted "
    "(no hashtags, no promotional language, no mood/interpretation).\n"
    "- Unknown values → null or [].\n\n"
    "Return ONE JSON object ONLY — no extra text."
)


def _extract_usage(resp: object) -> AIUsage | None:
    """Extract AIUsage from an OpenAI response object. Returns None if usage is absent."""
    usage = getattr(resp, "usage", None)
    if usage is None:
        return None
    return AIUsage(
        response_id=getattr(resp, "id", None) or "",
        total_tokens=getattr(usage, "total_tokens", 0) or 0,
        prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
    )


def _combine_usages(a: AIUsage | None, b: AIUsage | None) -> AIUsage | None:
    """Combine two AIUsage records (e.g., primary + fallback). Returns None if both None."""
    if a is None and b is None:
        return None
    if a is None:
        return b
    if b is None:
        return a
    return AIUsage(
        response_id=b.response_id or a.response_id,
        total_tokens=a.total_tokens + b.total_tokens,
        prompt_tokens=a.prompt_tokens + b.prompt_tokens,
        completion_tokens=a.completion_tokens + b.completion_tokens,
    )


class VisionAnalyzerOpenAI:
    def __init__(self, config: OpenAIConfig):
        self.client = AsyncOpenAI(api_key=config.api_key)
        self.model = config.vision_model  # Use vision-optimized model
        self.logger = logging.getLogger("publisher_v2.ai.vision")
        # Conservative upper bound for structured JSON response; tuned for expanded analysis schema.
        # Kept small enough to avoid unbounded token growth while allowing all fields to be populated.
        self.max_completion_tokens = getattr(config, "vision_max_completion_tokens", 512)
        # PUB-041 vision cost optimization
        self._vision_max_dimension = config.vision_max_dimension
        self._vision_detail = config.vision_detail
        self._vision_fallback_enabled = config.vision_fallback_enabled
        self._vision_fallback_max_dimension = config.vision_fallback_max_dimension
        self._vision_fallback_detail = config.vision_fallback_detail

    @staticmethod
    def _opt_str(v: object) -> str | None:
        if v is None:
            return None
        s = str(v).strip()
        return s or None

    async def _download_and_resize(self, url: str, max_dimension: int) -> str:
        """Download image at url and return a base64 JPEG data URL resized to max_dimension."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=30.0)
            resp.raise_for_status()
        resized = await asyncio.to_thread(resize_image_bytes, resp.content, max_dimension)
        b64 = base64.b64encode(resized).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"

    async def _prepare_image_url(self, url: str, max_dimension: int) -> tuple[str, bool]:
        """Return the image_url string to send to OpenAI plus whether it was resized.

        Done once per analyze chain (NOT inside the OpenAI retry loop) so that
        transient OpenAI errors do not cause repeat downloads.
        """
        if max_dimension > 0:
            return await self._download_and_resize(url, max_dimension), True
        return url, False

    async def analyze(self, url_or_bytes: str | bytes) -> tuple[ImageAnalysis, AIUsage | None]:
        """Analyze an image, with optional quality-escalation fallback (PUB-041).

        Behavior:
        - Primary attempt uses ``vision_max_dimension`` and ``vision_detail`` from config.
        - On AIServiceError after retries, if ``vision_fallback_enabled`` is True, a
          single additional attempt is made with the fallback dimensions/detail.
        - Returns combined ``AIUsage`` (primary + fallback) when fallback fires.
        - Each chain (primary, fallback) downloads/resizes the source image at most once;
          OpenAI-side retries reuse the prepared data URL.
        """
        if isinstance(url_or_bytes, bytes):
            raise AIServiceError("Byte input not supported in V2 analysis; provide a temporary URL.")
        url = url_or_bytes

        primary_usage: AIUsage | None = None
        try:
            primary_image_url, primary_resized = await self._prepare_image_url(url, self._vision_max_dimension)
            result, primary_usage = await self._analyze_core(
                primary_image_url, self._vision_max_dimension, self._vision_detail, primary_resized
            )
            return result, primary_usage
        except AIServiceError as primary_err:
            if not self._vision_fallback_enabled:
                raise
            log_json(
                self.logger,
                logging.WARNING,
                "vision_fallback_triggered",
                event="vision_fallback_triggered",
                original_error=str(primary_err),
                fallback_max_dimension=self._vision_fallback_max_dimension,
                fallback_detail=self._vision_fallback_detail,
            )
            try:
                fb_image_url, fb_resized = await self._prepare_image_url(url, self._vision_fallback_max_dimension)
                fallback_result, fallback_usage = await self._analyze_core(
                    fb_image_url,
                    self._vision_fallback_max_dimension,
                    self._vision_fallback_detail,
                    fb_resized,
                )
            except AIServiceError:
                log_json(
                    self.logger,
                    logging.INFO,
                    "vision_fallback_result",
                    event="vision_fallback_result",
                    ok=False,
                    vision_tokens=0,
                )
                raise
            combined = _combine_usages(primary_usage, fallback_usage)
            log_json(
                self.logger,
                logging.INFO,
                "vision_fallback_result",
                event="vision_fallback_result",
                ok=True,
                vision_tokens=(fallback_usage.total_tokens if fallback_usage else 0),
            )
            return fallback_result, combined

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
    )
    async def _analyze_core(
        self, image_url: str, max_dimension: int, detail: str, resized: bool
    ) -> tuple[ImageAnalysis, AIUsage | None]:
        """Single OpenAI vision attempt (with internal retries on transient errors).

        ``image_url`` is already prepared (either a presigned URL or a data URL);
        retries reuse the same prepared payload.
        """
        start = time.perf_counter()
        ok = False
        error_type: str | None = None
        try:
            static_cfg = get_static_config().ai_prompts
            system_prompt = static_cfg.vision.system or _DEFAULT_VISION_SYSTEM_PROMPT
            user_prompt = static_cfg.vision.user or _DEFAULT_VISION_USER_PROMPT

            # OpenAI's TypedDict expects detail as Literal["auto","low","high"]; the config
            # validator already enforces that exact set.
            image_url_payload: dict[str, str] = {
                "url": image_url,
                "detail": cast(Literal["auto", "low", "high"], detail),
            }
            user_content: list[ChatCompletionContentPartImageParam | ChatCompletionContentPartTextParam] = [
                ChatCompletionContentPartImageParam(
                    type="image_url",
                    image_url=cast(Any, image_url_payload),
                ),
                ChatCompletionContentPartTextParam(
                    type="text",
                    text=user_prompt,
                ),
            ]
            messages: list[ChatCompletionSystemMessageParam | ChatCompletionUserMessageParam] = [
                ChatCompletionSystemMessageParam(role="system", content=system_prompt),
                ChatCompletionUserMessageParam(role="user", content=user_content),
            ]
            try:
                resp = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    response_format={"type": "json_object"},
                    temperature=0.4,
                    max_tokens=self.max_completion_tokens,
                )
            except TypeError:
                # Fall back for older or test double clients that do not accept max_tokens.
                resp = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    response_format={"type": "json_object"},
                    temperature=0.4,
                )
            content = resp.choices[0].message.content or "{}"
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                error_type = "json_decode_error"
                # Fallback: attempt a best-effort mapping; keep safe defaults
                data = {
                    "description": str(content).strip()[:100],
                    "mood": "unknown",
                    "tags": [],
                    "nsfw": False,
                    "safety_labels": [],
                    "alt_text": None,
                }
            analysis = ImageAnalysis(
                description=str(data.get("description", "")).strip(),
                mood=str(data.get("mood", "")).strip(),
                tags=[str(t) for t in (data.get("tags") or [])],
                nsfw=bool(data.get("nsfw", False)),
                safety_labels=[str(s) for s in (data.get("safety_labels") or [])],
                subject=self._opt_str(data.get("subject")),
                style=self._opt_str(data.get("style")),
                lighting=self._opt_str(data.get("lighting")),
                camera=self._opt_str(data.get("camera")),
                clothing_or_accessories=self._opt_str(data.get("clothing_or_accessories")),
                aesthetic_terms=[str(t) for t in (data.get("aesthetic_terms") or [])],
                pose=self._opt_str(data.get("pose")),
                composition=self._opt_str(data.get("composition")),
                background=self._opt_str(data.get("background")),
                color_palette=self._opt_str(data.get("color_palette")),
                alt_text=self._opt_str(data.get("alt_text")),
            )
            ai_usage = _extract_usage(resp)
            ok = True
            return analysis, ai_usage
        except AIServiceError:
            if error_type is None:
                error_type = "openai_error"
            raise
        except Exception as exc:
            if error_type is None:
                error_type = "openai_error"
            raise AIServiceError(f"OpenAI analysis failed: {exc}") from exc
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            # Emit structured telemetry; avoid logging sensitive payloads (no URLs/data).
            log_json(
                self.logger,
                logging.INFO,
                "vision_analysis",
                event="vision_analysis",
                model=self.model,
                vision_analysis_ms=elapsed_ms,
                ok=ok,
                error_type=error_type,
                detail=detail,
                max_dimension=max_dimension,
                resized=resized,
            )


# ---------------------------------------------------------------------------
# PUB-035: Prompt builder helpers for context intelligence
# ---------------------------------------------------------------------------

logger = logging.getLogger("publisher_v2.services.ai")


def build_analysis_context(analysis: ImageAnalysis, max_field_len: int = 50) -> str:
    """Build a bounded analysis-context string for caption prompts (PUB-041).

    Includes ``description``, ``mood``, ``tags`` always; appends
    ``lighting``, ``composition``, ``pose``, ``aesthetic_terms`` (capped at 10),
    ``color_palette``, ``style`` when non-None/non-empty. Excludes sensitive or
    low-value fields (``nsfw``, ``safety_labels``, ``camera``, ``clothing_or_accessories``,
    ``background``, ``subject``).
    """

    def _trunc(s: str | None) -> str | None:
        if s is None:
            return None
        s2 = s.strip()
        if not s2:
            return None
        return s2[:max_field_len]

    parts: list[str] = [
        f"description='{_trunc(analysis.description) or ''}'",
        f"mood='{_trunc(analysis.mood) or ''}'",
        f"tags={analysis.tags}",
    ]

    lighting = _trunc(analysis.lighting)
    if lighting:
        parts.append(f"lighting='{lighting}'")

    composition = _trunc(analysis.composition)
    if composition:
        parts.append(f"composition='{composition}'")

    pose = _trunc(analysis.pose)
    if pose:
        parts.append(f"pose='{pose}'")

    if analysis.aesthetic_terms:
        terms = list(analysis.aesthetic_terms[:10])
        parts.append(f"aesthetic_terms={terms}")

    color_palette = _trunc(analysis.color_palette)
    if color_palette:
        parts.append(f"color_palette='{color_palette}'")

    style = _trunc(analysis.style)
    if style:
        parts.append(f"style='{style}'")

    return ", ".join(parts)


def build_platform_block(index: int, name: str, spec: CaptionSpec) -> str:
    """Build the prompt block for a single platform, including examples and guidance."""
    ht = f"Include hashtags: {spec.hashtags}." if spec.hashtags else "No hashtags."
    lines = [f"{index}. {name}: {spec.style}, up to {spec.max_length} chars. {ht}"]

    if spec.examples:
        lines.append("   Voice examples (match this tone, DO NOT copy):")
        for ex in spec.examples:
            lines.append(f'     - "{ex}"')

    if spec.guidance:
        lines.append(f"   Guidance: {spec.guidance}")

    return "\n".join(lines)


def build_history_block(captions: list[str]) -> str:
    """Build the history context block with anti-repetition instructions."""
    if not captions:
        return ""
    lines = ["Your recent captions for this account (DO NOT repeat phrasing, vary structure and openings):"]
    for i, cap in enumerate(captions, 1):
        lines.append(f'{i}. "{cap}"')
    lines.append("")
    lines.append("Now write a NEW caption that maintains voice consistency but uses DIFFERENT:")
    lines.append("- Opening patterns")
    lines.append("- Sentence structures")
    lines.append("- Word choices")
    lines.append("- Emotional angles")
    return "\n".join(lines)


def truncate_history_to_budget(captions: list[str], max_tokens_budget: int) -> list[str]:
    """Truncate captions list (oldest first) to fit within token budget.

    Uses a rough estimate of 1 token per 4 characters.
    """
    if not captions:
        return []
    result = list(captions)
    while result and sum(len(c) // 4 + 1 for c in result) > max_tokens_budget:
        result.pop(0)  # drop oldest first
    return result


_SIDECAR_MAX_SIZE = 64 * 1024  # 64 KB — skip suspiciously large sidecars


def _extract_caption_from_sidecar(data: bytes) -> str:
    """Extract the published caption from a sidecar file.

    Handles both JSON sidecars (``{"caption": "..."}`) and the standard text
    format (``sd_caption\\n\\n# ---\\n# key: val``).  For text sidecars the
    published caption is stored in the metadata line ``# caption: ...``;
    if absent we skip it (the first line is the SD prompt, not a social caption).
    """
    if len(data) > _SIDECAR_MAX_SIZE:
        return ""
    text = data.decode("utf-8", errors="replace").strip()
    if not text:
        return ""

    # Try JSON sidecar format first (future / PUB-035 format)
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return str(parsed.get("caption") or parsed.get("caption_generated") or "").strip()
    except (json.JSONDecodeError, ValueError):
        pass

    # Standard text sidecar: parse metadata lines for a 'caption' key
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("# caption:"):
            return stripped[len("# caption:") :].strip()
        if stripped.startswith("# caption_generated:"):
            return stripped[len("# caption_generated:") :].strip()

    return ""


async def fetch_caption_history(
    storage: StorageProtocol | Any,
    folder: str,
    window_size: int = 8,
    max_tokens_budget: int = 1000,
) -> list[str]:
    """Fetch recent captions from storage sidecars.

    Returns a list of caption strings (most recent last), or empty list on any error.
    Prefers 'caption' (published/edited) over 'caption_generated' (AI original).
    Downloads sidecars in parallel for performance.
    """
    if window_size <= 0:
        return []

    try:
        images = await storage.list_images(folder)
    except Exception:
        log_json(logger, logging.WARNING, "caption_history_list_failed", folder=folder)
        return []

    # Take the most recent N images
    recent = images[-window_size:] if len(images) > window_size else images
    if not recent:
        return []

    # Download sidecars in parallel (H2)
    async def _safe_download(img: str) -> tuple[str, bytes | None]:
        try:
            return img, await storage.download_sidecar_if_exists(folder, img)
        except Exception:
            return img, None

    results = await asyncio.gather(*[_safe_download(img) for img in recent])

    captions: list[str] = []
    for _img, data in results:
        if data is None:
            continue
        cap = _extract_caption_from_sidecar(data)
        if cap:
            captions.append(cap)

    return truncate_history_to_budget(captions, max_tokens_budget)


class CaptionGeneratorOpenAI:
    def __init__(self, config: OpenAIConfig):
        self.client = AsyncOpenAI(api_key=config.api_key)
        self.model = config.caption_model  # Use cost-effective caption model
        default_cfg = OpenAIConfig()
        tenant_custom_system = config.system_prompt != default_cfg.system_prompt
        tenant_custom_role = config.role_prompt != default_cfg.role_prompt

        # Start with config-provided prompts (or schema defaults if orchestrator omitted them).
        self.system_prompt = config.system_prompt
        self.role_prompt = config.role_prompt
        # SD caption settings
        self.sd_caption_enabled = config.sd_caption_enabled
        self.sd_caption_single_call_enabled = config.sd_caption_single_call_enabled
        self.sd_caption_model = config.sd_caption_model or self.model
        cfg_sd_system = config.sd_caption_system_prompt
        cfg_sd_role = config.sd_caption_role_prompt
        self.sd_caption_system_prompt = cfg_sd_system or self.system_prompt
        self.sd_caption_role_prompt = cfg_sd_role or (
            "Write two outputs for the provided analysis and platform spec: "
            "1) 'caption' for social media, respecting max_length and hashtags if provided; "
            "2) 'sd_caption' optimized for Stable Diffusion prompts (PG-13 fine-art phrasing; include pose, styling/material, lighting, mood). "
            "Respond strictly as JSON with keys caption, sd_caption."
        )

        # Static prompt overrides (non-secret, optional). These are defaults for the app,
        # but must NOT override tenant-specific prompts delivered by the orchestrator.
        static_prompts = get_static_config().ai_prompts

        # Caption prompts: prefer tenant config when it differs from schema defaults; otherwise use static YAML as fallback.
        if not tenant_custom_system and static_prompts.caption.system:
            self.system_prompt = static_prompts.caption.system
        if not tenant_custom_role and static_prompts.caption.role:
            self.role_prompt = static_prompts.caption.role

        # SD caption prompts:
        # - If tenant explicitly provided sd prompts, use them.
        # - If tenant provided custom caption prompts but no sd prompts, inherit the tenant caption prompts.
        # - Otherwise, use static YAML sd prompts as fallback.
        if cfg_sd_system:
            self.sd_caption_system_prompt = cfg_sd_system
        elif tenant_custom_system:
            self.sd_caption_system_prompt = self.system_prompt
        elif static_prompts.sd_caption.system:
            self.sd_caption_system_prompt = static_prompts.sd_caption.system
        else:
            # Keep current (which may reference self.system_prompt).
            self.sd_caption_system_prompt = self.sd_caption_system_prompt or self.system_prompt

        if cfg_sd_role:
            self.sd_caption_role_prompt = cfg_sd_role
        elif tenant_custom_role:
            # Preserve the required JSON/output-shape instruction by appending the SD role template.
            sd_role_template = static_prompts.sd_caption.role or self.sd_caption_role_prompt
            if sd_role_template and self.role_prompt and self.role_prompt not in sd_role_template:
                self.sd_caption_role_prompt = f"{self.role_prompt}\n\n{sd_role_template}"
            else:
                self.sd_caption_role_prompt = self.role_prompt or sd_role_template
        elif static_prompts.sd_caption.role:
            self.sd_caption_role_prompt = static_prompts.sd_caption.role
        else:
            # Keep current default.
            self.sd_caption_role_prompt = self.sd_caption_role_prompt

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
    )
    async def generate(self, analysis: ImageAnalysis, spec: CaptionSpec) -> tuple[str, AIUsage | None]:
        try:
            hashtags_clause = ""
            if spec.hashtags:
                hashtags_clause = f" End with these hashtags verbatim: {spec.hashtags}."
            prompt = (
                f"{self.role_prompt} "
                f"{build_analysis_context(analysis)}. "
                f"Platform={spec.platform}, style={spec.style}."
                f"{hashtags_clause}"
                f" Respect max_length={spec.max_length}."
            )
            resp = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
            )
            content = (resp.choices[0].message.content or "").strip()
            if not content:
                raise AIServiceError("Empty caption generated")
            # Enforce length
            if len(content) > spec.max_length:
                content = content[: spec.max_length - 1].rstrip() + "…"
            return content, _extract_usage(resp)
        except Exception as exc:
            raise AIServiceError(f"OpenAI caption failed: {exc}") from exc

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
    )
    async def generate_with_sd(
        self, analysis: ImageAnalysis, spec: CaptionSpec
    ) -> tuple[dict[str, str], AIUsage | None]:
        """
        Prefer a single-call generation that returns a JSON object:
        { "caption": str, "sd_caption": str }
        """
        try:
            hashtags_clause = ""
            if spec.hashtags:
                hashtags_clause = f" End with these hashtags verbatim: {spec.hashtags}."
            user_prompt = (
                f"{self.sd_caption_role_prompt} "
                f"Analysis: {build_analysis_context(analysis)}. "
                f"Platform={spec.platform}, style={spec.style}. "
                f"{hashtags_clause} Respect max_length={spec.max_length} for 'caption'. "
                f"For 'sd_caption', produce PG-13 fine-art phrasing including pose, styling/material, lighting, mood. "
                f"Return strict JSON with keys caption, sd_caption."
            )
            resp = await self.client.chat.completions.create(
                model=self.sd_caption_model,
                messages=[
                    {"role": "system", "content": self.sd_caption_system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.6,
            )
            content = (resp.choices[0].message.content or "{}").strip()
            data = json.loads(content)
            caption = str(data.get("caption", "")).strip()
            sd_caption = str(data.get("sd_caption", "")).strip()
            if not caption:
                raise AIServiceError("Empty caption in single-call response")
            # Enforce length for normal caption
            if len(caption) > spec.max_length:
                caption = caption[: spec.max_length - 1].rstrip() + "…"
            return {"caption": caption, "sd_caption": sd_caption}, _extract_usage(resp)
        except Exception as exc:
            raise AIServiceError(f"OpenAI caption+sd failed: {exc}") from exc

    @staticmethod
    def _build_multi_prompt(
        role_prompt: str,
        analysis: ImageAnalysis,
        specs: dict[str, CaptionSpec],
        history: list[str] | None,
        sd_suffix: str = "",
    ) -> tuple[str, str]:
        """Build the prompt and keys_list for multi-platform generation (DRY)."""
        platform_blocks = [build_platform_block(i, name, spec) for i, (name, spec) in enumerate(specs.items(), 1)]
        platforms_block = "\n".join(platform_blocks)
        keys_list = ", ".join(f'"{k}"' for k in specs)
        history_block = build_history_block(history or [])

        prompt = (
            f"{role_prompt}\n\n"
            f"Generate captions for these platforms:\n\n"
            f"{platforms_block}\n\n"
            + (f"{history_block}\n\n" if history_block else "")
            + f"Image analysis: {build_analysis_context(analysis)}\n\n"
            + sd_suffix
            + f"Respond with strict JSON containing exactly these keys: {keys_list}"
            + (', "sd_caption"' if sd_suffix else "")
        )
        return prompt, keys_list

    @staticmethod
    def _parse_platform_captions(data: dict, specs: dict[str, CaptionSpec]) -> dict[str, str]:
        """Parse and enforce max_length on per-platform captions from LLM response."""
        captions: dict[str, str] = {}
        for platform in specs:
            val = data.get(platform)
            if val is None:
                raise AIServiceError(f"Missing platform '{platform}' in LLM response")
            caption_text = str(val).strip()
            if len(caption_text) > specs[platform].max_length:
                caption_text = caption_text[: specs[platform].max_length - 1].rstrip() + "…"
            captions[platform] = caption_text
        return captions

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
    )
    async def generate_multi(
        self,
        analysis: ImageAnalysis,
        specs: dict[str, CaptionSpec],
        history: list[str] | None = None,
    ) -> tuple[dict[str, str], AIUsage | None]:
        """Generate one caption per platform in a single OpenAI call."""
        try:
            prompt, _ = self._build_multi_prompt(self.role_prompt, analysis, specs, history)
            resp = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.7,
            )
            data = json.loads((resp.choices[0].message.content or "{}").strip())
            return self._parse_platform_captions(data, specs), _extract_usage(resp)
        except Exception as exc:
            raise AIServiceError(f"OpenAI multi-caption failed: {exc}") from exc

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
    )
    async def generate_multi_with_sd(
        self,
        analysis: ImageAnalysis,
        specs: dict[str, CaptionSpec],
        history: list[str] | None = None,
    ) -> tuple[dict[str, str], AIUsage | None]:
        """Generate per-platform captions plus one sd_caption in a single OpenAI call."""
        try:
            sd_suffix = (
                "Also produce 'sd_caption' optimized for Stable Diffusion prompts "
                "(PG-13 fine-art phrasing; include pose, styling/material, lighting, mood).\n\n"
            )
            prompt, _ = self._build_multi_prompt(self.sd_caption_role_prompt, analysis, specs, history, sd_suffix)
            resp = await self.client.chat.completions.create(
                model=self.sd_caption_model,
                messages=[
                    {"role": "system", "content": self.sd_caption_system_prompt},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.6,
            )
            data = json.loads((resp.choices[0].message.content or "{}").strip())
            result = self._parse_platform_captions(data, specs)
            result["sd_caption"] = str(data.get("sd_caption", "")).strip()
            return result, _extract_usage(resp)
        except Exception as exc:
            raise AIServiceError(f"OpenAI multi-caption+sd failed: {exc}") from exc


class AIService:
    def __init__(self, analyzer: VisionAnalyzerOpenAI, generator: CaptionGeneratorOpenAI):
        self.analyzer = analyzer
        self.generator = generator
        limits = get_static_config().service_limits.ai
        rate = limits.rate_per_minute
        env_rate = os.environ.get("AI_RATE_PER_MINUTE")
        if env_rate:
            try:
                parsed = int(env_rate)
                if parsed > 0:
                    rate = parsed
            except ValueError:
                # Ignore invalid override; keep config/default rate.
                pass
        self._rate_limiter = AsyncRateLimiter(rate_per_minute=rate)

    async def create_caption_from_analysis(
        self, analysis: ImageAnalysis, spec: CaptionSpec
    ) -> tuple[str, list[AIUsage]]:
        """Create a single caption from an existing ImageAnalysis and return usage records.

        This is useful for fallback paths that already performed vision analysis and
        want metering parity with the primary caption-generation flows.
        """
        usages: list[AIUsage] = []
        async with self._rate_limiter:
            caption, usage = await self.generator.generate(analysis, spec)
        if usage is not None:
            usages.append(usage)
        return caption, usages

    async def create_caption(self, url_or_bytes: str | bytes, spec: CaptionSpec) -> str:
        async with self._rate_limiter:
            analysis, _usage = await self.analyzer.analyze(url_or_bytes)
        async with self._rate_limiter:
            caption, _usage2 = await self.generator.generate(analysis, spec)
        return caption

    async def create_caption_pair(self, url_or_bytes: str | bytes, spec: CaptionSpec) -> tuple[str, str | None]:
        """
        Create (caption, sd_caption). If sd generation is disabled or fails,
        return (caption, None) using legacy caption path.
        """
        async with self._rate_limiter:
            analysis, _usage = await self.analyzer.analyze(url_or_bytes)
        caption, sd, _usages = await self.create_caption_pair_from_analysis(analysis, spec)
        return caption, sd

    async def create_caption_pair_from_analysis(
        self, analysis: ImageAnalysis, spec: CaptionSpec
    ) -> tuple[str, str | None, list[AIUsage]]:
        """
        Create (caption, sd_caption, usages) when an ImageAnalysis is already available.

        If SD caption generation is disabled or the single-call path fails,
        falls back to the legacy caption-only path and returns (caption, None, usages).
        """
        usages: list[AIUsage] = []
        # Attempt single-call generation if enabled
        if getattr(self.generator, "sd_caption_enabled", True) and getattr(
            self.generator, "sd_caption_single_call_enabled", True
        ):
            try:
                async with self._rate_limiter:
                    pair, usage = await self.generator.generate_with_sd(analysis, spec)
                if usage is not None:
                    usages.append(usage)
                return pair.get("caption", ""), pair.get("sd_caption") or None, usages
            except Exception:  # noqa: S110 — intentional fallback to legacy caption-only path below
                pass
        # Legacy fallback
        async with self._rate_limiter:
            caption_only, usage = await self.generator.generate(analysis, spec)
        if usage is not None:
            usages.append(usage)
        return caption_only, None, usages

    async def create_multi_caption_pair_from_analysis(
        self,
        analysis: ImageAnalysis,
        specs: dict[str, CaptionSpec],
        history: list[str] | None = None,
    ) -> tuple[dict[str, str], str | None, list[AIUsage]]:
        """Create per-platform captions and optional sd_caption from an existing analysis.

        Returns (platform_captions_dict, sd_caption_or_none, usages).
        Falls back to generate_multi if SD generation fails or is disabled.
        If the generator doesn't support multi-caption, falls back to single-caption path.
        """
        # Fallback for generators that don't support multi-caption (backward compat)
        if not hasattr(self.generator, "generate_multi"):
            spec = next(iter(specs.values()))
            caption, sd, fallback_usages = await self.create_caption_pair_from_analysis(analysis, spec)
            return {next(iter(specs)): caption}, sd, fallback_usages

        usages: list[AIUsage] = []
        if getattr(self.generator, "sd_caption_enabled", True) and getattr(
            self.generator, "sd_caption_single_call_enabled", True
        ):
            try:
                async with self._rate_limiter:
                    result, usage = await self.generator.generate_multi_with_sd(analysis, specs, history=history)
                if usage is not None:
                    usages.append(usage)
                sd_caption = result.pop("sd_caption", None) or None
                return result, sd_caption, usages
            except Exception:  # noqa: S110 — intentional fallback
                pass
        # Fallback to multi-caption without SD
        async with self._rate_limiter:
            captions, usage = await self.generator.generate_multi(analysis, specs, history=history)
        if usage is not None:
            usages.append(usage)
        return captions, None, usages


class NullAIService:
    """
    Safe stub used when AI is disabled for a tenant.

    WorkflowOrchestrator guards all AI usage behind config.features.analyze_caption_enabled,
    so this should never be invoked when that flag is False.
    """

    analyzer = None
    generator = None
