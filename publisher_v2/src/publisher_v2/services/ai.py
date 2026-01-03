from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Optional

from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from publisher_v2.config.schema import OpenAIConfig
from publisher_v2.config.static_loader import get_static_config
from publisher_v2.core.exceptions import AIServiceError
from publisher_v2.core.models import CaptionSpec, ImageAnalysis
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
    "clothing_or_accessories, aesthetic_terms, pose, composition, background, color_palette\n\n"
    "TYPES & CONSTRAINTS:\n"
    "- description: string (≤ 30 words, neutral fine-art tone, no explicit anatomy/acts)\n"
    "- mood: string\n"
    "- tags: array of 10–25 strings, lowercase_snake_case, ordered by relevance\n"
    "- nsfw: boolean (true if nudity, erotic context, or bondage elements)\n"
    "- safety_labels: array of strings ONLY from:\n"
    "  [\"adult_nudity_non_explicit\",\"bondage_or_restraints\",\"suggestive_context\","
    "\"sexual_activity_none\",\"minors_none\",\"violence_none\",\"self_harm_none\","
    "\"public_display_none\",\"consent_unverified\",\"copyright_uncertain\"]\n"
    "- subject: string (≤ 10 words)\n"
    "- style: string (fine-art and photographic style)\n"
    "- lighting: string (type, quality, direction)\n"
    "- camera: string or null (perspective + focal-length bucket + depth of field if known)\n"
    "- clothing_or_accessories: string or null (include rope/knots if present; avoid explicit body detail)\n"
    "- aesthetic_terms: array of 5–15 fine-art/photography terms\n"
    "- pose: string (orientation/gesture/tension; avoid explicit anatomy)\n"
    "- composition: string (framing, structure, focal emphasis, leading lines/negative space)\n"
    "- background: string (environment/backdrop/texture)\n"
    "- color_palette: array of 3–6 dominant colors (hex preferred; common names if uncertain)\n\n"
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
    "aesthetic_terms (array), pose, composition, background, color_palette (array).\n\n"
    "GUIDELINES:\n"
    "- description: ≤ 30 words, neutral fine-art tone, no explicit anatomy/acts.\n"
    "- tags: 10–25 concise items, lowercase_snake_case, most-salient first (mix art, photo, composition, lighting, rope-art terms).\n"
    "- nsfw: true if nudity, erotic context, or rope bondage.\n"
    "- safety_labels: choose only from:\n"
    "  [\"adult_nudity_non_explicit\",\"bondage_or_restraints\",\"suggestive_context\","
    "\"sexual_activity_none\",\"minors_none\",\"violence_none\",\"self_harm_none\","
    "\"public_display_none\",\"consent_unverified\",\"copyright_uncertain\"]\n"
    "- camera: null if uncertain; otherwise perspective + focal bucket (wide/normal/short-tele/tele) + DoF.\n"
    "- lighting: type + quality + direction (e.g., soft sidelight, high-key studio).\n"
    "- color_palette: 3–6 dominant colors (hex preferred).\n"
    "- Unknown values → null or [].\n\n"
    "Return ONE JSON object ONLY — no extra text."
)


