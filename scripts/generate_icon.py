"""Generate application icons from standard-library drawing code."""

from __future__ import annotations

import math
import shutil
import struct
import subprocess
import zlib
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
ASSETS_DIR = ROOT_DIR / "assets"
ICONSET_DIR = ASSETS_DIR / "app.iconset"
MASTER_PNG = ASSETS_DIR / "app-icon-1024.png"
ICNS_PATH = ASSETS_DIR / "app.icns"
ICO_PATH = ASSETS_DIR / "app.ico"
SCALE = 1
MASTER_SIZE = 1024
CANVAS_SIZE = MASTER_SIZE * SCALE

Color = tuple[int, int, int, int]


def blend_pixel(dst: Color, src: Color) -> Color:
    sr, sg, sb, sa = src
    if sa <= 0:
        return dst
    if sa >= 255:
        return src
    dr, dg, db, da = dst
    src_a = sa / 255.0
    dst_a = da / 255.0
    out_a = src_a + dst_a * (1.0 - src_a)
    if out_a <= 0:
        return 0, 0, 0, 0
    r = int(round((sr * src_a + dr * dst_a * (1.0 - src_a)) / out_a))
    g = int(round((sg * src_a + dg * dst_a * (1.0 - src_a)) / out_a))
    b = int(round((sb * src_a + db * dst_a * (1.0 - src_a)) / out_a))
    a = int(round(out_a * 255))
    return r, g, b, a


def new_canvas(size: int) -> list[list[Color]]:
    return [[(0, 0, 0, 0) for _ in range(size)] for _ in range(size)]


def set_pixel(canvas: list[list[Color]], x: int, y: int, color: Color) -> None:
    if 0 <= y < len(canvas) and 0 <= x < len(canvas[y]):
        canvas[y][x] = blend_pixel(canvas[y][x], color)


def rounded_rect_mask(x: int, y: int, w: int, h: int, radius: int, px: int, py: int) -> bool:
    if px < x or px >= x + w or py < y or py >= y + h:
        return False
    left = x + radius
    right = x + w - radius - 1
    top = y + radius
    bottom = y + h - radius - 1
    if left <= px <= right or top <= py <= bottom:
        return True
    cx = left if px < left else right
    cy = top if py < top else bottom
    return (px - cx) ** 2 + (py - cy) ** 2 <= radius**2


def draw_rounded_rect(
    canvas: list[list[Color]],
    x: int,
    y: int,
    w: int,
    h: int,
    radius: int,
    color: Color,
) -> None:
    for py in range(y, y + h):
        for px in range(x, x + w):
            if rounded_rect_mask(x, y, w, h, radius, px, py):
                set_pixel(canvas, px, py, color)


def draw_gradient_rounded_rect(
    canvas: list[list[Color]],
    x: int,
    y: int,
    w: int,
    h: int,
    radius: int,
    top_left: tuple[int, int, int],
    bottom_right: tuple[int, int, int],
) -> None:
    for py in range(y, y + h):
        vertical = (py - y) / max(1, h - 1)
        for px in range(x, x + w):
            if not rounded_rect_mask(x, y, w, h, radius, px, py):
                continue
            horizontal = (px - x) / max(1, w - 1)
            t = (vertical * 0.62) + (horizontal * 0.38)
            r = int(round(top_left[0] * (1 - t) + bottom_right[0] * t))
            g = int(round(top_left[1] * (1 - t) + bottom_right[1] * t))
            b = int(round(top_left[2] * (1 - t) + bottom_right[2] * t))
            set_pixel(canvas, px, py, (r, g, b, 255))


def point_in_polygon(x: int, y: int, points: list[tuple[int, int]]) -> bool:
    inside = False
    j = len(points) - 1
    for i, point in enumerate(points):
        xi, yi = point
        xj, yj = points[j]
        if ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / max(1, yj - yi) + xi
        ):
            inside = not inside
        j = i
    return inside


