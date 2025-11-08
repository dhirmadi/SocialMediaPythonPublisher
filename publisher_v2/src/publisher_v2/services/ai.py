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
                        "Analyze this image and return strict JSON with keys: "
                        "description, mood, tags (array), nsfw (boolean), safety_labels (array). "
                        "Description ≤ 30 words."
                    ),
                },
            ]
            resp = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an expert vision curator for social media. Extract concise description, mood, "
                            "tags, and safety flags suitable for downstream captioning. Output strict JSON only."
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
            )
        except Exception as exc:
            raise AIServiceError(f"OpenAI analysis failed: {exc}") from exc


class CaptionGeneratorOpenAI:
    def __init__(self, config: OpenAIConfig):
        self.client = AsyncOpenAI(api_key=config.api_key)
        self.model = config.caption_model  # Use cost-effective caption model
        self.system_prompt = config.system_prompt
        self.role_prompt = config.role_prompt

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