class VisionAnalyzerOpenAI:
    def __init__(self, config: OpenAIConfig):
        self.client = AsyncOpenAI(api_key=config.api_key)
        self.model = config.vision_model  # Use vision-optimized model
        self.logger = logging.getLogger("publisher_v2.ai.vision")
        # Conservative upper bound for structured JSON response; tuned for expanded analysis schema.
        # Kept small enough to avoid unbounded token growth while allowing all fields to be populated.
        self.max_completion_tokens = getattr(config, "vision_max_completion_tokens", 512)

    @staticmethod
    def _opt_str(v: object) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip()
        return s or None

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
    )
    async def analyze(self, url_or_bytes: str | bytes) -> ImageAnalysis:
        """
        Use OpenAI vision model to produce structured analysis.
        Accepts a temporary url or image bytes (url recommended).
        """
        start = time.perf_counter()
        ok = False
        error_type: Optional[str] = None
        try:
            if isinstance(url_or_bytes, bytes):
                # For now we only support URLs; bytes support may be added later via data URLs.
                raise AIServiceError("Byte input not supported in V2 analysis; provide a temporary URL.")

            static_cfg = get_static_config().ai_prompts
            system_prompt = static_cfg.vision.system or _DEFAULT_VISION_SYSTEM_PROMPT
            user_prompt = static_cfg.vision.user or _DEFAULT_VISION_USER_PROMPT

            user_content = [
                {
                    "type": "image_url",
                    "image_url": {"url": url_or_bytes},
                },
                {
                    "type": "text",
                    "text": user_prompt,
                },
            ]
            try:
                resp = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": system_prompt,
                        },
                        {"role": "user", "content": user_content},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.4,
                    max_tokens=self.max_completion_tokens,
                )
            except TypeError:
                # Fall back for older or test double clients that do not accept max_tokens.
                resp = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": system_prompt,
                        },
                        {"role": "user", "content": user_content},
                    ],
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
            )
            ok = True
            return analysis
        except Exception as exc:
            if error_type is None:
                error_type = "openai_error"
            raise AIServiceError(f"OpenAI analysis failed: {exc}") from exc
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            # Emit structured telemetry; avoid logging sensitive payloads.
            log_json(
                self.logger,
                logging.INFO,
                "vision_analysis",
                event="vision_analysis",
                model=self.model,
                vision_analysis_ms=elapsed_ms,
                ok=ok,
                error_type=error_type,
            )


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
        self.sd_caption_enabled = getattr(config, "sd_caption_enabled", True)
        self.sd_caption_single_call_enabled = getattr(config, "sd_caption_single_call_enabled", True)
        self.sd_caption_model = getattr(config, "sd_caption_model", None) or self.model
        cfg_sd_system = getattr(config, "sd_caption_system_prompt", None)
        cfg_sd_role = getattr(config, "sd_caption_role_prompt", None)
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
    async def generate(self, analysis: ImageAnalysis, spec: CaptionSpec) -> str:
        try:
            hashtags_clause = ""
            if getattr(spec, "hashtags", None):
                hashtags_clause = f" End with these hashtags verbatim: {spec.hashtags}."
            prompt = (
                f"{self.role_prompt} "
                f"description='{analysis.description}', mood='{analysis.mood}', tags={analysis.tags}. "
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
            return content
        except Exception as exc:
            raise AIServiceError(f"OpenAI caption failed: {exc}") from exc

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
    )
    async def generate_with_sd(self, analysis: ImageAnalysis, spec: CaptionSpec) -> dict[str, str]:
        """
        Prefer a single-call generation that returns a JSON object:
        { "caption": str, "sd_caption": str }
        """
        try:
            hashtags_clause = ""
            if getattr(spec, "hashtags", None):
                hashtags_clause = f" End with these hashtags verbatim: {spec.hashtags}."
            user_prompt = (
                f"{self.sd_caption_role_prompt} "
                f"Analysis: description='{analysis.description}', mood='{analysis.mood}', tags={analysis.tags}. "
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
            return {"caption": caption, "sd_caption": sd_caption}
        except Exception as exc:
            raise AIServiceError(f"OpenAI caption+sd failed: {exc}") from exc


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

    async def create_caption(self, url_or_bytes: str | bytes, spec: CaptionSpec) -> str:
        async with self._rate_limiter:
            analysis = await self.analyzer.analyze(url_or_bytes)
        async with self._rate_limiter:
            caption = await self.generator.generate(analysis, spec)
        return caption

    async def create_caption_pair(self, url_or_bytes: str | bytes, spec: CaptionSpec) -> tuple[str, Optional[str]]:
        """
        Create (caption, sd_caption). If sd generation is disabled or fails,
        return (caption, None) using legacy caption path.
        """
        async with self._rate_limiter:
            analysis = await self.analyzer.analyze(url_or_bytes)
        return await self.create_caption_pair_from_analysis(analysis, spec)

    async def create_caption_pair_from_analysis(
        self, analysis: ImageAnalysis, spec: CaptionSpec
    ) -> tuple[str, Optional[str]]:
        """
        Create (caption, sd_caption) when an ImageAnalysis is already available.

        If SD caption generation is disabled or the single-call path fails,
        falls back to the legacy caption-only path and returns (caption, None).
        """
        # Attempt single-call generation if enabled
        if getattr(self.generator, "sd_caption_enabled", True) and getattr(
            self.generator, "sd_caption_single_call_enabled", True
        ):
            try:
                async with self._rate_limiter:
                    pair = await self.generator.generate_with_sd(analysis, spec)
                return pair.get("caption", ""), pair.get("sd_caption") or None
            except Exception:
                # Fallback to legacy below
                pass
        # Legacy fallback
        async with self._rate_limiter:
            caption_only = await self.generator.generate(analysis, spec)
        return caption_only, None


class NullAIService:
    """
    Safe stub used when AI is disabled for a tenant.

    WorkflowOrchestrator guards all AI usage behind config.features.analyze_caption_enabled,
    so this should never be invoked when that flag is False.
    """

    analyzer = None
    generator = None


