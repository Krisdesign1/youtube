"""Subtitle and video effect helpers for burned-in clip exports."""

from __future__ import annotations

import logging
import os
import platform
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, List

from PIL import Image, ImageDraw, ImageFont

DEFAULT_SUBTITLE_STYLE = "impact"
DEFAULT_VIDEO_EFFECT = "none"

MAX_WORDS_NORMAL = 7
MAX_WORDS_SHORT = 5
MAX_DURATION_SEC = 3.0
MIN_DURATION_SEC = 0.5
MAX_CHARS_NORMAL = 42
MAX_CHARS_SHORT = 26

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


@dataclass(frozen=True)
class AssStyle:
    fontname: str
    font_size: int
    primary_colour: str
    outline_colour: str
    back_colour: str
    bold: int
    outline: int
    shadow: int
    border_style: int
    alignment: int
    margin_v: int


_FONT_RATIOS: dict[str, dict[str, float]] = {
    "impact": {"16:9": 0.048, "9:16": 0.058},
    "modern": {"16:9": 0.040, "9:16": 0.050},
    "cinema": {"16:9": 0.034, "9:16": 0.042},
    "box": {"16:9": 0.038, "9:16": 0.046},
    "minimal": {"16:9": 0.028, "9:16": 0.034},
}

_MARGIN_V_RATIO = 0.08


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


def _escape_ass_event_text(text: object) -> str:
    raw = str(text).replace("\\N", "\n").replace("\r", "\n")
    lines = [escape_ass_text(line) for line in raw.split("\n")]
    return r"\N".join(line for line in lines if line)


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


