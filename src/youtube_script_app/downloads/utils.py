"""Helpers for download command construction and progress formatting."""

from __future__ import annotations

import re
from pathlib import Path
from typing import List

from ..core import subtitle_renderer

SIZE_TOKEN_RE = re.compile(
    r"^\s*~?(\d+(?:[.,]\d+)?)\s*([KMGTPE]?i?B)\s*$",
    re.IGNORECASE,
)


def parse_size_to_bytes(size: str) -> int | None:
    token = (size or "").strip()
    if not token:
        return None
    match = SIZE_TOKEN_RE.match(token)
    if not match:
        return None
    value_text, unit = match.groups()
    try:
        value = float(value_text.replace(",", "."))
    except ValueError:
        return None

    unit = unit.upper()
    factors = {
        "B": 1,
        "KB": 1000,
        "MB": 1000**2,
        "GB": 1000**3,
        "TB": 1000**4,
        "KIB": 1024,
        "MIB": 1024**2,
        "GIB": 1024**3,
        "TIB": 1024**4,
        "PIB": 1024**5,
    }
    factor = factors.get(unit)
    if factor is None:
        return None
    return int(value * factor)


def format_bytes(value: int) -> str:
    amount = max(0.0, float(value))
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    idx = 0
    while amount >= 1024.0 and idx < len(units) - 1:
        amount /= 1024.0
        idx += 1
    if idx == 0:
        return f"{int(amount)} {units[idx]}"
    return f"{amount:.1f} {units[idx]}"


def format_download_size_progress(percent: float, total_size: str) -> str:
    total_bytes = parse_size_to_bytes(total_size)
    if total_bytes is None:
        return total_size
    clamped = max(0.0, min(100.0, float(percent)))
    downloaded = int(total_bytes * (clamped / 100.0))
    return f"{format_bytes(downloaded)} / {format_bytes(total_bytes)}"


def build_media_download_command(item: dict) -> List[str]:
    kind = str(item.get("kind", "full_video")).strip().lower()
    output_dir = str(item.get("output_dir", ""))
    url = str(item.get("url", "")).strip()
    yt_dlp_cmd = item.get("yt_dlp_cmd")
    cmd_prefix = list(yt_dlp_cmd) if isinstance(yt_dlp_cmd, (list, tuple)) else []
    if kind == "audio":
        return [
            *cmd_prefix,
            "--no-playlist",
            "--extract-audio",
            "--audio-format",
            "mp3",
            "--audio-quality",
            "0",
            "--paths",
            output_dir,
            "-o",
            "%(title).120s_audio.%(ext)s",
            url,
        ]

    video_format = str(item.get("format", "mp4")).strip().lower() or "mp4"
    return [
        *cmd_prefix,
        "--no-playlist",
        "-S",
        f"ext:{video_format}",
        "--merge-output-format",
        video_format,
        "--paths",
        output_dir,
        "-o",
        "%(title).120s_full.%(ext)s",
        url,
    ]


def download_variant_suffix(
    to_shorts: bool,
    has_logo: bool,
    has_subtitles: bool = False,
    video_effect: str = "none",
    subtitle_style: str = "impact",
) -> str:
    normalized_effect = subtitle_renderer.normalize_video_effect(video_effect)
    if not has_subtitles and normalized_effect == "none":
        if to_shorts and has_logo:
            return "_shorts_logo"
        if to_shorts:
            return "_shorts_9x16"
        if has_logo:
            return "_logo"
        return ""

    parts: List[str] = []
    if to_shorts and has_logo:
        parts.extend(["shorts", "logo"])
    elif to_shorts:
        parts.append("shorts_9x16")
    if has_logo and not to_shorts:
        parts.append("logo")
    if has_subtitles:
        parts.append(f"subs-{subtitle_renderer.subtitle_style_suffix(subtitle_style)}")
    effect_suffix = subtitle_renderer.video_effect_suffix(normalized_effect)
    if effect_suffix:
        parts.append(effect_suffix)
    return f"_{'_'.join(parts)}" if parts else ""


def download_variant_output_path(
    input_path: Path,
    to_shorts: bool,
    has_logo: bool,
    has_subtitles: bool = False,
    video_effect: str = "none",
    subtitle_style: str = "impact",
) -> Path:
    suffix = download_variant_suffix(
        to_shorts,
        has_logo,
        has_subtitles=has_subtitles,
        video_effect=video_effect,
        subtitle_style=subtitle_style,
    )
    extension = ".mp4" if suffix else input_path.suffix
    return input_path.with_name(f"{input_path.stem}{suffix}{extension}")


def logo_overlay_y_expr(position: str, margin: int = 36) -> str:
    if position == "top":
        return str(margin)
    if position == "bottom":
        return f"H-h-{margin}"
    return "(H-h)/2"


def logo_opacity_ratio(percent: int) -> float:
    try:
        value = int(percent)
    except (TypeError, ValueError):
        value = 100
    value = max(10, min(100, value))
    return value / 100.0
