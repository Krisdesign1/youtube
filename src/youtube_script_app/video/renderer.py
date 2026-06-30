"""FFmpeg video rendering pipeline for creative variants."""

from __future__ import annotations

import functools
import re
import subprocess
import json
import shutil
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, List, Sequence

from PIL import Image

from ..core import lower_third, subtitle_renderer
from ..downloads import utils as download_utils

_SUBPROCESS_RUN = subprocess.run


@functools.lru_cache(maxsize=4)
def _detect_hw_video_encoder(ffmpeg_path: str) -> tuple[str, list[str]]:
    """Always use libx264 for maximum quality consistency."""
    return "libx264", ["-preset", VIDEO_ENCODER_PRESET, "-crf", VIDEO_ENCODER_CRF, "-pix_fmt", "yuv420p"]

VIDEO_ENCODER_PRESET = "slow"
VIDEO_ENCODER_CRF = "14"
AUDIO_ENCODER_BITRATE = "256k"
SCALE_FLAGS = "lanczos+accurate_rnd+full_chroma_int"
# Upscaling below this short edge. Set to 0 to disable forced upscale.
# Forcing 360p → 1080p adds no real detail and degrades perceived quality.
MIN_FULL_HD_SHORT_EDGE = 0
VIDEO_SHARPEN_FILTER = "unsharp=5:5:0.45:5:5:0.0"
LOWER_THIRD_SLIDE_DURATION = 0.4


@dataclass(frozen=True)
class VideoRenderOptions:
    input_path: Path
    ffmpeg_path: str
    to_shorts: bool = False
    logo_path: str = ""
    logo_position: str = download_utils.DEFAULT_LOGO_POSITION
    logo_size_mode: str = "relative"
    logo_scale_percent: int = download_utils.DEFAULT_LOGO_SCALE_PERCENT
    logo_opacity_percent: int = 100
    logo_width_ratio: float | None = None
    logo_x_ratio: float | None = None
    logo_y_ratio: float | None = None
    logo_original_width: int | None = None
    logo_original_height: int | None = None
    subtitle_chunks: Sequence[dict] | None = None
    subtitle_start: float = 0.0
    subtitle_duration: float | None = None
    subtitle_offset_ms: int = 0
    clip_duration: float | None = None
    lower_third_interval: float = lower_third.DEFAULT_DISPLAY_INTERVAL_SECONDS
    lower_third_display_duration: float = lower_third.DEFAULT_DISPLAY_DURATION_SECONDS
    intro_outro_enabled: bool = False
    intro_outro_channel_name: str = ""
    intro_outro_hold_duration: float = 1.5
    intro_outro_bg_color: str = "0x000000@0.55"
    intro_outro_text_color: str = "white"
    progress_bar_enabled: bool = False
    animated_watermark_enabled: bool = False
    watermark_logo_path: str = ""
    subtitle_style: str = "impact"
    video_effect: str = "none"
    lower_third_config: lower_third.LowerThirdConfig | None = None
    preview_width: int | None = None
    logo_display_duration: float | None = None  # None = visible toute la vidéo
    shorts_blur_bg: bool = True  # fond flouté pillarbox pour les Shorts


@dataclass(frozen=True)
class LogoPosition:
    x_ratio: float
    y_ratio: float


@dataclass(frozen=True)
class VideoEffectConfig:
    name: str


@dataclass(frozen=True)
class LogoRenderConfig:
    path: str
    width_px: int
    x_px: int
    y_px: int
    opacity: float
    duration: float | None = None  # None = toujours visible


@dataclass(frozen=True)
class SubtitleRenderConfig:
    srt_path: str
    force_style: str = ""


@dataclass(frozen=True)
class LowerThirdRenderConfig:
    path: str
    position: str = "bottom"
    band_h_px: int = 0


@dataclass(frozen=True)
class IntroOutroRenderConfig:
    duration: float
    channel_name: str
    video_width: int
    video_height: int
    hold_duration: float = 1.5
    bg_color: str = "0x000000@0.55"
    text_color: str = "white"


@dataclass(frozen=True)
class ProgressBarRenderConfig:
    duration: float
    video_width: int
    video_height: int
    color: str = "0xE85D3A"


@dataclass(frozen=True)
class WatermarkRenderConfig:
    path: str
    width_px: int
    x_px: int
    y_px: int


PRESET_POSITIONS: dict[str, tuple[float, float]] = dict(
    download_utils.PRESET_LOGO_RATIOS
)

EFFECT_FILTERS: dict[str, str] = {
    "bw": "hue=s=0",
    "black_white": "hue=s=0",
    "contrast": subtitle_renderer.VIDEO_EFFECT_FILTERS["contrast"],
    "vintage": subtitle_renderer.VIDEO_EFFECT_FILTERS["vintage"],
    "cinema_dark": subtitle_renderer.VIDEO_EFFECT_FILTERS["cinematic"],
    "cinematic": subtitle_renderer.VIDEO_EFFECT_FILTERS["cinematic"],
}


def _clamp_logo_scale_percent(value: object) -> int:
    try:
        percent = int(value)
    except (TypeError, ValueError):
        percent = download_utils.DEFAULT_LOGO_SCALE_PERCENT
    return max(20, min(80, percent))


