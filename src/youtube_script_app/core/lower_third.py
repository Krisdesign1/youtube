"""Lower third PNG generation helpers."""

from __future__ import annotations

import logging
import os
import re
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from PIL import Image, ImageDraw, ImageFont

DEFAULT_BG_COLOR = "#F5F0E8"
DEFAULT_ACCENT_COLOR = "#E85D3A"
DEFAULT_TEXT_COLOR = "#111827"
DEFAULT_DISPLAY_INTERVAL_SECONDS = 20
MIN_DISPLAY_INTERVAL_SECONDS = 10
MAX_DISPLAY_INTERVAL_SECONDS = 30
DEFAULT_DISPLAY_DURATION_SECONDS = 4
MIN_DISPLAY_DURATION_SECONDS = 2
MAX_DISPLAY_DURATION_SECONDS = 30

# Render at 2× then downscale — eliminates PIL's jagged text edges
_RENDER_SCALE = 2

_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


@dataclass(frozen=True)
class LowerThirdConfig:
    channel_name: str
    tagline: str = ""
    bg_color: tuple[int, int, int, int] = (245, 240, 232, 220)
    text_color: tuple[int, int, int, int] = (17, 24, 39, 255)
    accent_color: tuple[int, int, int, int] = (232, 93, 58, 255)
    font_size_ratio: float = 0.042
    height_ratio: float = 0.14
    show_subscribe: bool = True
    position: str = "bottom"  # "bottom" or "top"


def normalize_hex_color(value: object, default: str) -> str:
    color = str(value or "").strip()
    return color if _HEX_COLOR_RE.match(color) else default


def rgba_from_hex(value: object, *, alpha: int = 255, default: str = "#FFFFFF") -> tuple[int, int, int, int]:
    color = normalize_hex_color(value, default).lstrip("#")
    return (
        int(color[0:2], 16),
        int(color[2:4], 16),
        int(color[4:6], 16),
        max(0, min(255, int(alpha))),
    )


