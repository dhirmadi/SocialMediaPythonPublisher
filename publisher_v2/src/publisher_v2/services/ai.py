from __future__ import annotations

import asyncio
import json
from typing import Optional

from openai import AsyncOpenAI

from publisher_v2.config.schema import OpenAIConfig
from publisher_v2.core.exceptions import AIServiceError
from publisher_v2.core.models import CaptionSpec, ImageAnalysis


class VisionAnalyzerOpenAI:
    def __init__(self, config: OpenAIConfig):
        self.client = AsyncOpenAI(api_key=config.api_key)
        self.model = config.model

    async def analyze(self, url_or_bytes: str | bytes) -> ImageAnalysis:
        """
        Use OpenAI vision model to produce structured analysis.
        Accepts a temporary url or image bytes (url recommended).
        """
        try:
            if isinstance(url_or_bytes, bytes):
                raise AIServiceError("Byte input not supported in V2 analysis; use temporary URL.")

            user_content = [
                {"type": "input_text", "text": "Analyze this image and return strict JSON with keys: description, mood, tags (array), nsfw (boolean), safety_labels (array). Description ≤ 30 words."},
                {"type": "input_image", "image_url": url_or_bytes},
            ]
            resp = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert vision curator for social media. Extract concise description, mood, tags, and safety flags suitable for downstream captioning. Output strict JSON only.",
                    },
                    {"role": "user", "content": user_content},
                ],
                temperature=0.4,
            )
            content = resp.choices[0].message.content or "{}"
            data = json.loads(content)
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
        self.model = config.model
        self.system_prompt = config.system_prompt
        self.role_prompt = config.role_prompt

    async def generate(self, analysis: ImageAnalysis, spec: CaptionSpec) -> str:
        try:
            prompt = (
                f"{self.role_prompt} "
                f"description='{analysis.description}', mood='{analysis.mood}', tags={analysis.tags}. "
                f"Platform={spec.platform}, style={spec.style}. "
                f"One caption, 1–2 short sentences, authentic, no quotes, end with these hashtags verbatim: {spec.hashtags}."
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

    async def create_caption(self, url_or_bytes: str | bytes, spec: CaptionSpec) -> str:
        analysis = await self.analyzer.analyze(url_or_bytes)
        caption = await self.generator.generate(analysis, spec)
        return caption


