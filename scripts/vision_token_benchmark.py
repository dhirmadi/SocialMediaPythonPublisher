#!/usr/bin/env python3
"""Benchmark OpenAI vision cost vs downstream caption+SD quality (publisher-equivalent).

Vision (per image, three variants — same prompts/model params as VisionAnalyzerOpenAI):
  A) Long side 1024px JPEG + detail=low
  B) Long side 1024px JPEG + detail=high
  C) Full-resolution JPEG + detail=high

Downstream (same as CaptionGeneratorOpenAI.generate_with_sd when SD single-call is enabled):
  Builds ImageAnalysis from vision JSON (same field mapping as VisionAnalyzerOpenAI),
  then one caption+sd_caption call using static ai_prompts.yaml caption/SD prompts.

Requires OPENAI_API_KEY. Optional: OPENAI_VISION_MODEL (default gpt-4o),
OPENAI_CAPTION_MODEL (default gpt-4o-mini).

Usage (from repo root):
  PYTHONPATH=publisher_v2/src uv run python scripts/vision_token_benchmark.py \\
    --images-dir docs_v2/07_AI/Testfiles --out /tmp/vision_benchmark.json
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import logging
import os
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import AsyncOpenAI
from openai.types.chat import (
    ChatCompletionContentPartImageParam,
    ChatCompletionContentPartTextParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
)
from PIL import Image

from publisher_v2.config.schema import OpenAIConfig
from publisher_v2.config.static_loader import get_static_config
from publisher_v2.core.models import CaptionSpec, ImageAnalysis
from publisher_v2.services.ai import CaptionGeneratorOpenAI

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("vision_benchmark")

JPEG_QUALITY_FULL = 95
JPEG_QUALITY_RESIZED = 90
MAX_COMPLETION_TOKENS = 512


def _usage_dict(usage: object | None) -> dict[str, Any]:
    if usage is None:
        return {}
    md = getattr(usage, "model_dump", None)
    if callable(md):
        return md()
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }


def _image_to_data_url(jpeg_bytes: bytes) -> str:
    b64 = base64.standard_b64encode(jpeg_bytes).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def _prepare_jpeg(path: Path, long_side_max: int | None) -> tuple[bytes, tuple[int, int]]:
    with Image.open(path) as im:
        im = im.convert("RGB")
        w, h = im.size
        if long_side_max is not None:
            longest = max(w, h)
            if longest > long_side_max:
                scale = long_side_max / longest
                nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
                im = im.resize((nw, nh), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        q = JPEG_QUALITY_RESIZED if long_side_max else JPEG_QUALITY_FULL
        im.save(buf, format="JPEG", quality=q, optimize=True)
        out = buf.getvalue()
        return out, im.size


def _tag_set(tags: list[str]) -> set[str]:
    return {t.strip().lower() for t in tags if t.strip()}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _word_set(text: str) -> set[str]:
    return {w.lower() for w in re.findall(r"[a-zA-Z0-9']+", text) if len(w) > 1}


def _opt_str(v: object) -> str | None:
    """Match VisionAnalyzerOpenAI._opt_str."""
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def vision_json_to_image_analysis(data: dict[str, Any]) -> ImageAnalysis:
    """Same field mapping as VisionAnalyzerOpenAI (ai.py)."""
    return ImageAnalysis(
        description=str(data.get("description", "")).strip(),
        mood=str(data.get("mood", "")).strip(),
        tags=[str(t) for t in (data.get("tags") or [])],
        nsfw=bool(data.get("nsfw", False)),
        safety_labels=[str(s) for s in (data.get("safety_labels") or [])],
        subject=_opt_str(data.get("subject")),
        style=_opt_str(data.get("style")),
        lighting=_opt_str(data.get("lighting")),
        camera=_opt_str(data.get("camera")),
        clothing_or_accessories=_opt_str(data.get("clothing_or_accessories")),
        aesthetic_terms=[str(t) for t in (data.get("aesthetic_terms") or [])],
        pose=_opt_str(data.get("pose")),
        composition=_opt_str(data.get("composition")),
        background=_opt_str(data.get("background")),
        color_palette=_opt_str(data.get("color_palette")),
    )


def _vision_degenerate(data: dict[str, Any]) -> bool:
    tags = data.get("tags") or []
    desc = str(data.get("description", "")).strip()
    return len(tags) == 0 and len(desc) < 5


def _caption_spec_for_platform(platform: str, hashtag_placeholder: str) -> CaptionSpec:
    registry = get_static_config().ai_prompts.platform_captions
    style_cfg = registry.get(platform) or registry.get("generic")
    if style_cfg is None:
        return CaptionSpec(
            platform="generic",
            style="minimal_poetic",
            hashtags=hashtag_placeholder,
            max_length=2200,
        )
    return CaptionSpec(
        platform=platform,
        style=style_cfg.style,
        hashtags=hashtag_placeholder if style_cfg.hashtags else "",
        max_length=style_cfg.max_length,
        examples=tuple(style_cfg.examples),
        guidance=style_cfg.guidance,
    )


async def _call_openai(
    client: AsyncOpenAI,
    model: str,
    system_prompt: str,
    user_prompt: str,
    data_url: str,
    detail: str,
) -> tuple[dict[str, Any], dict[str, Any], float]:
    user_content: list[ChatCompletionContentPartImageParam | ChatCompletionContentPartTextParam] = [
        ChatCompletionContentPartImageParam(
            type="image_url",
            image_url={"url": data_url, "detail": detail},
        ),
        ChatCompletionContentPartTextParam(type="text", text=user_prompt),
    ]
    messages: list[ChatCompletionSystemMessageParam | ChatCompletionUserMessageParam] = [
        ChatCompletionSystemMessageParam(role="system", content=system_prompt),
        ChatCompletionUserMessageParam(role="user", content=user_content),
    ]
    t0 = time.perf_counter()
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.4,
            max_tokens=MAX_COMPLETION_TOKENS,
        )
    except TypeError:
        resp = await client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.4,
        )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    content = resp.choices[0].message.content or "{}"
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        data = {"description": content[:200], "tags": [], "mood": ""}
    usage = _usage_dict(getattr(resp, "usage", None))
    return data, usage, elapsed_ms


async def _run_downstream(
    generator: CaptionGeneratorOpenAI,
    analysis: ImageAnalysis,
    spec: CaptionSpec,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    pair, ai_usage = await generator.generate_with_sd(analysis, spec)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    if ai_usage is not None:
        usage_d = {
            "prompt_tokens": ai_usage.prompt_tokens,
            "completion_tokens": ai_usage.completion_tokens,
            "total_tokens": ai_usage.total_tokens,
        }
    else:
        usage_d = {}
    return {
        "caption": pair.get("caption", ""),
        "sd_caption": pair.get("sd_caption", ""),
        "elapsed_ms": elapsed_ms,
        "prompt_tokens": int(usage_d.get("prompt_tokens") or 0),
        "completion_tokens": int(usage_d.get("completion_tokens") or 0),
        "total_tokens": int(usage_d.get("total_tokens") or 0),
        "usage_raw": usage_d,
    }


async def benchmark_image(
    client: AsyncOpenAI,
    vision_model: str,
    system_prompt: str,
    user_prompt: str,
    image_path: Path,
    generator: CaptionGeneratorOpenAI,
    caption_spec: CaptionSpec,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    jpeg_1024, dim_1024 = _prepare_jpeg(image_path, 1024)
    url_1024 = _image_to_data_url(jpeg_1024)
    jpeg_full, dim_full = _prepare_jpeg(image_path, None)
    url_full = _image_to_data_url(jpeg_full)

    triple: list[tuple[str, str, tuple[int, int], int, str, dict[str, Any], dict[str, Any], float]] = []
    data_a, usage_a, ms_a = await _call_openai(client, vision_model, system_prompt, user_prompt, url_1024, "low")
    triple.append(("1024_detail_low", "low", dim_1024, len(jpeg_1024), url_1024, data_a, usage_a, ms_a))
    await asyncio.sleep(0.35)

    data_b, usage_b, ms_b = await _call_openai(client, vision_model, system_prompt, user_prompt, url_1024, "high")
    triple.append(("1024_detail_high", "high", dim_1024, len(jpeg_1024), url_1024, data_b, usage_b, ms_b))
    await asyncio.sleep(0.35)

    data_c, usage_c, ms_c = await _call_openai(client, vision_model, system_prompt, user_prompt, url_full, "high")
    triple.append(("original_detail_high", "high", dim_full, len(jpeg_full), url_full, data_c, usage_c, ms_c))

    ref_tags = _tag_set([str(t) for t in (data_c.get("tags") or [])])

    for variant_id, detail, dim, jpeg_len, _url, data, usage, ms in triple:
        tags = [str(t) for t in (data.get("tags") or [])]
        degenerate = _vision_degenerate(data)
        row: dict[str, Any] = {
            "variant": variant_id,
            "pixel_w": dim[0],
            "pixel_h": dim[1],
            "jpeg_bytes": jpeg_len,
            "detail": detail,
            "vision_elapsed_ms": ms,
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
            "vision_usage_raw": usage,
            "description": str(data.get("description", ""))[:500],
            "tag_count": len(tags),
            "tags": tags[:40],
            "tag_jaccard_vs_original": _jaccard(_tag_set(tags), ref_tags),
            "vision_json": data,
            "vision_degenerate": degenerate,
            "downstream": None,
            "caption_word_jaccard_vs_original": None,
            "sd_caption_word_jaccard_vs_original": None,
        }

        if not degenerate:
            analysis = vision_json_to_image_analysis(data)
            try:
                row["downstream"] = await _run_downstream(generator, analysis, caption_spec)
            except Exception as exc:
                row["downstream"] = {"error": str(exc)}
            await asyncio.sleep(0.35)
        else:
            row["downstream"] = {"error": "vision_degenerate_skip"}

        rows.append(row)

    # Second pass: caption word overlap vs original (same image)
    ref_caption_words: set[str] | None = None
    ref_sd_words: set[str] | None = None
    orig = next(r for r in rows if r["variant"] == "original_detail_high")
    ds_o = orig.get("downstream")
    if isinstance(ds_o, dict) and "caption" in ds_o and not ds_o.get("error"):
        ref_caption_words = _word_set(ds_o["caption"])
        ref_sd_words = _word_set(ds_o.get("sd_caption") or "")

    if ref_caption_words is not None:
        for r in rows:
            ds = r.get("downstream")
            if not isinstance(ds, dict) or "caption" not in ds or ds.get("error"):
                continue
            cap_w = _word_set(ds["caption"])
            sd_w = _word_set(ds.get("sd_caption") or "")
            r["caption_word_jaccard_vs_original"] = _jaccard(cap_w, ref_caption_words)
            r["sd_caption_word_jaccard_vs_original"] = _jaccard(sd_w, ref_sd_words or set())

    return rows


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_variant: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_variant.setdefault(r["variant"], []).append(r)

    summary: dict[str, Any] = {}
    for variant, items in by_variant.items():
        pts = [x["prompt_tokens"] for x in items]
        vcts = [x["completion_tokens"] for x in items]
        tts = [x["total_tokens"] for x in items]
        jj = [x["tag_jaccard_vs_original"] for x in items]
        degenerate = sum(1 for x in items if x["vision_degenerate"])
        ds_ok = sum(
            1
            for x in items
            if isinstance(x.get("downstream"), dict)
            and "caption" in x["downstream"]
            and not x["downstream"].get("error")
        )
        cap_j = [
            x["caption_word_jaccard_vs_original"] for x in items if x["caption_word_jaccard_vs_original"] is not None
        ]
        sd_j = [
            x["sd_caption_word_jaccard_vs_original"]
            for x in items
            if x["sd_caption_word_jaccard_vs_original"] is not None
        ]
        combined: list[int] = []
        for x in items:
            vt = x["total_tokens"]
            d = x.get("downstream")
            if isinstance(d, dict) and "total_tokens" in d:
                combined.append(vt + int(d["total_tokens"]))
            else:
                combined.append(vt)
        ds_tokens = [
            int(x["downstream"]["total_tokens"])
            for x in items
            if isinstance(x.get("downstream"), dict) and "total_tokens" in x["downstream"]
        ]

        summary[variant] = {
            "n": len(items),
            "vision_degenerate_runs": degenerate,
            "downstream_success_runs": ds_ok,
            "prompt_tokens_mean": round(statistics.mean(pts), 1),
            "prompt_tokens_stdev": round(statistics.pstdev(pts), 1) if len(pts) > 1 else 0.0,
            "vision_completion_tokens_mean": round(statistics.mean(vcts), 1),
            "vision_total_tokens_mean": round(statistics.mean(tts), 1),
            "tag_jaccard_vs_original_mean": round(statistics.mean(jj), 3),
            "tag_count_mean": round(statistics.mean([x["tag_count"] for x in items]), 1),
            "caption_word_jaccard_vs_original_mean": round(statistics.mean(cap_j), 3) if cap_j else None,
            "sd_caption_word_jaccard_vs_original_mean": round(statistics.mean(sd_j), 3) if sd_j else None,
            "downstream_total_tokens_mean": round(statistics.mean(ds_tokens), 1) if ds_tokens else None,
            "vision_plus_downstream_total_tokens_mean": round(statistics.mean(combined), 1) if combined else None,
        }
    return summary


async def _async_main(
    image_paths: list[Path],
    vision_model: str,
    caption_model: str,
    caption_platform: str,
    hashtag_placeholder: str,
) -> dict[str, Any] | None:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.error("OPENAI_API_KEY is not set (export it or add to .env).")
        return None

    static_cfg = get_static_config().ai_prompts
    system_prompt = static_cfg.vision.system or ""
    user_prompt = static_cfg.vision.user or ""
    if not system_prompt.strip() or not user_prompt.strip():
        logger.error("Vision prompts missing from static config.")
        return None

    if not image_paths:
        logger.error("No image paths provided.")
        return None

    oa_cfg = OpenAIConfig(api_key=api_key, vision_model=vision_model, caption_model=caption_model)
    client = AsyncOpenAI(api_key=api_key)
    generator = CaptionGeneratorOpenAI(oa_cfg)
    caption_spec = _caption_spec_for_platform(caption_platform, hashtag_placeholder)

    all_rows: list[dict[str, Any]] = []

    for i, path in enumerate(image_paths):
        logger.info("[%s/%s] %s", i + 1, len(image_paths), path.name)
        try:
            results = await benchmark_image(
                client, vision_model, system_prompt, user_prompt, path, generator, caption_spec
            )
        except Exception:
            logger.exception("Failed on %s", path)
            return None
        for r in results:
            r["image"] = path.name
            # Drop huge data URL from any accidental serial — not stored
            all_rows.append(r)
        await asyncio.sleep(0.5)

    return {
        "vision_model": vision_model,
        "caption_model": caption_model,
        "caption_platform": caption_platform,
        "max_completion_tokens": MAX_COMPLETION_TOKENS,
        "summary": _summarize(all_rows),
        "runs": all_rows,
    }


def _collect_images(images_dir: Path) -> list[Path]:
    return sorted(
        p for p in images_dir.iterdir() if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    )


def main() -> int:
    p = argparse.ArgumentParser(description="Vision + downstream caption/SD benchmark (publisher-equivalent).")
    p.add_argument(
        "--images-dir",
        type=Path,
        default=Path("docs_v2/07_AI/Testfiles"),
        help="Directory of test images",
    )
    p.add_argument("--out", type=Path, default=None, help="Write JSON results to this path")
    p.add_argument(
        "--vision-model",
        default=os.environ.get("OPENAI_VISION_MODEL", "gpt-4o"),
        help="Vision model (default: gpt-4o)",
    )
    p.add_argument(
        "--caption-model",
        default=os.environ.get("OPENAI_CAPTION_MODEL", "gpt-4o-mini"),
        help="Caption model (default: gpt-4o-mini)",
    )
    p.add_argument(
        "--caption-platform",
        default="instagram",
        help="platform_captions registry key for CaptionSpec (default: instagram)",
    )
    p.add_argument(
        "--hashtag-placeholder",
        default="#fineart #photography",
        help="Hashtag string passed into CaptionSpec for benchmark prompts",
    )
    args = p.parse_args()
    if not args.images_dir.is_dir():
        logger.error("Not a directory: %s", args.images_dir)
        return 1
    image_paths = _collect_images(args.images_dir)
    if not image_paths:
        logger.error("No images found in %s", args.images_dir)
        return 1

    payload = asyncio.run(
        _async_main(
            image_paths,
            args.vision_model,
            args.caption_model,
            args.caption_platform,
            args.hashtag_placeholder,
        )
    )
    if payload is None:
        return 1
    payload["images_dir"] = str(args.images_dir.resolve())

    text = json.dumps(payload, indent=2)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        logger.info("Wrote %s", args.out)
    else:
        print(text)

    s = payload["summary"]
    logger.info("--- summary ---")
    for k in ("1024_detail_low", "1024_detail_high", "original_detail_high"):
        if k not in s:
            continue
        sk = s[k]
        logger.info(
            "%s: vision_total≈%s, downstream_ok=%s/%s, vision_degen=%s, "
            "cap_jaccard_vs_orig≈%s, sd_jaccard≈%s, end_to_end_tokens≈%s",
            k,
            sk.get("vision_total_tokens_mean"),
            sk.get("downstream_success_runs"),
            sk.get("n"),
            sk.get("vision_degenerate_runs"),
            sk.get("caption_word_jaccard_vs_original_mean"),
            sk.get("sd_caption_word_jaccard_vs_original_mean"),
            sk.get("vision_plus_downstream_total_tokens_mean"),
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