def _wrap_chunk_words(words: list[str], max_chars: int) -> str:
    chunk_text = " ".join(words)
    if len(chunk_text) <= max_chars:
        return chunk_text
    split_at = max(1, len(words) // 2)
    return " ".join(words[:split_at]) + "\n" + " ".join(words[split_at:])


def rechunk_blocks(
    chunks: Iterable[dict],
    video_format: str,
    clip_start: float = 0.0,
    clip_duration: float | None = None,
) -> list[dict]:
    """
    Redecoupe les blocs YouTube en unites optimales pour l'affichage.

    Retourne des blocs relatifs au debut du clip avec les cles:
    ``text``, ``start`` et ``duration``.
    """
    is_short = video_format == "9:16"
    max_words = MAX_WORDS_SHORT if is_short else MAX_WORDS_NORMAL
    max_chars = MAX_CHARS_SHORT if is_short else MAX_CHARS_NORMAL
    window_start = max(0.0, float(clip_start or 0.0))
    window_duration = None if clip_duration is None else max(0.0, float(clip_duration))
    clip_end = (
        window_start + window_duration
        if window_duration is not None
        else float("inf")
    )

    result: list[dict] = []

    for block in chunks:
        text = escape_ass_text(str(block.get("text", ""))).strip()
        if not text:
            continue

        try:
            start = float(block.get("start", 0.0) or 0.0)
            duration = float(block.get("duration", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue

        if duration <= 0:
            continue
        if start + duration <= window_start:
            continue
        if start >= clip_end:
            break

        words = text.split()
        if not words:
            continue

        duration_per_word = duration / len(words)

        for index in range(0, len(words), max_words):
            chunk_words = words[index : index + max_words]
            chunk_start = start + index * duration_per_word
            chunk_duration = min(
                len(chunk_words) * duration_per_word,
                MAX_DURATION_SEC,
            )
            chunk_duration = max(chunk_duration, MIN_DURATION_SEC)
            chunk_end = chunk_start + chunk_duration

            if chunk_end <= window_start or chunk_start >= clip_end:
                continue

            chunk_start = max(chunk_start, window_start)
            chunk_end = min(chunk_end, clip_end)
            chunk_duration = max(chunk_end - chunk_start, MIN_DURATION_SEC)

            chunk_text = _wrap_chunk_words(chunk_words, max_chars)

            result.append(
                {
                    "text": chunk_text,
                    "start": round(chunk_start - window_start, 3),
                    "duration": round(chunk_duration, 3),
                }
            )

    result.sort(key=lambda item: item["start"])
    return _merge_close_blocks(
        result,
        max_words=max_words,
        max_chars=max_chars,
        max_duration=MAX_DURATION_SEC,
    )


def _merge_close_blocks(
    blocks: list[dict],
    gap_threshold: float = 0.1,
    max_words: int = MAX_WORDS_NORMAL,
    max_chars: int = MAX_CHARS_NORMAL,
    max_duration: float = MAX_DURATION_SEC,
) -> list[dict]:
    """Fusionne seulement les micro-blocs qui restent lisibles."""
    if not blocks:
        return blocks

    merged = [blocks[0].copy()]

    for current in blocks[1:]:
        previous = merged[-1]
        previous_end = previous["start"] + previous["duration"]
        gap = current["start"] - previous_end
        candidate_end = current["start"] + current["duration"]
        candidate_duration = candidate_end - previous["start"]
        candidate_words = f"{previous['text']} {current['text']}".replace("\n", " ").split()

        if (
            gap < gap_threshold
            and candidate_duration <= max_duration
            and len(candidate_words) <= max_words
        ):
            previous["duration"] = round(
                candidate_end - previous["start"],
                3,
            )
            previous["text"] = _wrap_chunk_words(candidate_words, max_chars)
        else:
            merged.append(current.copy())

    return merged


def build_subtitle_entries(
    transcript_chunks: Iterable[dict],
    clip_start: float,
    clip_duration: float | None,
    min_duration: float = MIN_DURATION_SEC,
    gap_threshold: float = 0.1,
    video_format: str = "16:9",
) -> List[dict]:
    """
    Compatibility wrapper returning the historical ``start``/``end`` shape.

    New rendering code should use :func:`rechunk_blocks`, which returns
    ``start``/``duration`` chunks ready for ASS generation.
    """
    blocks = rechunk_blocks(
        transcript_chunks,
        video_format,
        clip_start=clip_start,
        clip_duration=clip_duration,
    )
    if gap_threshold != 0.1:
        blocks = _merge_close_blocks(blocks, gap_threshold=gap_threshold)
    entries: List[dict] = []
    for block in blocks:
        start = float(block["start"])
        duration = max(float(block["duration"]), float(min_duration))
        entries.append(
            {
                "start": start,
                "end": round(start + duration, 3),
                "text": block["text"],
            }
        )
    return entries


def build_ass_style(
    design: str,
    video_width: int,
    video_height: int,
    video_format: str,
) -> AssStyle:
    """Calcule les parametres ASS relativement a la resolution finale."""
    _ = video_width
    normalized = normalize_subtitle_style(design)
    fmt = video_format if video_format in {"16:9", "9:16"} else "16:9"
    ratio = _FONT_RATIOS.get(normalized, _FONT_RATIOS["impact"])[fmt]
    font_size = max(12, int(video_height * ratio))
    margin_v = max(20, int(video_height * _MARGIN_V_RATIO))
    outline_px = max(2, int(font_size * 0.08))
    shadow_px = max(1, int(font_size * 0.04))

    styles: dict[str, AssStyle] = {
        "impact": AssStyle(
            fontname="Arial Black",
            font_size=font_size,
            primary_colour="&H00FFFFFF",
            outline_colour="&H00000000",
            back_colour="&H00000000",
            bold=1,
            outline=outline_px,
            shadow=shadow_px,
            border_style=1,
            alignment=2,
            margin_v=margin_v,
        ),
        "modern": AssStyle(
            fontname="Arial",
            font_size=font_size,
            primary_colour="&H00FFFFFF",
            outline_colour="&H00000000",
            back_colour="&H00000000",
            bold=1,
            outline=outline_px,
            shadow=0,
            border_style=1,
            alignment=2,
            margin_v=margin_v,
        ),
        "cinema": AssStyle(
            fontname="Georgia",
            font_size=font_size,
            primary_colour="&H00F0E8D0",
            outline_colour="&H00000000",
            back_colour="&H00000000",
            bold=0,
            outline=max(1, outline_px - 1),
            shadow=shadow_px,
            border_style=1,
            alignment=2,
            margin_v=margin_v,
        ),
        "box": AssStyle(
            fontname="Arial",
            font_size=font_size,
            primary_colour="&H00FFFFFF",
            outline_colour="&H00000000",
            back_colour="&HAA000000",
            bold=1,
            outline=0,
            shadow=0,
            border_style=4,
            alignment=2,
            margin_v=margin_v,
        ),
        "minimal": AssStyle(
            fontname="Arial",
            font_size=font_size,
            primary_colour="&H00FFFFFF",
            outline_colour="&H00000000",
            back_colour="&H00000000",
            bold=0,
            outline=1,
            shadow=0,
            border_style=1,
            alignment=2,
            margin_v=margin_v,
        ),
    }
    return styles.get(normalized, styles["impact"])


def ass_style_to_string(style: AssStyle) -> str:
    """Serialise un :class:`AssStyle` en ligne ``Style:`` valide."""
    return (
        "Style: Default,"
        f"{style.fontname},{style.font_size},"
        f"{style.primary_colour},&H00FFFFFF,"
        f"{style.outline_colour},{style.back_colour},"
        f"{style.bold},0,0,0,"
        "100,100,0,0,"
        f"{style.border_style},"
        f"{style.outline},{style.shadow},"
        f"{style.alignment},"
        f"10,10,{style.margin_v},1"
    )


def build_ass_header(video_width: int, video_height: int) -> str:
    """Genere l'en-tete ASS avec la resolution finale exacte."""
    return (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "WrapStyle: 0\n"
        f"PlayResX: {max(1, int(video_width))}\n"
        f"PlayResY: {max(1, int(video_height))}\n"
        "ScaledBorderAndShadow: yes\n"
        "YCbCr Matrix: TV.709\n"
        "\n"
    )


def build_ass_events(chunks: Iterable[dict]) -> str:
    """Genere la section ``[Events]`` depuis des chunks normalises."""
    lines = [
        "[Events]",
        "Format: Layer, Start, End, Style, Name, "
        "MarginL, MarginR, MarginV, Effect, Text",
    ]

    for chunk in chunks:
        try:
            start = float(chunk.get("start", 0.0) or 0.0)
            if "duration" in chunk:
                end = start + float(chunk.get("duration", 0.0) or 0.0)
            else:
                end = float(chunk.get("end", start + 1.0) or start + 1.0)
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        text = _escape_ass_event_text(chunk.get("text", ""))
        if not text:
            continue
        lines.append(
            f"Dialogue: 0,{ass_timestamp(start)},{ass_timestamp(end)},"
            f"Default,,0,0,0,,{text}"
        )

    return "\n".join(lines) + "\n"


def build_ass_file(
    chunks: Iterable[dict],
    design: str,
    video_width: int,
    video_height: int,
    video_format: str,
) -> str:
    """Construit le contenu complet du fichier ASS."""
    style = build_ass_style(design, video_width, video_height, video_format)
    sections = [
        build_ass_header(video_width, video_height),
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        ass_style_to_string(style),
        "",
        build_ass_events(chunks),
    ]
    return "\n".join(sections)


def build_ass_document(
    entries: Iterable[dict],
    *,
    style: str = DEFAULT_SUBTITLE_STYLE,
    canvas_mode: str = "landscape",
) -> str:
    """Compatibility wrapper for older callers."""
    vertical = canvas_mode == "shorts"
    video_width = 1080 if vertical else 1920
    video_height = 1920 if vertical else 1080
    video_format = "9:16" if vertical else "16:9"
    max_chars = MAX_CHARS_SHORT if vertical else MAX_CHARS_NORMAL
    chunks: list[dict] = []

    for entry in entries:
        try:
            start = float(entry.get("start", 0.0) or 0.0)
            if "duration" in entry:
                duration = float(entry.get("duration", 0.0) or 0.0)
            else:
                duration = float(entry.get("end", start + 1.0) or start + 1.0) - start
        except (TypeError, ValueError):
            continue
        text = wrap_subtitle_text(str(entry.get("text", "")), max_chars=max_chars)
        if not text or duration <= 0:
            continue
        chunks.append(
            {
                "text": text.replace(r"\N", "\n"),
                "start": start,
                "duration": duration,
            }
        )

    return build_ass_file(chunks, style, video_width, video_height, video_format)


@contextmanager
def temporary_ass_file(content: str, prefix: str = "yt_subs_") -> Iterator[str]:
    """
    Ecrit un fichier ASS temporaire et garantit sa suppression apres usage.
    """
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".ass", prefix=prefix)

    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as file_obj:
            file_obj.write(content)
        yield tmp_path
    finally:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            logging.getLogger(__name__).warning(
                "Impossible de supprimer le fichier ASS temporaire %s : %s",
                tmp_path,
                exc,
            )


def escape_ass_path(path: str) -> str:
    """Echappe un chemin pour le filtre ffmpeg ``subtitles=``."""
    value = str(path)
    if platform.system() == "Windows":
        value = value.replace("\\", "\\\\")
        value = value.replace(":", r"\:")
        return value

    value = value.replace("\\", "/")
    for char in (" ", "'", "[", "]", ",", ";"):
        value = value.replace(char, f"\\{char}")
    return value


def escape_ffmpeg_filter_path(path: str) -> str:
    """Compatibility alias for older renderer code."""
    return escape_ass_path(path)


def generate_subtitle_preview(
    frame_path: str,
    chunks: list[dict],
    timestamp: float,
    design: str,
    video_width: int,
    video_height: int,
    video_format: str,
    output_path: str | None = None,
) -> str:
    """Genere une image statique avec le sous-titre actif via PIL."""
    active = next(
        (
            chunk
            for chunk in chunks
            if chunk["start"] <= timestamp < chunk["start"] + chunk["duration"]
        ),
        None,
    )

    image = Image.open(frame_path).convert("RGBA")
    if image.size != (video_width, video_height):
        image = image.resize((video_width, video_height), Image.LANCZOS)

    if not active:
        output = output_path or _preview_output_path(frame_path, "_preview")
        image.convert("RGB").save(output, quality=85)
        return output

    style = build_ass_style(design, video_width, video_height, video_format)
    draw = ImageDraw.Draw(image)
    text = str(active["text"]).replace("\\N", "\n")
    font = _load_preview_font(style.fontname, style.font_size)

    bbox = draw.multiline_textbbox((0, 0), text, font=font, align="center")
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = max(10, (video_width - text_w) // 2)
    y = max(10, video_height - style.margin_v - text_h)

    if style.border_style == 4:
        pad = int(style.font_size * 0.2)
        draw.rectangle(
            [x - pad, y - pad, x + text_w + pad, y + text_h + pad],
            fill=(0, 0, 0, 170),
        )

    if style.outline > 0:
        for dx in range(-style.outline, style.outline + 1):
            for dy in range(-style.outline, style.outline + 1):
                if dx == 0 and dy == 0:
                    continue
                draw.multiline_text(
                    (x + dx, y + dy),
                    text,
                    font=font,
                    fill=(0, 0, 0, 255),
                    align="center",
                )

    r, g, b = _hex_ass_to_rgb(style.primary_colour)
    draw.multiline_text(
        (x, y),
        text,
        font=font,
        fill=(r, g, b, 255),
        align="center",
    )

    output = output_path or _preview_output_path(frame_path, "_subtitle_preview")
    image.convert("RGB").save(output, quality=85)
    return output


def _preview_output_path(frame_path: str, suffix: str) -> str:
    path = Path(frame_path)
    return str(path.with_name(f"{path.stem}{suffix}{path.suffix}"))


def _load_preview_font(fontname: str, font_size: int) -> ImageFont.ImageFont:
    candidates = [
        f"{fontname}.ttf",
        f"{fontname.replace(' ', '')}.ttf",
        "arial.ttf",
        "Arial.ttf",
        "DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, font_size)
        except OSError:
            continue
    return ImageFont.load_default()


def _hex_ass_to_rgb(ass_colour: str) -> tuple[int, int, int]:
    """Convertit une couleur ASS ``&HAABBGGRR`` en tuple RGB."""
    clean = ass_colour.replace("&H", "").replace("&h", "")
    if len(clean) == 8:
        b = int(clean[2:4], 16)
        g = int(clean[4:6], 16)
        r = int(clean[6:8], 16)
        return r, g, b
    return 255, 255, 255
