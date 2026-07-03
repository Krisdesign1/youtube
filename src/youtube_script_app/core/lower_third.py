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
    position: str = "bottom"  # "bottom" | "top" | "top-center"
    title_scale: float = 1.0       # font size multiplier for channel name
    tagline_scale: float = 1.0     # font size multiplier for tagline
    subscribe_text: str = "Abonnez-vous"  # customizable CTA button text
    vertical_align: str = "top"    # "top" | "center" | "bottom" within pillarbox


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
    bg_alpha: int | None = None,
    title_scale: float = 1.0,
    tagline_scale: float = 1.0,
    subscribe_text: str = "Abonnez-vous",
    vertical_align: str = "top",
) -> LowerThirdConfig:
    normalized_bg = normalize_hex_color(bg_color, DEFAULT_BG_COLOR)
    normalized_accent = normalize_hex_color(accent_color, DEFAULT_ACCENT_COLOR)
    normalized_position = position if position in {"bottom", "top", "top-center"} else "bottom"
    is_top_center = normalized_position == "top-center"
    _bg_alpha = max(0, min(255, int(bg_alpha))) if bg_alpha is not None else 220
    return LowerThirdConfig(
        channel_name=" ".join(str(channel_name or "").split()),
        tagline=" ".join(str(tagline or "").split()),
        bg_color=rgba_from_hex(normalized_bg, alpha=_bg_alpha, default=DEFAULT_BG_COLOR),
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
        font_size_ratio=0.034 if is_top_center and video_format == "9:16" else (0.038 if video_format == "9:16" else 0.042),
        height_ratio=0.20 if is_top_center and video_format == "9:16" else (0.16 if is_top_center else (0.12 if video_format == "9:16" else 0.14)),
        show_subscribe=bool(show_subscribe),
        position=normalized_position,
        title_scale=max(0.5, min(2.0, float(title_scale))),
        tagline_scale=max(0.5, min(2.0, float(tagline_scale))),
        subscribe_text=str(subscribe_text or "Abonnez-vous").strip() or "Abonnez-vous",
        vertical_align=vertical_align if vertical_align in {"top", "center", "bottom"} else "top",
    )


def lower_third_band_height(config: LowerThirdConfig, video_height: int) -> int:
    """Return the pixel height of the lower third band for a given video height."""
    return max(48, int(video_height * config.height_ratio))


def _draw_symmetric_gradient_band(
    image: Image.Image,
    band_y: int,
    width: int,
    height: int,
    color: tuple[int, int, int, int],
    *,
    solid_fraction: float = 0.60,
) -> None:
    """Symmetric gradient: fades from both edges, solid in the center."""
    band_height = height - band_y
    if band_height <= 0:
        return
    r, g, b, a = color
    src_w = 400
    fade_w = max(1, int(src_w * (1.0 - solid_fraction) / 2))
    src = Image.new("RGBA", (src_w, 1))
    for x in range(src_w):
        if x < fade_w:
            t = 1.0 - (x / fade_w)
            src.putpixel((x, 0), (r, g, b, max(0, int(a * (1.0 - t)))))
        elif x > src_w - fade_w:
            t = (x - (src_w - fade_w)) / fade_w
            src.putpixel((x, 0), (r, g, b, max(0, int(a * (1.0 - t)))))
        else:
            src.putpixel((x, 0), (r, g, b, a))
    gradient = src.resize((width, band_height), Image.LANCZOS)
    image.alpha_composite(gradient, (0, band_y))


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
    """Generate a transparent PNG matching the final video resolution.

    For position='top-center', generates a band-height PNG (not full-frame)
    to enable y-slide animation in ffmpeg.
    """
    if config.position == "top-center":
        return _generate_top_center_lower_third(config, video_width, video_height, output_path)
    return _generate_standard_lower_third(config, video_width, video_height, output_path)


def generate_lower_third_image(
    config: LowerThirdConfig,
    video_width: int,
    video_height: int,
) -> "Image.Image":
    """Return a PIL Image of the lower third (no disk I/O — used for live preview)."""
    if config.position == "top-center":
        return _render_top_center_lower_third_image(config, video_width, video_height)
    return _render_standard_lower_third_image(config, video_width, video_height)


