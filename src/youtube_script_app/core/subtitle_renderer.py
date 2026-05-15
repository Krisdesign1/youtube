"""Subtitle and video effect helpers for burned-in clip exports."""

from __future__ import annotations

from typing import Iterable, List

DEFAULT_SUBTITLE_STYLE = "impact"
DEFAULT_VIDEO_EFFECT = "none"

SUBTITLE_STYLES = {
    "impact",
    "modern",
    "cinema",
    "box",
    "minimal",
}

VIDEO_EFFECTS = {
    "none",
    "black_white",
    "contrast",
    "cinematic",
    "vintage",
}

VIDEO_EFFECT_FILTERS = {
    "none": "",
    "black_white": "hue=s=0",
    "contrast": "eq=contrast=1.25:brightness=-0.03:saturation=1.12",
    "cinematic": "eq=contrast=1.18:brightness=-0.05:saturation=0.82,vignette=PI/5",
    "vintage": "eq=contrast=1.08:saturation=0.72:gamma=1.05,noise=alls=6:allf=t+u",
}

VIDEO_EFFECT_SUFFIXES = {
    "black_white": "bw",
    "contrast": "contrast",
    "cinematic": "cinema",
    "vintage": "vintage",
}


def normalize_subtitle_style(value: object) -> str:
    style = str(value or "").strip().lower()
    return style if style in SUBTITLE_STYLES else DEFAULT_SUBTITLE_STYLE


def normalize_video_effect(value: object) -> str:
    effect = str(value or "").strip().lower()
    return effect if effect in VIDEO_EFFECTS else DEFAULT_VIDEO_EFFECT


def subtitle_style_suffix(value: object) -> str:
    return normalize_subtitle_style(value).replace("_", "-")


def video_effect_suffix(value: object) -> str:
    effect = normalize_video_effect(value)
    return VIDEO_EFFECT_SUFFIXES.get(effect, "")


def video_effect_filter(value: object) -> str:
    return VIDEO_EFFECT_FILTERS[normalize_video_effect(value)]


def has_video_effect(value: object) -> bool:
    return normalize_video_effect(value) != DEFAULT_VIDEO_EFFECT


def ass_timestamp(seconds: float) -> str:
    centiseconds = max(0, int(round(float(seconds) * 100)))
    total_seconds, cs = divmod(centiseconds, 100)
    minutes, sec = divmod(total_seconds, 60)
    hours, minute = divmod(minutes, 60)
    return f"{hours}:{minute:02d}:{sec:02d}.{cs:02d}"


def escape_ass_text(text: str) -> str:
    cleaned = str(text).replace("\n", " ").replace("\r", " ")
    cleaned = cleaned.replace("{", "(").replace("}", ")")
    return " ".join(cleaned.split())


def wrap_subtitle_text(text: str, max_chars: int = 34) -> str:
    words = escape_ass_text(text).split()
    if not words:
        return ""

    lines: List[str] = []
    current: List[str] = []
    current_len = 0
    for word in words:
        extra = len(word) + (1 if current else 0)
        if current and current_len + extra > max_chars and len(lines) < 1:
            lines.append(" ".join(current))
            current = [word]
            current_len = len(word)
        else:
            current.append(word)
            current_len += extra
    if current:
        lines.append(" ".join(current))
    return r"\N".join(lines[:2])


