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

DEFAULT_LOGO_POSITION = "top-right"
DEFAULT_LOGO_WIDTH_RATIO = 0.12
DEFAULT_LOGO_X_RATIO = 0.95
DEFAULT_LOGO_Y_RATIO = 0.05
DEFAULT_LOGO_SCALE_PERCENT = 30
MIN_LOGO_WIDTH_RATIO = 0.05
MAX_LOGO_WIDTH_RATIO = 0.30
PORTRAIT_LOGO_MIN_WIDTH_RATIO = 0.24
PORTRAIT_LOGO_MAX_WIDTH_RATIO = 0.44
PORTRAIT_LOGO_WIDTH_MULTIPLIER = 1.8
LOGO_EDGE_MARGIN_RATIO = 0.05
LOGO_ESTIMATED_HEIGHT_RATIO = 0.08
LOGO_POSITIONS = {
    "top-left",
    "top",
    "top-right",
    "center-left",
    "center",
    "center-right",
    "bottom-left",
    "bottom",
    "bottom-right",
}
LOGO_POSITION_LABELS = {
    "top-left": "en haut à gauche",
    "top": "en haut au centre",
    "top-right": "en haut à droite",
    "center-left": "au centre à gauche",
    "center": "au centre",
    "center-right": "au centre à droite",
    "bottom-left": "en bas à gauche",
    "bottom": "en bas au centre",
    "bottom-right": "en bas à droite",
}
PRESET_LOGO_RATIOS = {
    "top-left": (0.05, 0.05),
    "top": (0.50, 0.05),
    "top-right": (0.95, 0.05),
    "center-left": (0.05, 0.46),
    "center": (0.50, 0.46),
    "center-right": (0.95, 0.46),
    "bottom-left": (0.05, 0.87),
    "bottom": (0.50, 0.87),
    "bottom-right": (0.95, 0.87),
}
BEST_VIDEO_FORMAT_SELECTOR = "bestvideo*+bestaudio/best"
BEST_VIDEO_SORT_ORDER = "res,fps,br"
COMMON_VIDEO_EXTENSIONS = {".mp4", ".webm", ".mkv", ".mov", ".m4v"}


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


def build_best_video_download_args(video_format: str) -> List[str]:
    normalized_format = str(video_format or "mp4").strip().lower() or "mp4"
    return [
        "-f",
        BEST_VIDEO_FORMAT_SELECTOR,
        "-S",
        BEST_VIDEO_SORT_ORDER,
        "--merge-output-format",
        normalized_format,
    ]


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
        *build_best_video_download_args(video_format),
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
    has_lower_third: bool = False,
    has_intro_outro: bool = False,
    has_progress_bar: bool = False,
    has_watermark: bool = False,
    video_effect: str = "none",
    subtitle_style: str = "impact",
) -> str:
    normalized_effect = subtitle_renderer.normalize_video_effect(video_effect)
    if (
        not has_subtitles
        and not has_lower_third
        and not has_intro_outro
        and not has_progress_bar
        and not has_watermark
        and normalized_effect == "none"
    ):
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
    if has_lower_third:
        parts.append("lower-third")
    if has_intro_outro:
        parts.append("intro-outro")
    if has_progress_bar:
        parts.append("progress")
    if has_watermark:
        parts.append("watermark")
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
    has_lower_third: bool = False,
    has_intro_outro: bool = False,
    has_progress_bar: bool = False,
    has_watermark: bool = False,
    video_effect: str = "none",
    subtitle_style: str = "impact",
) -> Path:
    suffix = download_variant_suffix(
        to_shorts,
        has_logo,
        has_subtitles=has_subtitles,
        has_lower_third=has_lower_third,
        has_intro_outro=has_intro_outro,
        has_progress_bar=has_progress_bar,
        has_watermark=has_watermark,
        video_effect=video_effect,
        subtitle_style=subtitle_style,
    )
    extension = ".mp4" if suffix else input_path.suffix
    return input_path.with_name(f"{input_path.stem}{suffix}{extension}")