def _logo_frame_scale_ratios(percent: int) -> tuple[float, float]:
    width_ratio = download_utils.logo_scale_percent_to_width_ratio(percent)
    normalized = (max(20, min(80, percent)) - 20) / 60.0
    return width_ratio, 0.045 + (normalized * 0.045)


def logo_frame_width_percent(percent: int) -> int:
    width_ratio, _ = _logo_frame_scale_ratios(_clamp_logo_scale_percent(percent))
    return int(round(width_ratio * 100))


def compute_logo_width(
    mode: str,
    slider_value: float,
    video_width: int,
    video_format: str,
    original_logo_width: int | None = None,
) -> int:
    """Compute the logo render width in pixels."""
    normalized_mode = str(mode or "relative").strip().lower()
    if normalized_mode == "relative":
        normalized = (max(20.0, min(80.0, float(slider_value))) - 20.0) / 60.0
        ratio = 0.10 + (normalized * 0.12)
        if video_format == "9:16":
            ratio = max(0.24, min(0.44, ratio * 1.8))
        return max(1, int(video_width * ratio))

    if normalized_mode == "original":
        if original_logo_width is None:
            raise ValueError("original_logo_width requis pour le mode 'original'.")
        max_px = int(video_width * 0.30)
        return max(1, min(int(original_logo_width), max_px))

    raise ValueError(
        f"Mode de taille logo inconnu : '{mode}'. "
        "Valeurs acceptées : 'relative', 'original'."
    )


