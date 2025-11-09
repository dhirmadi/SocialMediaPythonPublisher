"""
Preview mode utilities for human-readable output.
Displays what will be published without taking any actions.
"""
from __future__ import annotations

from typing import List, Dict
from publisher_v2.core.models import ImageAnalysis, CaptionSpec
from publisher_v2.services.publishers.base import Publisher
from publisher_v2.utils.captions import build_caption_sidecar


def print_preview_header() -> None:
    """Print beautiful header for preview mode"""
    print("\n" + "═" * 70)
    print("  PUBLISHER V2 - PREVIEW MODE")
    print("═" * 70)


def print_image_details(
    filename: str,
    folder: str,
    sha256: str,
    dropbox_url: str,
    is_new: bool,
    already_posted: bool = False,
) -> None:
    """Print image selection details"""
    print("\n📸 IMAGE SELECTED")
    print("─" * 70)
    print(f"  File:        {filename}")
    print(f"  Folder:      {folder}")
    print(f"  SHA256:      {sha256[:16]}... (truncated)")
    print(f"  Dropbox URL: {dropbox_url}")
    
    if already_posted:
        print(f"  Status:      ⚠️  Previously posted (would be skipped in real run)")
    elif is_new:
        print(f"  Status:      ✓ New (not previously posted)")
    else:
        print(f"  Status:      Unknown")


def print_vision_analysis(analysis: ImageAnalysis, model: str) -> None:
    """Print vision analysis results"""
    print(f"\n🔍 AI VISION ANALYSIS ({model})")
    print("─" * 70)
    
    # Description with word wrapping
    desc_lines = _wrap_text(analysis.description, 60)
    print(f"  Description: {desc_lines[0]}")
    for line in desc_lines[1:]:
        print(f"               {line}")
    
    print(f"\n  Mood:        {analysis.mood}")
    
    # Tags with wrapping
    tags_str = ", ".join(analysis.tags)
    tag_lines = _wrap_text(tags_str, 60)
    print(f"\n  Tags:        {tag_lines[0]}")
    for line in tag_lines[1:]:
        print(f"               {line}")
    
    print(f"\n  NSFW:        {analysis.nsfw}")
    
    if analysis.safety_labels:
        print(f"  Safety:      {', '.join(analysis.safety_labels)}")
    else:
        print(f"  Safety:      None")
    
    # Optional detailed fields
    subject = getattr(analysis, "subject", None)
    if subject:
        print(f"\n  Subject:     {subject}")
    style = getattr(analysis, "style", None)
    if style:
        print(f"  Style:       {style}")
    lighting = getattr(analysis, "lighting", None)
    if lighting:
        print(f"  Lighting:    {lighting}")
    camera = getattr(analysis, "camera", None)
    if camera:
        print(f"  Camera:      {camera}")
    clothing = getattr(analysis, "clothing_or_accessories", None)
    if clothing:
        print(f"  Clothing:    {clothing}")
    aesthetics = getattr(analysis, "aesthetic_terms", None)
    if aesthetics:
        aesthetics_str = ", ".join(aesthetics)
        print(f"  Aesthetics:  {aesthetics_str}")
    pose = getattr(analysis, "pose", None)
    if pose:
        print(f"  Pose:        {pose}")
    composition = getattr(analysis, "composition", None)
    if composition:
        print(f"  Composition: {composition}")
    background = getattr(analysis, "background", None)
    if background:
        print(f"  Background:  {background}")
    palette = getattr(analysis, "color_palette", None)
    if palette:
        print(f"  Palette:     {palette}")
    
    # Optional SD caption preview
    sd_text = getattr(analysis, "sd_caption", None)
    if sd_text:
        sd_lines = _wrap_text(sd_text, 60)
        print(f"\n  SD Caption:  {sd_lines[0]}")
        for line in sd_lines[1:]:
            print(f"               {line}")


def print_caption(caption: str, spec: CaptionSpec, model: str, hashtag_count: int) -> None:
    """Print generated caption"""
    print(f"\n✍️  AI CAPTION GENERATION ({model})")
    print("─" * 70)
    print(f"  Platform:    {spec.platform}")
    print(f"  Style:       {spec.style}")
    print(f"  Max Length:  {spec.max_length} chars")
    
    print(f"\n  Caption:")
    # Indent and wrap caption text
    caption_lines = _wrap_text(caption, 60)
    for line in caption_lines:
        print(f"  \"{line}\"")
    
    print(f"\n  Length:      {len(caption)} characters")
    print(f"  Hashtags:    {hashtag_count}")