def build_subtitle_entries(
    transcript_chunks: Iterable[dict],
    clip_start: float,
    clip_duration: float | None,
) -> List[dict]:
    start = max(0.0, float(clip_start or 0.0))
    end = None if clip_duration is None else start + max(0.0, float(clip_duration))
    entries: List[dict] = []

    for chunk in transcript_chunks:
        text = escape_ass_text(str(chunk.get("text", "")))
        if not text:
            continue
        try:
            chunk_start = float(chunk.get("start", 0.0) or 0.0)
            chunk_duration = float(chunk.get("duration", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue

        fallback_duration = 2.5 if chunk_duration <= 0 else chunk_duration
        chunk_end = chunk_start + fallback_duration
        if end is not None and (chunk_start >= end or chunk_end <= start):
            continue
        if end is None and chunk_end <= start:
            continue

        entry_start = max(chunk_start, start) - start
        entry_end = chunk_end if end is None else min(chunk_end, end)
        entry_end = entry_end - start
        if entry_end - entry_start < 0.35:
            entry_end = entry_start + 0.35

        entries.append(
            {
                "start": entry_start,
                "end": entry_end,
                "text": text,
            }
        )

    return entries


def _style_values(style: str, canvas_mode: str) -> dict:
    vertical = canvas_mode == "shorts"
    font_size = {
        "impact": 82 if vertical else 56,
        "modern": 64 if vertical else 44,
        "cinema": 50 if vertical else 34,
        "box": 58 if vertical else 40,
        "minimal": 44 if vertical else 30,
    }[style]
    margin_v = {
        "impact": 210 if vertical else 76,
        "modern": 190 if vertical else 70,
        "cinema": 160 if vertical else 54,
        "box": 185 if vertical else 68,
        "minimal": 145 if vertical else 46,
    }[style]
    primary = {
        "impact": "&H00FFFFFF",
        "modern": "&H00FFFFFF",
        "cinema": "&H00DDF7FF",
        "box": "&H00FFFFFF",
        "minimal": "&H00F4F4F5",
    }[style]
    outline = {
        "impact": 8,
        "modern": 5,
        "cinema": 3,
        "box": 0,
        "minimal": 2,
    }[style]
    shadow = {
        "impact": 3,
        "modern": 2,
        "cinema": 1,
        "box": 0,
        "minimal": 1,
    }[style]
    border_style = 3 if style == "box" else 1
    back_colour = "&H99000000" if style == "box" else "&H66000000"
    font_name = "Arial Black" if style == "impact" else "Arial"
    return {
        "font_name": font_name,
        "font_size": font_size,
        "primary": primary,
        "outline": outline,
        "shadow": shadow,
        "border_style": border_style,
        "back_colour": back_colour,
        "margin_v": margin_v,
        "bold": -1 if style in {"impact", "modern", "box"} else 0,
    }


def build_ass_document(
    entries: Iterable[dict],
    *,
    style: str = DEFAULT_SUBTITLE_STYLE,
    canvas_mode: str = "landscape",
) -> str:
    normalized_style = normalize_subtitle_style(style)
    vertical = canvas_mode == "shorts"
    play_res_x = 1080 if vertical else 1920
    play_res_y = 1920 if vertical else 1080
    values = _style_values(normalized_style, "shorts" if vertical else "landscape")
    max_chars = 26 if vertical else 42

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        f"PlayResX: {play_res_x}",
        f"PlayResY: {play_res_y}",
        "",
        "[V4+ Styles]",
        (
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
            "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
            "MarginL, MarginR, MarginV, Encoding"
        ),
        (
            "Style: Default,"
            f"{values['font_name']},{values['font_size']},{values['primary']},"
            "&H000000FF,&H00000000,"
            f"{values['back_colour']},{values['bold']},0,0,0,100,100,0,0,"
            f"{values['border_style']},{values['outline']},{values['shadow']},2,"
            f"72,72,{values['margin_v']},1"
        ),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    for entry in entries:
        text = wrap_subtitle_text(str(entry.get("text", "")), max_chars=max_chars)
        if not text:
            continue
        try:
            start = float(entry.get("start", 0.0) or 0.0)
            end = float(entry.get("end", start + 1.0) or start + 1.0)
        except (TypeError, ValueError):
            continue
        if end <= start:
            end = start + 1.0
        lines.append(
            f"Dialogue: 0,{ass_timestamp(start)},{ass_timestamp(end)},"
            f"Default,,0,0,0,,{text}"
        )

    return "\n".join(lines) + "\n"


def escape_ffmpeg_filter_path(path: str) -> str:
    value = str(path)
    replacements = {
        "\\": r"\\",
        ":": r"\:",
        "'": r"\'",
        ",": r"\,",
        "[": r"\[",
        "]": r"\]",
        ";": r"\;",
    }
    for source, target in replacements.items():
        value = value.replace(source, target)
    return value