def _render_top_center_lower_third_image(
    config: LowerThirdConfig,
    video_width: int,
    video_height: int,
) -> Image.Image:
    """Render the top-center band as a PIL Image (band height only, not full frame)."""
    s = _RENDER_SCALE
    width = max(1, int(video_width))
    band_h = lower_third_band_height(config, max(1, int(video_height)))
    render_width = width * s
    render_band_h = band_h * s

    image = Image.new("RGBA", (render_width, render_band_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    _draw_symmetric_gradient_band(image, 0, render_width, render_band_h, config.bg_color, solid_fraction=0.90)

    font_size = max(14 * s, int(render_band_h * 0.28 * config.title_scale))
    tagline_size = max(10 * s, int(render_band_h * 0.28 * config.title_scale * 0.58 * config.tagline_scale))
    subscribe_size = max(10 * s, int(font_size * 0.55))
    padding_x = max(20 * s, int(render_width * 0.06))
    max_text_width = render_width - padding_x * 2

    font_bold = _load_font(["Arial Bold.ttf", "Arial-Bold.ttf"], font_size)
    font_tagline = _load_font(["Arial.ttf", "Arial Unicode.ttf"], tagline_size)
    font_subscribe = _load_font(["Arial.ttf", "Arial Unicode.ttf"], subscribe_size)
    subscribe_text = config.subscribe_text or "Abonnez-vous"

    title = _fit_text(draw, config.channel_name, font_bold, max_text_width)
    tagline = _fit_text(draw, config.tagline, font_tagline, max_text_width)

    title_bbox = draw.textbbox((0, 0), title, font=font_bold)
    title_h = title_bbox[3] - title_bbox[1]
    title_w = title_bbox[2] - title_bbox[0]

    tagline_h = 0
    if tagline:
        tb = draw.textbbox((0, 0), tagline, font=font_tagline)
        tagline_h = tb[3] - tb[1]

    underline_h = max(3 * s, int(font_size * 0.08))
    underline_gap = max(4 * s, int(font_size * 0.12))
    underline_w = min(title_w + padding_x, int(render_width * 0.55))

    btn_h = 0
    btn_text_w = 0
    btn_pad_x = max(10 * s, int(font_size * 0.40))
    btn_pad_y = max(5 * s, int(font_size * 0.20))
    if config.show_subscribe:
        bb = draw.textbbox((0, 0), subscribe_text, font=font_subscribe)
        btn_text_w = bb[2] - bb[0]
        btn_text_h = bb[3] - bb[1]
        btn_h = btn_text_h + btn_pad_y * 2

    gap_tagline = max(4 * s, int(font_size * 0.14)) if tagline else 0
    gap_btn = max(6 * s, int(font_size * 0.18)) if config.show_subscribe else 0
    underline_total = underline_gap + underline_h + underline_gap

    total_h = title_h + underline_total + tagline_h + gap_tagline + gap_btn + btn_h
    if not tagline:
        total_h -= gap_tagline
    if not config.show_subscribe:
        total_h -= gap_btn

    y = max(max(4 * s, render_band_h // 20), (render_band_h - total_h) // 2)

    title_x = (render_width - title_w) // 2
    shadow_off = max(s, int(font_size * 0.04))
    draw.text((title_x + shadow_off, y + shadow_off), title, font=font_bold, fill=(0, 0, 0, 80))
    draw.text((title_x, y), title, font=font_bold, fill=config.text_color)
    y += title_h + underline_gap

    ul_x = (render_width - underline_w) // 2
    draw.rectangle([ul_x, y, ul_x + underline_w, y + underline_h], fill=config.accent_color)
    y += underline_h + underline_gap

    if tagline:
        tb = draw.textbbox((0, 0), tagline, font=font_tagline)
        tagline_w = tb[2] - tb[0]
        tagline_x = (render_width - tagline_w) // 2
        muted = (config.text_color[0], config.text_color[1], config.text_color[2], 210)
        draw.text((tagline_x, y), tagline, font=font_tagline, fill=muted)
        y += tagline_h + gap_tagline

    if config.show_subscribe:
        y += gap_btn
        btn_w = btn_text_w + btn_pad_x * 2
        btn_x1 = (render_width - btn_w) // 2
        btn_x2 = btn_x1 + btn_w
        btn_y1 = y
        btn_y2 = btn_y1 + btn_h
        draw.rounded_rectangle(
            [btn_x1, btn_y1, btn_x2, btn_y2],
            radius=max(8 * s, (btn_y2 - btn_y1) // 2),
            fill=config.accent_color,
        )
        bb = draw.textbbox((0, 0), subscribe_text, font=font_subscribe)
        bw = bb[2] - bb[0]
        bh = bb[3] - bb[1]
        draw.text(
            (btn_x1 + (btn_w - bw) // 2, btn_y1 + (btn_h - bh) // 2),
            subscribe_text, font=font_subscribe, fill=(255, 255, 255, 255),
        )

    return image.resize((width, band_h), Image.LANCZOS)


def _generate_top_center_lower_third(
    config: LowerThirdConfig,
    video_width: int,
    video_height: int,
    output_path: str,
) -> str:
    """Centered-top variant: band-height PNG with symmetric gradient and vertical stacked layout."""
    try:
        _render_top_center_lower_third_image(config, video_width, video_height).save(output_path, format="PNG")
    except (OSError, PermissionError) as exc:
        raise RuntimeError(f"Impossible de sauvegarder le lower third : {output_path} — {exc}") from exc
    return output_path


def _render_standard_lower_third_image(
    config: LowerThirdConfig,
    video_width: int,
    video_height: int,
) -> Image.Image:
    """Standard lower third: full-frame PIL Image with left-aligned gradient band."""
    return _generate_standard_lower_third_image(config, video_width, video_height)


def _generate_standard_lower_third_image(
    config: LowerThirdConfig,
    video_width: int,
    video_height: int,
) -> Image.Image:
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

    draw.text((text_x, text_y), title, font=font_bold, fill=config.text_color)

    if tagline:
        tagline_y = text_y + title_h + gap
        muted = (config.text_color[0], config.text_color[1], config.text_color[2], 210)
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
            subscribe_text, font=subscribe_font, fill=(255, 255, 255, 255),
        )

    return image.resize((width, height), Image.LANCZOS)


def _generate_standard_lower_third(
    config: LowerThirdConfig,
    video_width: int,
    video_height: int,
    output_path: str,
) -> str:
    """Standard lower third: full-frame PNG with left-aligned gradient band."""
    _generate_standard_lower_third_image(config, video_width, video_height).save(output_path, format="PNG")
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