def draw_polygon(canvas: list[list[Color]], points: list[tuple[int, int]], color: Color) -> None:
    min_x = max(0, min(x for x, _ in points))
    max_x = min(len(canvas[0]) - 1, max(x for x, _ in points))
    min_y = max(0, min(y for _, y in points))
    max_y = min(len(canvas) - 1, max(y for _, y in points))
    for y in range(min_y, max_y + 1):
        for x in range(min_x, max_x + 1):
            if point_in_polygon(x, y, points):
                set_pixel(canvas, x, y, color)


def draw_circle(canvas: list[list[Color]], cx: int, cy: int, radius: int, color: Color) -> None:
    r2 = radius * radius
    for y in range(cy - radius, cy + radius + 1):
        for x in range(cx - radius, cx + radius + 1):
            if (x - cx) ** 2 + (y - cy) ** 2 <= r2:
                set_pixel(canvas, x, y, color)


def draw_line(
    canvas: list[list[Color]],
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    thickness: int,
    color: Color,
) -> None:
    radius = max(1, thickness // 2)
    length = max(abs(x2 - x1), abs(y2 - y1), 1)
    for step in range(length + 1):
        t = step / length
        x = int(round(x1 * (1 - t) + x2 * t))
        y = int(round(y1 * (1 - t) + y2 * t))
        draw_circle(canvas, x, y, radius, color)


def downsample_box(canvas: list[list[Color]], target_size: int) -> list[list[Color]]:
    source_size = len(canvas)
    factor = source_size // target_size
    result = new_canvas(target_size)
    for y in range(target_size):
        for x in range(target_size):
            totals = [0, 0, 0, 0]
            for yy in range(y * factor, (y + 1) * factor):
                for xx in range(x * factor, (x + 1) * factor):
                    pixel = canvas[yy][xx]
                    for channel in range(4):
                        totals[channel] += pixel[channel]
            area = factor * factor
            result[y][x] = tuple(int(round(value / area)) for value in totals)  # type: ignore[assignment]
    return result


def resize_nearest(canvas: list[list[Color]], target_size: int) -> list[list[Color]]:
    source_size = len(canvas)
    result = new_canvas(target_size)
    for y in range(target_size):
        source_y = min(source_size - 1, int(y * source_size / target_size))
        for x in range(target_size):
            source_x = min(source_size - 1, int(x * source_size / target_size))
            result[y][x] = canvas[source_y][source_x]
    return result


def write_png(path: Path, canvas: list[list[Color]]) -> None:
    height = len(canvas)
    width = len(canvas[0])
    raw_rows = []
    for row in canvas:
        raw_rows.append(b"\x00" + b"".join(bytes(pixel) for pixel in row))
    raw = b"".join(raw_rows)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, level=9))
    png += chunk(b"IEND", b"")
    path.write_bytes(png)


def build_master() -> list[list[Color]]:
    canvas = new_canvas(CANVAS_SIZE)
    s = SCALE

    draw_rounded_rect(canvas, 92 * s, 108 * s, 840 * s, 840 * s, 228 * s, (11, 31, 49, 70))
    draw_gradient_rounded_rect(
        canvas,
        84 * s,
        68 * s,
        856 * s,
        856 * s,
        220 * s,
        (20, 184, 166),
        (37, 99, 235),
    )

    draw_rounded_rect(canvas, 208 * s, 218 * s, 608 * s, 588 * s, 92 * s, (255, 255, 255, 242))
    draw_rounded_rect(canvas, 258 * s, 288 * s, 508 * s, 268 * s, 66 * s, (15, 23, 42, 236))
    draw_circle(canvas, 512 * s, 422 * s, 96 * s, (20, 184, 166, 255))
    draw_polygon(
        canvas,
        [
            (484 * s, 360 * s),
            (484 * s, 484 * s),
            (590 * s, 422 * s),
        ],
        (255, 255, 255, 255),
    )

    line_color = (37, 99, 235, 235)
    muted_line = (15, 23, 42, 92)
    draw_line(canvas, 282 * s, 618 * s, 742 * s, 618 * s, 28 * s, line_color)
    draw_line(canvas, 282 * s, 674 * s, 660 * s, 674 * s, 24 * s, muted_line)
    draw_line(canvas, 282 * s, 728 * s, 565 * s, 728 * s, 24 * s, muted_line)

    draw_line(canvas, 700 * s, 674 * s, 700 * s, 754 * s, 28 * s, (20, 184, 166, 255))
    draw_polygon(
        canvas,
        [
            (648 * s, 724 * s),
            (752 * s, 724 * s),
            (700 * s, 780 * s),
        ],
        (20, 184, 166, 255),
    )
    draw_line(canvas, 646 * s, 800 * s, 754 * s, 800 * s, 24 * s, (20, 184, 166, 255))

    return downsample_box(canvas, MASTER_SIZE)