def print_platform_preview(
    publishers: List[Publisher],
    caption: str,
    platform_captions: Dict[str, str],
    email_subject: str | None = None,
    email_caption_target: str | None = None,
    email_subject_mode: str | None = None,
) -> None:
    """Print which platforms will receive what"""
    print(f"\n📤 PUBLISHING PREVIEW")
    print("─" * 70)
    
    enabled_count = 0
    disabled_count = 0
    
    for pub in publishers:
        if pub.is_enabled():
            enabled_count += 1
            platform_caption = platform_captions.get(pub.platform_name, caption)
            
            # Show platform-specific details
            print(f"  ✓ {pub.platform_name.capitalize():12} (ENABLED)")
            
            if pub.platform_name == "telegram":
                print(f"     → Image will be resized to max 1280px width")
            elif pub.platform_name == "instagram":
                print(f"     → Image will be resized to max 1080px width")
                # Count hashtags
                hashtag_count = platform_caption.count('#')
                if hashtag_count > 30:
                    print(f"     ⚠️  Hashtags will be limited to 30 (currently {hashtag_count})")
            elif pub.platform_name == "email":
                subj_preview = (email_subject or platform_caption)[:60]
                if email_caption_target:
                    print(f"     → Caption target: {email_caption_target}")
                if email_subject_mode and email_subject_mode != "normal":
                    print(f"     → Subject mode: {email_subject_mode}")
                print(f"     → Subject: \"{subj_preview}...\"")
                print(f"     → FetLife formatting: no hashtags, ≤240 chars")
            
            # Show caption preview
            preview_length = 60
            if len(platform_caption) > preview_length:
                caption_preview = platform_caption[:preview_length] + "..."
            else:
                caption_preview = platform_caption
            print(f"     Caption: \"{caption_preview}\"")
            print()
        else:
            disabled_count += 1
            print(f"  ✗ {pub.platform_name.capitalize():12} (DISABLED)")
    
    print(f"\n  Summary: {enabled_count} enabled, {disabled_count} disabled")


def print_email_confirmation_preview(
    enabled: bool,
    to_sender: bool,
    tags_count: int,
    tags_sample: List[str] | None,
    nature: str,
) -> None:
    """Show what confirmation email settings will do"""
    if not enabled:
        return
    print(f"\n✉️  EMAIL CONFIRMATION")
    print("─" * 70)
    print(f"  To sender:   {'ON' if to_sender else 'OFF'}")
    if to_sender:
        print(f"  Tags count:  {tags_count}")
        print(f"  Tags nature: {nature}")
        if tags_sample:
            print(f"  Sample tags: {', '.join(tags_sample[:tags_count])}")


def print_config_summary(
    vision_model: str,
    caption_model: str,
    config_file: str,
) -> None:
    """Print configuration summary"""
    print(f"\n⚙️  CONFIGURATION")
    print("─" * 70)
    print(f"  Config File:    {config_file}")
    print(f"  Vision Model:   {vision_model}")
    print(f"  Caption Model:  {caption_model}")


def print_preview_footer() -> None:
    """Print warning that this is preview only"""
    print(f"\n⚠️  PREVIEW MODE - NO ACTIONS TAKEN")
    print("─" * 70)
    print("  • No content published to any platform")
    print("  • No images moved or archived on Dropbox")
    print("  • No state/cache updates")
    print("\n  To publish for real, run without --preview flag.")
    print("═" * 70)
    print()


def print_error(message: str) -> None:
    """Print error message in preview mode"""
    print(f"\n❌ ERROR")
    print("─" * 70)
    print(f"  {message}")
    print("═" * 70)
    print()


def print_caption_sidecar_preview(sd_caption: str, metadata: Dict[str, object]) -> None:
    """Print the full caption sidecar content (caption + metadata block)."""
    print(f"\n📄 CAPTION SIDECAR")
    print("─" * 70)
    content = build_caption_sidecar(sd_caption, metadata)
    for line in content.rstrip("\n").split("\n"):
        print(f"  {line}")


def _wrap_text(text: str, max_width: int) -> List[str]:
    """Wrap text to specified width, breaking on spaces"""
    if len(text) <= max_width:
        return [text]
    
    lines = []
    current_line = ""
    
    words = text.split()
    for word in words:
        if not current_line:
            current_line = word
        elif len(current_line) + 1 + len(word) <= max_width:
            current_line += " " + word
        else:
            lines.append(current_line)
            current_line = word
    
    if current_line:
        lines.append(current_line)
    
    return lines


def _count_hashtags(text: str) -> int:
    """Count hashtags in text"""
    return text.count('#')

