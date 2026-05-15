"""FFmpeg video rendering pipeline for creative variants."""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Sequence

from ..core import subtitle_renderer
from ..downloads import utils as download_utils


@dataclass(frozen=True)
class VideoRenderOptions:
    input_path: Path
    ffmpeg_path: str
    to_shorts: bool = False
    logo_path: str = ""
    logo_position: str = "center"
    logo_size_mode: str = "relative"
    logo_scale_percent: int = 58
    logo_opacity_percent: int = 100
    subtitle_chunks: Sequence[dict] | None = None
    subtitle_start: float = 0.0
    subtitle_duration: float | None = None
    subtitle_style: str = "impact"
    video_effect: str = "none"
    preview_width: int | None = None


def _normalize_logo_size_mode(value: str) -> str:
    return value if value in {"original", "relative"} else "relative"


def _build_video_filters(to_shorts: bool, video_effect: str, preview_width: int | None) -> List[str]:
    filters: List[str] = []
    if to_shorts:
        filters.append("scale=1080:1920:force_original_aspect_ratio=increase")
        filters.append("crop=1080:1920")
    effect_filter = subtitle_renderer.video_effect_filter(video_effect)
    if effect_filter:
        filters.append(effect_filter)
    if preview_width:
        width = max(240, min(1080, int(preview_width)))
        filters.append(f"scale={width}:-2")
    return filters


def _write_subtitle_file(
    subtitle_entries: Sequence[dict],
    *,
    subtitle_style: str,
    to_shorts: bool,
    preview_width: int | None,
) -> Path:
    canvas_mode = "shorts" if to_shorts else "landscape"
    ass_document = subtitle_renderer.build_ass_document(
        subtitle_entries,
        style=subtitle_style,
        canvas_mode=canvas_mode,
    )
    with tempfile.NamedTemporaryFile(
        "w",
        suffix=".ass",
        encoding="utf-8",
        delete=False,
    ) as subtitle_file:
        subtitle_file.write(ass_document)
        return Path(subtitle_file.name)


def _called_process_message(error: subprocess.CalledProcessError) -> str:
    details = (error.stderr or "").strip().splitlines()
    return details[-1] if details else "Le traitement du clip a échoué."


def render_video_variant(
    options: VideoRenderOptions,
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> Path:
    input_path = Path(options.input_path)
    has_logo = bool(options.logo_path)
    normalized_effect = subtitle_renderer.normalize_video_effect(options.video_effect)
    normalized_subtitle_style = subtitle_renderer.normalize_subtitle_style(
        options.subtitle_style
    )
    subtitle_entries = subtitle_renderer.build_subtitle_entries(
        options.subtitle_chunks or [],
        clip_start=options.subtitle_start,
        clip_duration=options.subtitle_duration,
    )
    has_subtitles = bool(subtitle_entries)
    has_preview_scale = bool(options.preview_width)
    if (
        not options.to_shorts
        and not has_logo
        and not has_subtitles
        and normalized_effect == "none"
        and not has_preview_scale
    ):
        return input_path

    normalized_logo_size_mode = _normalize_logo_size_mode(options.logo_size_mode)
    logo_scale_percent = max(20, min(80, int(options.logo_scale_percent)))
    logo_scale_ratio = logo_scale_percent / 100.0
    logo_opacity_ratio = download_utils.logo_opacity_ratio(options.logo_opacity_percent)

    output_path = download_utils.download_variant_output_path(
        input_path,
        options.to_shorts,
        has_logo,
        has_subtitles=has_subtitles,
        video_effect=normalized_effect,
        subtitle_style=normalized_subtitle_style,
    )
    if (
        not has_logo
        and output_path.exists()
        and output_path.stat().st_mtime >= input_path.stat().st_mtime
    ):
        return output_path

    cmd = [options.ffmpeg_path, "-y", "-i", str(input_path)]
    if has_logo:
        cmd.extend(["-i", str(Path(options.logo_path))])

    subtitle_path: Path | None = None
    try:
        video_filters = _build_video_filters(
            options.to_shorts,
            normalized_effect,
            options.preview_width,
        )
        subtitle_filter = ""
        if has_subtitles:
            subtitle_path = _write_subtitle_file(
                subtitle_entries,
                subtitle_style=normalized_subtitle_style,
                to_shorts=options.to_shorts,
                preview_width=options.preview_width,
            )
            escaped_path = subtitle_renderer.escape_ffmpeg_filter_path(
                str(subtitle_path)
            )
            subtitle_filter = f"subtitles=filename='{escaped_path}'"

        if has_logo:
            filter_parts: List[str] = []
            base_input = "[0:v]"
            if video_filters:
                filter_parts.append(f"[0:v]{','.join(video_filters)}[base]")
                base_input = "[base]"

            if normalized_logo_size_mode == "original":
                logo_filters = (
                    f"format=rgba,colorchannelmixer=aa={logo_opacity_ratio:.3f}"
                )
            else:
                logo_filters = (
                    f"scale=iw*{logo_scale_ratio:.3f}:-1,"
                    f"format=rgba,colorchannelmixer=aa={logo_opacity_ratio:.3f}"
                )
            overlay_y = download_utils.logo_overlay_y_expr(
                options.logo_position,
                margin=36,
            )
            filter_parts.append(f"[1:v]{logo_filters}[logoa]")
            if subtitle_filter:
                filter_parts.append(
                    f"{base_input}[logoa]overlay=(W-w)/2:{overlay_y}:format=auto[logoed]"
                )
                filter_parts.append(f"[logoed]{subtitle_filter}[outv]")
            else:
                filter_parts.append(
                    f"{base_input}[logoa]overlay=(W-w)/2:{overlay_y}:format=auto[outv]"
                )
            cmd.extend(["-filter_complex", ";".join(filter_parts), "-map", "[outv]"])
        else:
            if subtitle_filter:
                video_filters.append(subtitle_filter)
            cmd.extend(["-vf", ",".join(video_filters), "-map", "0:v:0"])

        cmd.extend(
            [
                "-map",
                "0:a?",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "20",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-movflags",
                "+faststart",
                str(output_path),
            ]
        )
        runner(
            cmd,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        raise RuntimeError(_called_process_message(error)) from error
    finally:
        if subtitle_path is not None:
            subtitle_path.unlink(missing_ok=True)
    return output_path