def contrast_text_hex(bg_hex: object) -> str:
    red, green, blue, _alpha = rgba_from_hex(
        bg_hex,
        default=DEFAULT_BG_COLOR,
    )
    luminance = (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255
    return "#111827" if luminance >= 0.55 else "#FFFFFF"


def config_from_hex(
    *,
    channel_name: str,
    tagline: str = "",
    bg_color: object = DEFAULT_BG_COLOR,
    accent_color: object = DEFAULT_ACCENT_COLOR,
    show_subscribe: bool = True,
    video_format: str = "16:9",
    position: str = "bottom",
) -> LowerThirdConfig:
    normalized_bg = normalize_hex_color(bg_color, DEFAULT_BG_COLOR)
    normalized_accent = normalize_hex_color(accent_color, DEFAULT_ACCENT_COLOR)
    normalized_position = position if position in {"bottom", "top"} else "bottom"
    return LowerThirdConfig(
        channel_name=" ".join(str(channel_name or "").split()),
        tagline=" ".join(str(tagline or "").split()),
        bg_color=rgba_from_hex(normalized_bg, alpha=220, default=DEFAULT_BG_COLOR),
        text_color=rgba_from_hex(
            contrast_text_hex(normalized_bg),
            alpha=255,
            default=DEFAULT_TEXT_COLOR,
        ),
        accent_color=rgba_from_hex(
            normalized_accent,
            alpha=255,
            default=DEFAULT_ACCENT_COLOR,
        ),
        font_size_ratio=0.038 if video_format == "9:16" else 0.042,
        height_ratio=0.12 if video_format == "9:16" else 0.14,
        show_subscribe=bool(show_subscribe),
        position=normalized_position,
    )


def _draw_gradient_band(
    image: Image.Image,
    band_y: int,
    width: int,
    height: int,
    color: tuple[int, int, int, int],
    *,
    fade_start: float = 0.60,
) -> None:
    """Horizontal gradient band: solid on the left, fading to transparent on the right."""
    band_height = height - band_y
    if band_height <= 0:
        return
    r, g, b, a = color
    src_w = 400
    fade_px = int(src_w * fade_start)
    src = Image.new("RGBA", (src_w, 1))
    for x in range(src_w):
        if x < fade_px:
            src.putpixel((x, 0), (r, g, b, a))
        else:
            t = (x - fade_px) / (src_w - fade_px)
            src.putpixel((x, 0), (r, g, b, max(0, int(a * (1.0 - t)))))
    gradient = src.resize((width, band_height), Image.LANCZOS)
    image.alpha_composite(gradient, (0, band_y))


def generate_lower_third(
    config: LowerThirdConfig,
    video_width: int,
    video_height: int,
    output_path: str,
) -> str:
    """Generate a transparent PNG matching the final video resolution."""
    s = _RENDER_SCALE
    width = max(1, int(video_width))
    height = max(1, int(video_height))
    render_width = width * s
    render_height = height * s

    image = Image.new("RGBA", (render_width, render_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    band_h = max(48 * s, int(render_height * config.height_ratio))
    top_position = config.position == "top"
    band_y = 0 if top_position else render_height - band_h
    band_end = band_h if top_position else render_height
    font_size = max(14 * s, int(render_height * config.font_size_ratio))
    tagline_size = max(10 * s, int(font_size * 0.55))
    padding = max(16 * s, int(render_width * 0.03))

    _draw_gradient_band(image, band_y, render_width, band_end, config.bg_color)

    accent_w = max(4 * s, int(render_width * 0.005))
    accent_y_pad = max(8 * s, int(band_h * 0.16))
    draw.rectangle(
        [padding, band_y + accent_y_pad, padding + accent_w, band_end - accent_y_pad],
        fill=config.accent_color,
    )

    font_bold = _load_font(["Arial Bold.ttf", "Arial-Bold.ttf"], font_size)
    font_tagline = _load_font(["Arial.ttf", "Arial Unicode.ttf"], tagline_size)

    text_x = padding + accent_w + max(12 * s, int(padding * 0.6))
    max_text_width = render_width - text_x - padding

    subscribe_box: tuple[int, int, int, int] | None = None
    subscribe_text = "Abonnez-vous"
    subscribe_font = _load_font(
        ["Arial.ttf", "Arial Unicode.ttf"], max(11 * s, int(font_size * 0.58))
    )
    if config.show_subscribe:
        btn_bbox = draw.textbbox((0, 0), subscribe_text, font=subscribe_font)
        btn_text_w = btn_bbox[2] - btn_bbox[0]
        btn_text_h = btn_bbox[3] - btn_bbox[1]
        btn_pad_x = max(10 * s, int(font_size * 0.42))
        btn_pad_y = max(6 * s, int(font_size * 0.24))
        btn_x2 = render_width - padding
        btn_x1 = btn_x2 - btn_text_w - (btn_pad_x * 2)
        btn_y1 = band_y + ((band_h - btn_text_h - (btn_pad_y * 2)) // 2)
        btn_y2 = btn_y1 + btn_text_h + (btn_pad_y * 2)
        subscribe_box = (btn_x1, btn_y1, btn_x2, btn_y2)
        max_text_width = max(80 * s, btn_x1 - text_x - padding)

    title = _fit_text(draw, config.channel_name, font_bold, max_text_width)
    tagline = _fit_text(draw, config.tagline, font_tagline, max_text_width)
    title_bbox = draw.textbbox((0, 0), title, font=font_bold)
    title_h = title_bbox[3] - title_bbox[1]
    tagline_h = 0
    if tagline:
        tagline_bbox = draw.textbbox((0, 0), tagline, font=font_tagline)
        tagline_h = tagline_bbox[3] - tagline_bbox[1]
    gap = max(4 * s, int(font_size * 0.16)) if tagline else 0
    text_block_h = title_h + gap + tagline_h
    text_y = band_y + ((band_h - text_block_h) // 2)

    shadow_offset = max(2 * s, int(font_size * 0.06))
    shadow_color = (0, 0, 0, 120)
    draw.text(
        (text_x + shadow_offset, text_y + shadow_offset),
        title,
        font=font_bold,
        fill=shadow_color,
    )
    draw.text((text_x, text_y), title, font=font_bold, fill=config.text_color)

    if tagline:
        tagline_y = text_y + title_h + gap
        muted = (config.text_color[0], config.text_color[1], config.text_color[2], 210)
        draw.text(
            (text_x + shadow_offset, tagline_y + shadow_offset),
            tagline,
            font=font_tagline,
            fill=shadow_color,
        )
        draw.text((text_x, tagline_y), tagline, font=font_tagline, fill=muted)

    if subscribe_box is not None:
        btn_x1, btn_y1, btn_x2, btn_y2 = subscribe_box
        draw.rounded_rectangle(
            [btn_x1, btn_y1, btn_x2, btn_y2],
            radius=max(8 * s, (btn_y2 - btn_y1) // 2),
            fill=config.accent_color,
        )
        btn_bbox = draw.textbbox((0, 0), subscribe_text, font=subscribe_font)
        btn_text_w = btn_bbox[2] - btn_bbox[0]
        btn_text_h = btn_bbox[3] - btn_bbox[1]
        draw.text(
            (
                btn_x1 + ((btn_x2 - btn_x1 - btn_text_w) // 2),
                btn_y1 + ((btn_y2 - btn_y1 - btn_text_h) // 2),
            ),
            subscribe_text,
            font=subscribe_font,
            fill=(255, 255, 255, 255),
        )

    final = image.resize((width, height), Image.LANCZOS)
    final.save(output_path, format="PNG")
    return output_path


@contextmanager
def temporary_lower_third_png(
    config: LowerThirdConfig,
    video_width: int,
    video_height: int,
    prefix: str = "yt_lower_third_",
) -> Iterator[str]:
    fd, path = tempfile.mkstemp(suffix=".png", prefix=prefix)
    os.close(fd)
    try:
        generate_lower_third(config, video_width, video_height, path)
        yield path
    finally:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            logging.getLogger(__name__).warning(
                "Impossible de supprimer le PNG lower third temporaire %s : %s",
                path,
                exc,
            )


def _load_font(candidates: list[str], size: int) -> ImageFont.ImageFont:
    paths = [
        *candidates,
        "DejaVuSans-Bold.ttf",
        # macOS
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Black.ttf",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNSText.ttf",
        # Linux — Debian/Ubuntu
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        # Linux — Fedora/RHEL
        "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
        # Windows
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
    ]
    for candidate in paths:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> str:
    clean = " ".join(str(text or "").split())
    if not clean:
        return ""
    if draw.textbbox((0, 0), clean, font=font)[2] <= max_width:
        return clean

    ellipsis = "..."
    result = clean
    while result:
        candidate = f"{result.rstrip()}{ellipsis}"
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] <= max_width:
            return candidate
        result = result[:-1]
    return ellipsis