def normalize_logo_position(position: object) -> str:
    normalized = str(position or "").strip().lower().replace("_", "-")
    return normalized if normalized in LOGO_POSITIONS else DEFAULT_LOGO_POSITION


def logo_position_label(position: object) -> str:
    return LOGO_POSITION_LABELS[normalize_logo_position(position)]


def _coerce_float(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def logo_scale_percent_to_width_ratio(percent: object) -> float:
    try:
        value = int(percent)
    except (TypeError, ValueError):
        return DEFAULT_LOGO_WIDTH_RATIO
    normalized = (max(20, min(80, value)) - 20) / 60.0
    return 0.10 + (normalized * 0.12)


def logo_width_ratio_to_scale_percent(ratio: object) -> int:
    width_ratio = normalize_logo_width_ratio(ratio)
    normalized = (width_ratio - 0.10) / 0.12
    return max(20, min(80, int(round(20 + (normalized * 60)))))


def normalize_logo_width_ratio(value: object) -> float:
    ratio = _coerce_float(value, DEFAULT_LOGO_WIDTH_RATIO)
    return max(MIN_LOGO_WIDTH_RATIO, min(MAX_LOGO_WIDTH_RATIO, ratio))


def effective_logo_width_ratio(
    value: object,
    *,
    portrait: bool = False,
) -> float:
    ratio = normalize_logo_width_ratio(value)
    if not portrait:
        return ratio
    boosted = max(PORTRAIT_LOGO_MIN_WIDTH_RATIO, ratio * PORTRAIT_LOGO_WIDTH_MULTIPLIER)
    return min(PORTRAIT_LOGO_MAX_WIDTH_RATIO, boosted)


def normalize_logo_x_ratio(value: object, width_ratio: object | None = None) -> float:
    ratio = _coerce_float(value, DEFAULT_LOGO_X_RATIO)
    return max(0.0, min(1.0, ratio))


def normalize_logo_y_ratio(value: object) -> float:
    ratio = _coerce_float(value, DEFAULT_LOGO_Y_RATIO)
    return max(0.0, min(0.95, ratio))


def logo_position_to_ratios(
    position: object,
    width_ratio: object | None = None,
) -> tuple[float, float]:
    normalized = normalize_logo_position(position)
    x_ratio, y_ratio = PRESET_LOGO_RATIOS[normalized]
    return normalize_logo_x_ratio(x_ratio, width_ratio), normalize_logo_y_ratio(y_ratio)


def logo_ratios_match_position(
    position: object,
    width_ratio: object,
    x_ratio: object,
    y_ratio: object,
    *,
    tolerance: float = 0.008,
) -> bool:
    expected_x, expected_y = logo_position_to_ratios(position, width_ratio)
    normalized_x = normalize_logo_x_ratio(x_ratio, width_ratio)
    normalized_y = normalize_logo_y_ratio(y_ratio)
    return (
        abs(normalized_x - expected_x) <= tolerance
        and abs(normalized_y - expected_y) <= tolerance
    )


def _margin_expr(margin: int | str) -> str:
    if isinstance(margin, int):
        return str(margin)
    return str(margin)


def logo_overlay_margin_expr() -> str:
    return r"max(24\,min(W\,H)*0.040)"


def logo_overlay_x_expr(position: object, margin: int | str = 36) -> str:
    normalized = normalize_logo_position(position)
    margin_expr = _margin_expr(margin)
    if normalized.endswith("-left"):
        return margin_expr
    if normalized.endswith("-right"):
        return f"W-w-{margin_expr}"
    return "(W-w)/2"


def logo_overlay_y_expr(position: object, margin: int | str = 36) -> str:
    normalized = normalize_logo_position(position)
    margin_expr = _margin_expr(margin)
    if normalized.startswith("top"):
        return margin_expr
    if normalized.startswith("bottom"):
        return f"H-h-{margin_expr}"
    return "(H-h)/2"


def logo_opacity_ratio(percent: int) -> float:
    try:
        value = int(percent)
    except (TypeError, ValueError):
        value = 100
    value = max(10, min(100, value))
    return value / 100.0
