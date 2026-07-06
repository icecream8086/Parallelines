#!/usr/bin/env python
"""Generate ico/logo.ico from ico/logo.svg.

Uses cairosvg for rendering when available (Linux CI with libcairo2-dev, or
local machines with cairo DLLs).  Falls back to Pillow-only rendering when
cairo is not available (Windows CI without GTK runtime, etc.).

The fallback icon recreates the same parallel-lines-and-nodes concept directly
with Pillow drawing primitives — no system C library needed.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ICO_PATH = PROJECT_ROOT / "ico" / "logo.ico"

# ── Try cairosvg (optional) ────────────────────────────────────────────

svg_candidates = [
    PROJECT_ROOT / "ico" / "logo.svg",
    PROJECT_ROOT / "ico" / "logo.ico.svg",
]
SVG_PATH = next((p for p in svg_candidates if p.exists()), None)

try:
    import cairosvg
    CAIROSVG_OK = True
except Exception:
    CAIROSVG_OK = False


# ── SVG rendering (when cairo available) ───────────────────────────────


def _render_svg_png(size: int, svg_data: bytes) -> bytes | None:
    """Render SVG to PNG bytes at *size* via cairosvg."""
    if not CAIROSVG_OK or not svg_data:
        return None
    try:
        return cairosvg.svg2png(
            bytestring=svg_data, output_width=size, output_height=size,
        )
    except Exception:
        return None


# ── Pillow fallback rendering (always available) ───────────────────────


def _render_fallback_png(size: int) -> Image.Image:
    """Draw a parallel-lines-and-nodes icon with Pillow (no cairo needed)."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Scale factor relative to 256px reference
    S = size / 256.0

    def s(v: float) -> int:
        return round(v * S)

    c_dark = (24, 24, 27, 255)       # #18181B
    c_darker = (14, 14, 17, 255)     # #0E0E11
    c_blue_1 = (79, 70, 229, 255)    # #4F46E5
    c_blue_2 = (14, 165, 233, 255)   # #0EA5E9
    c_orange = (249, 115, 22, 255)   # #F97316
    c_white = (255, 255, 255, 255)

    # Background: split dark tones
    mid_x = s(125)
    draw.rectangle([0, 0, mid_x, size], fill=c_dark)
    draw.rectangle([mid_x, 0, size, size], fill=c_darker)

    # Gradient helper: blend two colors
    def grad(x1, y1, x2, y2, c1, c2):
        """Draw a gradient line by layering thin segments."""
        steps = max(abs(x2 - x1), abs(y2 - y1), 8)
        for i in range(steps + 1):
            t = i / steps
            x = round(x1 + (x2 - x1) * t)
            y = round(y1 + (y2 - y1) * t)
            r = round(c1[0] + (c2[0] - c1[0]) * t)
            g = round(c1[1] + (c2[1] - c1[1]) * t)
            b = round(c1[2] + (c2[2] - c1[2]) * t)
            draw.point((x, y), fill=(r, g, b, 255))

    # Line positions (scaled from SVG coordinates)
    nodes_svg = [
        (10, 120), (10, 392),          # left VPK
        (160, 10), (160, 180), (160, 332), (160, 490),   # dag left
        (340, 100), (340, 256), (340, 412),              # dag right
        (490, 120), (490, 392),         # right VPK
    ]
    nodes = [(s(x), s(y)) for x, y in nodes_svg]

    # Connection lines (SVG line coordinates)
    lines = [
        (0, 1), (0, 2), (0, 6), (1, 4), (1, 5),
        (2, 7), (3, 6), (4, 6), (4, 7), (5, 7),
        (6, 8), (7, 8), (7, 9), (8, 10),
    ]
    for i, j in lines:
        if i < len(nodes) and j < len(nodes):
            grad(nodes[i][0], nodes[i][1], nodes[j][0], nodes[j][1],
                 c_blue_1, c_blue_2)

    # Draw thick line segments for the parallel-line effect
    lw = max(1, s(5))
    for pts in [
        [(10, 120), (160, 10)],
        [(10, 120), (160, 180)],
        [(10, 392), (160, 332)],
        [(10, 392), (160, 490)],
        [(490, 120), (340, 100)],
        [(490, 120), (340, 256)],
        [(490, 392), (340, 256)],
        [(490, 392), (340, 412)],
    ]:
        x1, y1 = s(pts[0][0]), s(pts[0][1])
        x2, y2 = s(pts[1][0]), s(pts[1][1])
        draw.line([(x1, y1), (x2, y2)], fill=c_blue_2, width=lw)

    # DAG node circles (blue)
    dag_indices = [2, 3, 4, 5, 6, 7, 8]
    for idx in dag_indices:
        cx, cy = nodes[idx]
        r = max(1, s(14))
        r2 = max(1, s(11))
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c_white)
        draw.ellipse([cx - r2, cy - r2, cx + r2, cy + r2], fill=c_blue_2)

    # VPK node circles (orange) with inner detail
    vpk_indices = [0, 1, 9, 10]
    for idx in vpk_indices:
        cx, cy = nodes[idx]
        r = max(1, s(14))
        r2 = max(1, s(11))
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c_white)
        draw.ellipse([cx - r2, cy - r2, cx + r2, cy + r2], fill=c_orange)

    return img


# ── ICO packer ─────────────────────────────────────────────────────────


def _pack_ico(sizes: list[int], frames: list[bytes]) -> bytes:
    """Build a Windows ICO file from PNG frame data."""
    count = len(sizes)
    header = struct.pack("<HHH", 0, 1, count)
    data_offset = 6 + count * 16
    directory = b""
    for s, png_data in zip(sizes, frames):
        w = 0 if s >= 256 else s
        h = 0 if s >= 256 else s
        directory += struct.pack(
            "<BBBBHHII", w, h, 0, 0, 1, 32, len(png_data), data_offset,
        )
        data_offset += len(png_data)
    return header + directory + b"".join(frames)


# ── Main ───────────────────────────────────────────────────────────────


def main() -> int:
    svg_data = SVG_PATH.read_bytes() if SVG_PATH else b""
    sizes = [16, 32, 48, 256]

    frames: list[bytes] = []
    for s in sizes:
        png = None
        if svg_data:
            png = _render_svg_png(s, svg_data)
        if png is not None:
            frames.append(png)
        else:
            img = _render_fallback_png(s)
            import io
            buf = io.BytesIO()
            img.save(buf, "PNG")
            frames.append(buf.getvalue())

    ico_data = _pack_ico(sizes, frames)
    ICO_PATH.parent.mkdir(parents=True, exist_ok=True)
    ICO_PATH.write_bytes(ico_data)

    source = "cairosvg" if CAIROSVG_OK and svg_data else "Pillow"
    print(f"[OK] {ICO_PATH}  ({len(ico_data):,} bytes, rendered via {source})")
    for s in sizes:
        print(f"     Frame: {s}x{s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