def build_iconset(master: list[list[Color]]) -> None:
    if ICONSET_DIR.exists():
        shutil.rmtree(ICONSET_DIR)
    ICONSET_DIR.mkdir(parents=True)
    sizes = {
        "icon_16x16.png": 16,
        "icon_16x16@2x.png": 32,
        "icon_32x32.png": 32,
        "icon_32x32@2x.png": 64,
        "icon_128x128.png": 128,
        "icon_128x128@2x.png": 256,
        "icon_256x256.png": 256,
        "icon_256x256@2x.png": 512,
        "icon_512x512.png": 512,
        "icon_512x512@2x.png": 1024,
    }
    for filename, size in sizes.items():
        if size == MASTER_SIZE:
            shutil.copy2(MASTER_PNG, ICONSET_DIR / filename)
            continue
        subprocess.run(
            [
                "sips",
                "-z",
                str(size),
                str(size),
                str(MASTER_PNG),
                "--out",
                str(ICONSET_DIR / filename),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )


def write_icns() -> None:
    chunks = [
        (b"icp4", ICONSET_DIR / "icon_16x16.png"),
        (b"icp5", ICONSET_DIR / "icon_32x32.png"),
        (b"icp6", ICONSET_DIR / "icon_32x32@2x.png"),
        (b"ic07", ICONSET_DIR / "icon_128x128.png"),
        (b"ic08", ICONSET_DIR / "icon_256x256.png"),
        (b"ic09", ICONSET_DIR / "icon_512x512.png"),
        (b"ic10", ICONSET_DIR / "icon_512x512@2x.png"),
    ]
    payload = bytearray()
    for chunk_type, path in chunks:
        data = path.read_bytes()
        payload.extend(chunk_type)
        payload.extend(struct.pack(">I", len(data) + 8))
        payload.extend(data)
    ICNS_PATH.write_bytes(b"icns" + struct.pack(">I", len(payload) + 8) + payload)


def write_ico() -> None:
    entries = [
        ICONSET_DIR / "icon_16x16.png",
        ICONSET_DIR / "icon_32x32.png",
        ICONSET_DIR / "icon_32x32@2x.png",
        ICONSET_DIR / "icon_128x128.png",
        ICONSET_DIR / "icon_256x256.png",
    ]
    header_size = 6 + (16 * len(entries))
    image_offset = header_size
    directory = bytearray()
    payload = bytearray()

    for path in entries:
        size = int(path.stem.split("_", 1)[1].split("x", 1)[0])
        data = path.read_bytes()
        directory.extend(
            struct.pack(
                "<BBBBHHII",
                0 if size >= 256 else size,
                0 if size >= 256 else size,
                0,
                0,
                1,
                32,
                len(data),
                image_offset,
            )
        )
        payload.extend(data)
        image_offset += len(data)

    ICO_PATH.write_bytes(struct.pack("<HHH", 0, 1, len(entries)) + directory + payload)


def main() -> int:
    ASSETS_DIR.mkdir(exist_ok=True)
    master = build_master()
    write_png(MASTER_PNG, master)
    build_iconset(master)
    write_icns()
    write_ico()
    print(f"Icons generated: {ICNS_PATH}, {ICO_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
