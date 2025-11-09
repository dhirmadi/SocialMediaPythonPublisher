from __future__ import annotations

import asyncio
import json
from typing import Optional

from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from publisher_v2.config.schema import OpenAIConfig
from publisher_v2.core.exceptions import AIServiceError
from publisher_v2.core.models import CaptionSpec, ImageAnalysis
from publisher_v2.utils.rate_limit import AsyncRateLimiter


class VisionAnalyzerOpenAI:
    def __init__(self, config: OpenAIConfig):
        self.client = AsyncOpenAI(api_key=config.api_key)
        self.model = config.vision_model  # Use vision-optimized model

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
        try:
            if isinstance(url_or_bytes, bytes):
                # For now we only support URLs; bytes support may be added later via data URLs.
                raise AIServiceError("Byte input not supported in V2 analysis; provide a temporary URL.")

            user_content = [
                {
                    "type": "image_url",
                    "image_url": {"url": url_or_bytes},
                },
                {
                    "type": "text",
                    "text": (
                        "Analyze this image and return strict JSON with keys:\n"
                        "description, mood, tags (array), nsfw (boolean), safety_labels (array),\n"
                        "subject, style, lighting, camera, clothing_or_accessories,\n"
                        "aesthetic_terms (array), pose, composition, background, color_palette.\n"
                        "Description ≤ 30 words. If unknown, use null or empty array. No extra text."
                    ),
                },
            ]
            resp = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an expert vision curator for social media and AI art datasets. "
                            "Produce a detailed but structured breakdown suitable for downstream captioning and SD prompts. "
                            "Return strict JSON only; no prose."
                        ),
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
                # Fallback: attempt a best-effort mapping; keep safe defaults
                data = {
                    "description": str(content).strip()[:100],
                    "mood": "unknown",
                    "tags": [],
                    "nsfw": False,
                    "safety_labels": [],
                }
            return ImageAnalysis(
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
        except Exception as exc:
            raise AIServiceError(f"OpenAI analysis failed: {exc}") from exc


class CaptionGeneratorOpenAI:
    def __init__(self, config: OpenAIConfig):
        self.client = AsyncOpenAI(api_key=config.api_key)
        self.model = config.caption_model  # Use cost-effective caption model
        self.system_prompt = config.system_prompt
        self.role_prompt = config.role_prompt
        # SD caption settings
        self.sd_caption_enabled = getattr(config, "sd_caption_enabled", True)
        self.sd_caption_single_call_enabled = getattr(config, "sd_caption_single_call_enabled", True)
        self.sd_caption_model = getattr(config, "sd_caption_model", None) or self.model
        self.sd_caption_system_prompt = getattr(config, "sd_caption_system_prompt", None) or self.system_prompt
        self.sd_caption_role_prompt = getattr(config, "sd_caption_role_prompt", None) or (
            "Write two outputs for the provided analysis and platform spec: "
            "1) 'caption' for social media, respecting max_length and hashtags if provided; "
            "2) 'sd_caption' optimized for Stable Diffusion prompts (PG-13 fine-art phrasing; include pose, styling/material, lighting, mood). "
            "Respond strictly as JSON with keys caption, sd_caption."
        )

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
        self._rate_limiter = AsyncRateLimiter(rate_per_minute=20)

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
        # Attempt single-call generation if enabled
        if getattr(self.generator, "sd_caption_enabled", True) and getattr(self.generator, "sd_caption_single_call_enabled", True):
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