def resolve_logo_position(
    position_name: str,
    x_ratio_custom: float,
    y_ratio_custom: float,
    video_width: int,
    video_height: int,
    logo_width_px: int,
    logo_height_px: int,
) -> tuple[int, int]:
    """Return top-left logo coordinates in pixels."""
    normalized_position = download_utils.normalize_logo_position(position_name)
    if position_name == "custom":
        rx, ry = float(x_ratio_custom), float(y_ratio_custom)
    else:
        rx, ry = PRESET_POSITIONS.get(normalized_position, PRESET_POSITIONS["top-right"])

    if "right" in normalized_position and position_name != "custom":
        x_px = int(video_width * rx) - logo_width_px
    elif normalized_position in {"top", "bottom", "center"} and position_name != "custom":
        x_px = int(video_width * rx) - (logo_width_px // 2)
    else:
        x_px = int(video_width * rx)

    if "bottom" in normalized_position and position_name != "custom":
        y_px = int(video_height * ry) - logo_height_px
    elif (
        normalized_position in {"center", "center-left", "center-right"}
        and position_name != "custom"
    ):
        y_px = int(video_height * ry) - (logo_height_px // 2)
    else:
        y_px = int(video_height * ry)

    x_px = max(0, min(x_px, video_width - logo_width_px))
    y_px = max(0, min(y_px, video_height - logo_height_px))
    return x_px, y_px


def _even_dimension(value: float, *, minimum: int = 2) -> int:
    dimension = max(minimum, int(round(value)))
    return dimension if dimension % 2 == 0 else dimension + 1


def _ffprobe_path(ffmpeg_path: str) -> str | None:
    executable = Path(ffmpeg_path)
    candidate = executable.with_name("ffprobe")
    if candidate.exists():
        return str(candidate)
    return shutil.which("ffprobe")


def _probe_media_size(ffmpeg_path: str, path: Path) -> tuple[int, int] | None:
    ffprobe_path = _ffprobe_path(ffmpeg_path)
    if ffprobe_path is None:
        return None
    try:
        result = _SUBPROCESS_RUN(
            [
                ffprobe_path,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=30,
        )
        streams = json.loads(result.stdout or "{}").get("streams", [])
        if not streams:
            return None
        width = int(streams[0].get("width", 0))
        height = int(streams[0].get("height", 0))
    except (OSError, subprocess.CalledProcessError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if width <= 0 or height <= 0:
        return None
    return width, height


def _probe_media_duration(ffmpeg_path: str, path: Path) -> float | None:
    ffprobe_path = _ffprobe_path(ffmpeg_path)
    if ffprobe_path is None:
        return None
    try:
        result = _SUBPROCESS_RUN(
            [
                ffprobe_path,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=30,
        )
        duration = float(json.loads(result.stdout or "{}").get("format", {}).get("duration", 0))
    except (OSError, subprocess.CalledProcessError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return duration if duration > 0 else None


def _probe_audio_codec(ffmpeg_path: str, path: Path) -> str | None:
    ffprobe_path = _ffprobe_path(ffmpeg_path)
    if ffprobe_path is None:
        return None
    try:
        result = _SUBPROCESS_RUN(
            [
                ffprobe_path,
                "-v", "error",
                "-select_streams", "a:0",
                "-show_entries", "stream=codec_name",
                "-of", "json",
                str(path),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=30,
        )
        streams = json.loads(result.stdout or "{}").get("streams", [])
        return str(streams[0].get("codec_name", "")).lower() if streams else None
    except (OSError, subprocess.CalledProcessError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _minimum_full_hd_size(width: int, height: int) -> tuple[int, int]:
    short_edge = min(width, height)
    if short_edge >= MIN_FULL_HD_SHORT_EDGE:
        return width, height
    scale_factor = MIN_FULL_HD_SHORT_EDGE / short_edge
    return _even_dimension(width * scale_factor), _even_dimension(height * scale_factor)


def _base_video_geometry(options: VideoRenderOptions) -> tuple[int, int, bool]:
    upscale_to_full_hd = False
    if options.to_shorts:
        width, height = 1080, 1920
    else:
        probed = _probe_media_size(options.ffmpeg_path, Path(options.input_path))
        width, height = probed if probed is not None else (1920, 1080)
        if probed is not None and not options.preview_width:
            target_width, target_height = _minimum_full_hd_size(width, height)
            upscale_to_full_hd = (target_width, target_height) != (width, height)
            width, height = target_width, target_height
    if options.preview_width:
        preview_width = max(240, min(1080, int(options.preview_width)))
        height = _even_dimension(preview_width * (height / width))
        width = preview_width
    return width, height, upscale_to_full_hd


def _base_video_size(options: VideoRenderOptions) -> tuple[int, int]:
    width, height, _upscale_to_full_hd = _base_video_geometry(options)
    return width, height


def _logo_width_ratio(options: VideoRenderOptions) -> float:
    if options.logo_width_ratio is not None:
        return download_utils.normalize_logo_width_ratio(options.logo_width_ratio)
    return download_utils.logo_scale_percent_to_width_ratio(options.logo_scale_percent)


def _probe_logo_size(path: str) -> tuple[int, int] | None:
    try:
        with Image.open(path) as image:
            return image.size
    except Exception:
        return None


def _logo_source_size(options: VideoRenderOptions) -> tuple[int, int]:
    if options.logo_original_width and options.logo_original_height:
        return options.logo_original_width, options.logo_original_height
    probed = _probe_logo_size(options.logo_path)
    if probed is not None:
        return probed
    width = max(1, int(options.logo_original_width or 100))
    height = max(1, int(options.logo_original_height or round(width * 0.36)))
    return width, height


def _logo_overlay_geometry(options: VideoRenderOptions) -> tuple[int, int, int, int]:
    frame_width, frame_height = _base_video_size(options)
    source_width, source_height = _logo_source_size(options)
    frame_format = "9:16" if frame_height > frame_width else "16:9"
    logo_width = compute_logo_width(
        options.logo_size_mode,
        options.logo_scale_percent,
        frame_width,
        frame_format,
        original_logo_width=source_width,
    )
    aspect_ratio = source_height / source_width if source_width else 0.36
    logo_height = max(1, int(round(logo_width * aspect_ratio)))
    base_width_ratio = logo_width / frame_width
    use_position_ratios = options.logo_x_ratio is None or options.logo_y_ratio is None
    if not use_position_ratios:
        use_position_ratios = download_utils.logo_ratios_match_position(
            options.logo_position,
            base_width_ratio,
            options.logo_x_ratio,
            options.logo_y_ratio,
        )
    if use_position_ratios:
        x, y = resolve_logo_position(
            options.logo_position,
            0.0,
            0.0,
            frame_width,
            frame_height,
            logo_width,
            logo_height,
        )
    else:
        x, y = resolve_logo_position(
            "custom",
            download_utils.normalize_logo_x_ratio(options.logo_x_ratio, base_width_ratio),
            download_utils.normalize_logo_y_ratio(options.logo_y_ratio),
            frame_width,
            frame_height,
            logo_width,
            logo_height,
        )
    return logo_width, logo_height, x, y


def _watermark_overlay_geometry(
    video_width: int,
    video_height: int,
    *,
    width_ratio: float = 0.12,
    x_ratio: float = 0.95,
    y_ratio: float = 0.05,
) -> tuple[int, int, int]:
    logo_width = max(1, int(video_width * width_ratio))
    x = int(video_width * x_ratio) - logo_width
    y = int(video_height * y_ratio)
    return logo_width, max(0, min(x, video_width - logo_width)), max(0, y)


def _build_base_video_filters(
    to_shorts: bool,
    preview_width: int | None,
    *,
    upscale_width: int | None = None,
    upscale_height: int | None = None,
    blur_bg: bool = False,
) -> List[str]:
    filters: List[str] = []
    if to_shorts and not blur_bg:
        # blur_bg uses a split/overlay approach handled in build_filter_complex
        filters.append(
            f"scale=1080:1920:force_original_aspect_ratio=increase:flags={SCALE_FLAGS}"
        )
        filters.append("crop=1080:1920")
    elif upscale_width and upscale_height:
        filters.append(f"scale={upscale_width}:{upscale_height}:flags={SCALE_FLAGS}")
    if preview_width:
        width = max(240, min(1080, int(preview_width)))
        filters.append(f"scale={width}:-2:flags={SCALE_FLAGS}")
    filters.append(VIDEO_SHARPEN_FILTER)
    return filters


def _called_process_message(error: subprocess.CalledProcessError) -> str:
    raw = (error.stderr or "").strip()
    lines = [line for line in raw.splitlines() if line.strip()]
    if not lines:
        return "Le traitement du clip a échoué."

    # Lines that start with a bracketed debug tag (e.g. "[mov,mp4 @ 0x...]") are
    # demuxer/muxer diagnostics and may be warnings, not errors — skip them when
    # searching for the real failure reason.
    _BRACKET_TAG_RE = re.compile(r"^\[[\w,.:/ ]+@ 0x[0-9a-f]+\]", re.IGNORECASE)

    # Error lines from filters/encoders start with "Error" or contain these keywords.
    error_keywords = (
        "invalid argument",
        "no such file",
        "permission denied",
        "codec not found",
        "unknown encoder",
        "could not find tag",
        "error while opening",
        "error initializing",
        "error evaluating",
        "moov atom not found",
        "Invalid data found",
        "not found",
    )

    # Prefer lines that look like real errors (not bare demuxer debug tags).
    for line in reversed(lines):
        lower = line.lower()
        is_debug_tag = bool(_BRACKET_TAG_RE.match(line.strip()))
        for keyword in error_keywords:
            if keyword in lower:
                if is_debug_tag and "error" not in lower:
                    # This is a demuxer warning (e.g. "moov atom not found"),
                    # not the actual failure — keep scanning.
                    break
                last = lines[-1]
                if last != line and last not in line:
                    return f"{line.strip()} — {last.strip()}"
                return line.strip()

    return lines[-1]


def _filter_number(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _escape_drawtext_text(value: object) -> str:
    text = str(value or "")
    return (
        text.replace("\\", "\\\\")
        .replace(":", r"\:")
        .replace("'", r"\'")
        .replace(",", r"\,")
        .replace("%", r"\%")
    )


def _coerce_positive_duration(value: object) -> float | None:
    if value is None:
        return None
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return None
    return duration if duration > 0 else None


def _clamp_float(value: object, default: float, minimum: float, maximum: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = default
    return max(minimum, min(maximum, numeric))


def build_lower_third_overlay_options(
    clip_duration: float | None = None,
    *,
    interval: float = lower_third.DEFAULT_DISPLAY_INTERVAL_SECONDS,
    display_duration: float = lower_third.DEFAULT_DISPLAY_DURATION_SECONDS,
    position: str = "bottom",
    y_offset_px: int = 0,
) -> tuple[str, str | None]:
    """Return (overlay_options, fade_expr_or_None).

    For 'top-center': y-slide animation + fade expression.
    For other positions: x-slide animation, no fade.
    """
    interval = _clamp_float(
        interval,
        lower_third.DEFAULT_DISPLAY_INTERVAL_SECONDS,
        lower_third.MIN_DISPLAY_INTERVAL_SECONDS,
        lower_third.MAX_DISPLAY_INTERVAL_SECONDS,
    )
    display_duration = _clamp_float(
        display_duration,
        lower_third.DEFAULT_DISPLAY_DURATION_SECONDS,
        lower_third.MIN_DISPLAY_DURATION_SECONDS,
        min(lower_third.MAX_DISPLAY_DURATION_SECONDS, interval),
    )
    duration = _coerce_positive_duration(clip_duration)
    if duration:
        display_duration = min(display_duration, duration)
    slide_duration = min(LOWER_THIRD_SLIDE_DURATION, max(0.1, display_duration / 2))
    interval_text = _filter_number(interval)
    display_duration_text = _filter_number(display_duration)
    slide_duration_text = _filter_number(slide_duration)
    slide_out_start_text = _filter_number(display_duration - slide_duration)
    phase = f"mod(t,{interval_text})"

    if position == "top-center":
        # Y-slide: band drops from (y_base - h) to y_base, stays, then rises back.
        # y_offset_px places the band within the pillarbox (0=top, pillarbox_h-band_h=bottom).
        y_base = str(y_offset_px)
        y_expression = (
            f"if(lt({phase},{display_duration_text}),"
            f"if(lt({phase},{slide_duration_text}),"
            f"{y_base}-h+{phase}*(h/{slide_duration_text}),"
            f"if(gt({phase},{slide_out_start_text}),"
            f"{y_base}-(({phase}-{slide_out_start_text}))*(h/{slide_duration_text}),"
            f"{y_base})),"
            f"{y_base}-h)"
        )
        return f"x=0:y='{y_expression}':eval=frame:format=auto", None

    # Standard x-slide (bottom / top)
    x_expression = (
        f"if(lt({phase},{display_duration_text}),"
        f"if(lt({phase},{slide_duration_text}),"
        f"-W+{phase}*(W/{slide_duration_text}),"
        f"if(gt({phase},{slide_out_start_text}),"
        f"-({phase}-{slide_out_start_text})*(W/{slide_duration_text}),"
        "0)),-W)"
    )
    return f"x='{x_expression}':y=H-h:format=auto", None


def build_intro_outro_filter(
    clip_duration: float,
    channel_name: str,
    video_width: int,
    video_height: int,
    fade_duration: float = 0.5,
    hold_duration: float = 1.5,
    bg_color: str = "0x000000@0.55",
    text_color: str = "white",
) -> str:
    duration = _coerce_positive_duration(clip_duration) or 0.0
    fade_duration = min(max(0.1, float(fade_duration)), max(0.1, duration / 2))
    hold_duration = min(max(0.1, float(hold_duration)), max(0.1, duration))
    fade_out_start = max(0.0, duration - fade_duration)
    font_size = max(18, int(video_height * 0.06))
    shadow_px = max(2, int(video_height * 0.004))
    box_h = max(60, int(video_height * 0.16))
    box_y = (video_height - box_h) // 2
    hold_txt = _filter_number(hold_duration)
    safe_bg = str(bg_color).strip() or "0x000000@0.55"
    safe_text = str(text_color).strip() or "white"
    return (
        f"fade=t=in:st=0:d={_filter_number(fade_duration)},"
        f"fade=t=out:st={_filter_number(fade_out_start)}:d={_filter_number(fade_duration)},"
        f"drawbox=x=0:y={box_y}:w={video_width}:h={box_h}:color={safe_bg}:t=fill:enable='lt(t,{hold_txt})',"
        "drawtext="
        f"text='{_escape_drawtext_text(channel_name)}':"
        f"fontsize={font_size}:"
        f"fontcolor={safe_text}:"
        "x=(W-text_w)/2:"
        "y=(H-text_h)/2:"
        f"alpha='if(lt(t,{hold_txt}),1,0)':"
        f"shadowcolor=black:shadowx={shadow_px}:shadowy={shadow_px}"
    )


def build_progress_bar_filter(
    clip_duration: float,
    video_width: int,
    video_height: int,
    *,
    bar_color: str = "0xE85D3A",
    bar_height_ratio: float = 0.008,
    position: str = "bottom",
) -> tuple[str, str]:
    duration = _coerce_positive_duration(clip_duration) or 1.0
    bar_w = max(2, int(video_width))
    bar_h = max(4, int(video_height * bar_height_ratio))
    bar_y = "H-h" if position == "bottom" else "0"
    source = f"color=c={bar_color}@1.0:s={bar_w}x{bar_h}:d={duration + 1.0:.4f}"
    overlay = (
        f"x='max(-w,min(0,-w+w*t/{duration:.4f}))':"
        f"y={bar_y}:format=auto:eval=frame"
    )
    return source, overlay


def build_filter_complex(
    effect: VideoEffectConfig | None,
    intro_outro_config: IntroOutroRenderConfig | None,
    progress_bar_config: ProgressBarRenderConfig | None,
    watermark_config: WatermarkRenderConfig | None,
    logo: LogoRenderConfig | None,
    lower_third_config: LowerThirdRenderConfig | None,
    subtitles: SubtitleRenderConfig | None,
    *,
    base_filters: Sequence[str] | None = None,
    lower_third_duration: float | None = None,
    lower_third_interval: float = lower_third.DEFAULT_DISPLAY_INTERVAL_SECONDS,
    lower_third_display_duration: float = lower_third.DEFAULT_DISPLAY_DURATION_SECONDS,
    lower_third_y_offset_px: int = 0,
    shorts_blur_bg: bool = False,
) -> tuple[str, list[str]]:
    """Build the ffmpeg filter graph in the order: effect, base, logo, lower third, subtitles."""
    stages: list[str] = []
    extra_inputs: list[str] = []
    current = "[0:v]"
    input_index = 1

    if effect:
        effect_filter = EFFECT_FILTERS.get(effect.name)
        if effect_filter is None:
            raise ValueError(f"Effet inconnu : '{effect.name}'")
        stages.append(f"{current}{effect_filter}[effected]")
        current = "[effected]"

    if shorts_blur_bg:
        # Pillarbox: blurred background + original video centred, no crop
        stages.append(f"{current}split[_bg_raw][_fg_raw]")
        stages.append(
            f"[_bg_raw]scale=1080:1920:force_original_aspect_ratio=increase:flags={SCALE_FLAGS},"
            "crop=1080:1920,boxblur=luma_radius=12:luma_power=2[_bg_blurred]"
        )
        stages.append(
            f"[_fg_raw]scale=1080:1920:force_original_aspect_ratio=decrease:flags={SCALE_FLAGS},"
            "setsar=1[_fg_sized]"
        )
        stages.append("[_bg_blurred][_fg_sized]overlay=(W-w)/2:(H-h)/2[_shorts_comp]")
        current = "[_shorts_comp]"

    if base_filters:
        stages.append(f"{current}{','.join(base_filters)}[base]")
        current = "[base]"

    if intro_outro_config:
        intro_outro_filter = build_intro_outro_filter(
            intro_outro_config.duration,
            intro_outro_config.channel_name,
            intro_outro_config.video_width,
            intro_outro_config.video_height,
            hold_duration=intro_outro_config.hold_duration,
            bg_color=intro_outro_config.bg_color,
            text_color=intro_outro_config.text_color,
        )
        stages.append(f"{current}{intro_outro_filter}[introoutro]")
        current = "[introoutro]"

    if progress_bar_config:
        progress_source, progress_overlay = build_progress_bar_filter(
            progress_bar_config.duration,
            progress_bar_config.video_width,
            progress_bar_config.video_height,
            bar_color=progress_bar_config.color,
        )
        stages.append(f"{progress_source}[progressbar]")
        stages.append(f"{current}[progressbar]overlay={progress_overlay}[progress]")
        current = "[progress]"

    if watermark_config:
        # Pulsing opacity: use lut filter on alpha channel (cheaper than geq per-pixel eval)
        # lut maps alpha to alpha * (0.50 + 0.25*sin(T)) via colorchannelmixer with time-varying aa
        # Since lut can't use T directly, use fade+overlay cycling at video rate instead.
        # Implementation: scale → format=rgba → alphamerge trick replaced by
        # colorchannelmixer with fixed 75% opacity (no per-frame geq cost).
        extra_inputs.append(watermark_config.path)
        stages.append(
            f"[{input_index}:v]"
            f"scale={watermark_config.width_px}:-1:flags={SCALE_FLAGS},"
            "format=rgba,"
            "colorchannelmixer=aa=0.75"
            "[watermark]"
        )
        stages.append(
            f"{current}[watermark]overlay={watermark_config.x_px}:{watermark_config.y_px}:format=auto[withwatermark]"
        )
        current = "[withwatermark]"
        input_index += 1

    if logo:
        extra_inputs.append(logo.path)
        shadow_off = max(3, int(logo.width_px * 0.04))
        shadow_x = max(0, logo.x_px + shadow_off)
        shadow_y = max(0, logo.y_px + shadow_off)
        dur_enable = (
            f":enable='lt(t,{logo.duration:.3f})'"
            if logo.duration is not None and logo.duration > 0
            else ""
        )
        # Scale + prepare → split into fg (logo) + bg (shadow source)
        stages.append(
            f"[{input_index}:v]"
            f"scale={logo.width_px}:-1:flags={SCALE_FLAGS},"
            "setsar=1,"
            "format=rgba,"
            f"colorchannelmixer=aa={logo.opacity:.3f},"
            "split[logo_fg][logo_bg]"
        )
        # Shadow: darken to black — soft drop shadow (no blur, saves per-frame convolution)
        stages.append(
            "[logo_bg]"
            "colorchannelmixer=rr=0:gg=0:bb=0:aa=0.4"
            "[logo_shadow]"
        )
        # Composite shadow first (offset), then logo on top
        stages.append(
            f"{current}[logo_shadow]"
            f"overlay={shadow_x}:{shadow_y}:format=auto{dur_enable}"
            "[with_shadow]"
        )
        stages.append(
            f"[with_shadow][logo_fg]"
            f"overlay={logo.x_px}:{logo.y_px}:format=auto{dur_enable}"
            "[withlogo]"
        )
        current = "[withlogo]"
        input_index += 1

    if lower_third_config:
        extra_inputs.append(lower_third_config.path)
        overlay_options, fade_expr = build_lower_third_overlay_options(
            lower_third_duration,
            interval=lower_third_interval,
            display_duration=lower_third_display_duration,
            position=lower_third_config.position,
            y_offset_px=lower_third_y_offset_px,
        )
        if lower_third_config.position == "top-center":
            # Loop the PNG for proper timestamps; eof_action=endall prevents ffmpeg from
            # hanging indefinitely waiting for the infinite loop stream to end.
            stages.append(
                f"[{input_index}:v]"
                "loop=loop=-1:size=1:start=0,"
                "format=rgba[lowerthird]"
            )
            stages.append(f"{current}[lowerthird]overlay={overlay_options}:eof_action=endall[withlowerthird]")
        else:
            stages.append(f"[{input_index}:v]format=rgba[lowerthird]")
            stages.append(f"{current}[lowerthird]overlay={overlay_options}[withlowerthird]")
        current = "[withlowerthird]"
        input_index += 1

    if subtitles:
        escaped_path = subtitle_renderer.escape_ass_path(subtitles.srt_path)
        subtitle_filter = f"subtitles=filename='{escaped_path}'"
        if subtitles.force_style:
            subtitle_filter = f"{subtitle_filter}:force_style='{subtitles.force_style}'"
        stages.append(f"{current}{subtitle_filter}[outv]")
        current = "[outv]"

    if current != "[outv]":
        stages.append(f"{current}null[outv]")

    return ";".join(stages), extra_inputs


def build_ffmpeg_command(
    input_video: str,
    output_path: str,
    filter_complex: str,
    extra_inputs: list[str],
    *,
    ffmpeg_path: str = "ffmpeg",
    encode_audio: bool = True,
    audio_copy: bool = False,
) -> list[str]:
    """Assemble the ffmpeg command from a prepared filter graph."""
    cmd = [ffmpeg_path, "-y", "-threads", "0", "-i", input_video]
    for extra in extra_inputs:
        cmd.extend(["-i", extra])
    cmd.extend(["-filter_complex", filter_complex, "-map", "[outv]"])
    if encode_audio:
        if audio_copy:
            cmd.extend(["-map", "0:a?", "-c:a", "copy"])
        else:
            cmd.extend(["-map", "0:a?", "-c:a", "aac", "-b:a", AUDIO_ENCODER_BITRATE])
    encoder_name, encoder_args = _detect_hw_video_encoder(ffmpeg_path)
    cmd.extend(["-c:v", encoder_name, *encoder_args, "-movflags", "+faststart", output_path])
    return cmd


def render_video_variant(
    options: VideoRenderOptions,
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> Path:
    input_path = Path(options.input_path)
    if not input_path.exists():
        raise RuntimeError(
            f"Fichier introuvable : {input_path.name}\n"
            "Le téléchargement a peut-être échoué ou le fichier a été déplacé."
        )
    if input_path.stat().st_size == 0:
        raise RuntimeError(
            f"Fichier vide : {input_path.name}\n"
            "Le téléchargement est incomplet. Réessaie le téléchargement."
        )
    has_logo = bool(options.logo_path)
    normalized_effect = subtitle_renderer.normalize_video_effect(options.video_effect)
    normalized_subtitle_style = subtitle_renderer.normalize_subtitle_style(
        options.subtitle_style
    )
    frame_width, frame_height, upscale_to_full_hd = _base_video_geometry(options)
    frame_format = "9:16" if frame_height > frame_width else "16:9"
    subtitle_offset_sec = (options.subtitle_offset_ms or 0) / 1000.0
    if normalized_subtitle_style == "word":
        subtitle_chunks = subtitle_renderer.rechunk_words(
            options.subtitle_chunks or [],
            frame_format,
            clip_start=options.subtitle_start,
            clip_duration=options.subtitle_duration,
            offset_sec=subtitle_offset_sec,
        )
    else:
        subtitle_chunks = subtitle_renderer.rechunk_blocks(
            options.subtitle_chunks or [],
            frame_format,
            clip_start=options.subtitle_start,
            clip_duration=options.subtitle_duration,
            offset_sec=subtitle_offset_sec,
        )
    has_subtitles = bool(subtitle_chunks)
    has_lower_third = options.lower_third_config is not None
    render_duration = _coerce_positive_duration(options.clip_duration)
    if render_duration is None:
        render_duration = _coerce_positive_duration(options.subtitle_duration)
    if render_duration is None and (
        options.intro_outro_enabled or options.progress_bar_enabled
    ):
        render_duration = _probe_media_duration(options.ffmpeg_path, input_path)
    has_intro_outro = bool(
        options.intro_outro_enabled
        and render_duration
        and str(options.intro_outro_channel_name).strip()
    )
    has_progress_bar = bool(options.progress_bar_enabled and render_duration)
    has_watermark = bool(
        options.animated_watermark_enabled and str(options.watermark_logo_path).strip()
    )
    has_preview_scale = bool(options.preview_width)
    if (
        not options.to_shorts
        and not has_logo
        and not has_subtitles
        and not has_lower_third
        and not has_intro_outro
        and not has_progress_bar
        and not has_watermark
        and normalized_effect == "none"
        and not has_preview_scale
    ):
        return input_path

    logo_width, _logo_height, logo_x, logo_y = (
        _logo_overlay_geometry(options) if has_logo else (0, 0, 0, 0)
    )
    logo_opacity_ratio = download_utils.logo_opacity_ratio(options.logo_opacity_percent)

    output_path = download_utils.download_variant_output_path(
        input_path,
        options.to_shorts,
        has_logo,
        has_subtitles=has_subtitles,
        has_lower_third=has_lower_third,
        has_intro_outro=has_intro_outro,
        has_progress_bar=has_progress_bar,
        has_watermark=has_watermark,
        video_effect=normalized_effect,
        subtitle_style=normalized_subtitle_style,
    )
    if (
        not has_logo
        and output_path.exists()
        and output_path.stat().st_mtime >= input_path.stat().st_mtime
    ):
        return output_path

    try:
        use_blur_bg = options.to_shorts and options.shorts_blur_bg and not options.preview_width

        # For shorts pillarbox: place the band at the correct vertical position.
        # Probe source dims to compute pillarbox height; fall back to 16:9.
        _lt_config_effective = options.lower_third_config
        _lt_y_offset_px = 0
        if (
            use_blur_bg
            and has_lower_third
            and options.lower_third_config is not None
            and options.lower_third_config.position == "top-center"
        ):
            _src_size = _probe_media_size(options.ffmpeg_path, input_path)
            if _src_size:
                _src_w, _src_h = _src_size
                _fg_h = int(frame_width * _src_h / _src_w) if _src_w > 0 else 0
            else:
                _fg_h = int(frame_width * 9 / 16)
            _pillarbox_h = (frame_height - _fg_h) // 2
            if _pillarbox_h > 0:
                _band_h = lower_third.lower_third_band_height(options.lower_third_config, frame_height)
                _valign = options.lower_third_config.vertical_align
                if _valign == "bottom":
                    _lt_y_offset_px = max(0, _pillarbox_h - _band_h)
                elif _valign == "center":
                    _lt_y_offset_px = max(0, (_pillarbox_h - _band_h) // 2)
                # "top" → y_offset stays 0

        # Copy audio stream when source is already AAC — avoids full re-encode (10-15% faster)
        _src_audio_codec = _probe_audio_codec(options.ffmpeg_path, input_path)
        _audio_copy = _src_audio_codec == "aac" and not options.preview_width

        base_filters = _build_base_video_filters(
            options.to_shorts,
            options.preview_width,
            upscale_width=frame_width if upscale_to_full_hd else None,
            upscale_height=frame_height if upscale_to_full_hd else None,
            blur_bg=use_blur_bg,
        )
        effect_config = (
            VideoEffectConfig(normalized_effect)
            if normalized_effect != "none"
            else None
        )
        _logo_dur = options.logo_display_duration
        logo_config = (
            LogoRenderConfig(
                path=str(Path(options.logo_path)),
                width_px=logo_width,
                x_px=logo_x,
                y_px=logo_y,
                opacity=logo_opacity_ratio,
                duration=_logo_dur if (_logo_dur or 0) > 0 else None,
            )
            if has_logo
            else None
        )
        intro_outro_config = (
            IntroOutroRenderConfig(
                duration=float(render_duration),
                channel_name=str(options.intro_outro_channel_name).strip(),
                video_width=frame_width,
                video_height=frame_height,
                hold_duration=max(0.1, float(options.intro_outro_hold_duration or 1.5)),
                bg_color=str(options.intro_outro_bg_color or "0x000000@0.55"),
                text_color=str(options.intro_outro_text_color or "white"),
            )
            if has_intro_outro and render_duration is not None
            else None
        )
        progress_bar_config = (
            ProgressBarRenderConfig(
                duration=float(render_duration),
                video_width=frame_width,
                video_height=frame_height,
            )
            if has_progress_bar and render_duration is not None
            else None
        )
        watermark_config = None
        if has_watermark:
            watermark_width, watermark_x, watermark_y = _watermark_overlay_geometry(
                frame_width,
                frame_height,
            )
            watermark_config = WatermarkRenderConfig(
                path=str(Path(options.watermark_logo_path)),
                width_px=watermark_width,
                x_px=watermark_x,
                y_px=watermark_y,
            )

        import logging as _logging
        _render_log = _logging.getLogger("youtube-script")

        def _run_render(
            subtitle_path: str | None = None,
            lower_third_path: str | None = None,
        ) -> None:
            subtitle_config = (
                SubtitleRenderConfig(subtitle_path) if subtitle_path else None
            )
            _lt_position = _lt_config_effective.position if _lt_config_effective else "bottom"
            _lt_band_h = (
                lower_third.lower_third_band_height(_lt_config_effective, frame_height)
                if _lt_config_effective and _lt_position == "top-center"
                else 0
            )
            lower_third_render_config = (
                LowerThirdRenderConfig(lower_third_path, position=_lt_position, band_h_px=_lt_band_h)
                if lower_third_path
                else None
            )
            filter_complex, extra_inputs = build_filter_complex(
                effect_config,
                intro_outro_config,
                progress_bar_config,
                watermark_config,
                logo_config,
                lower_third_render_config,
                subtitle_config,
                base_filters=base_filters,
                lower_third_duration=(
                    options.clip_duration
                    if options.clip_duration is not None
                    else options.subtitle_duration
                ),
                lower_third_interval=options.lower_third_interval,
                lower_third_display_duration=options.lower_third_display_duration,
                lower_third_y_offset_px=_lt_y_offset_px,
                shorts_blur_bg=use_blur_bg,
            )
            cmd = build_ffmpeg_command(
                str(input_path),
                str(output_path),
                filter_complex,
                extra_inputs,
                ffmpeg_path=options.ffmpeg_path,
                encode_audio=True,
                audio_copy=_audio_copy,
            )
            _render_log.info("FFmpeg cmd: %s", " ".join(cmd))
            try:
                runner(
                    cmd,
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            except subprocess.CalledProcessError as _exc:
                _render_log.error("FFmpeg stderr:\n%s", (_exc.stderr or "").strip())
                raise

        if has_subtitles and has_lower_third:
            assert _lt_config_effective is not None
            ass_content = subtitle_renderer.build_ass_file(
                subtitle_chunks,
                normalized_subtitle_style,
                frame_width,
                frame_height,
                frame_format,
            )
            with subtitle_renderer.temporary_ass_file(ass_content) as subtitle_path:
                with lower_third.temporary_lower_third_png(
                    _lt_config_effective,
                    frame_width,
                    frame_height,
                ) as lower_third_path:
                    _run_render(subtitle_path, lower_third_path)
        elif has_subtitles:
            ass_content = subtitle_renderer.build_ass_file(
                subtitle_chunks,
                normalized_subtitle_style,
                frame_width,
                frame_height,
                frame_format,
            )
            with subtitle_renderer.temporary_ass_file(ass_content) as subtitle_path:
                _run_render(subtitle_path=subtitle_path)
        elif has_lower_third:
            assert _lt_config_effective is not None
            with lower_third.temporary_lower_third_png(
                _lt_config_effective,
                frame_width,
                frame_height,
            ) as lower_third_path:
                _run_render(lower_third_path=lower_third_path)
        else:
            _run_render()
    except subprocess.CalledProcessError as error:
        # Remove the 0-byte output file left by FFmpeg on failure so it is not
        # mistakenly picked up as the downloaded source on the next attempt.
        try:
            if output_path.exists() and output_path.stat().st_size == 0:
                output_path.unlink()
        except OSError:
            pass
        raise RuntimeError(_called_process_message(error)) from error
    return output_path
