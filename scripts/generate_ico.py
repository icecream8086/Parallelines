#!/usr/bin/env python
"""Generate ico/logo.ico from ico/logo.svg.

Produces a Windows ICO with 4 square frames: 16, 32, 48, 256.
Relies on cairosvg (SVG→PNG) and manually builds the ICO via struct.

Each frame is stored as embedded PNG data inside the ICO (Windows Vista+),
which is the simplest correct approach across Pillow versions.
"""

from __future__ import annotations

import io
import struct
import sys
from pathlib import Path

import cairosvg
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ICO_PATH = PROJECT_ROOT / "ico" / "logo.ico"

svg_candidates = [
    PROJECT_ROOT / "ico" / "logo.svg",
    PROJECT_ROOT / "ico" / "logo.ico.svg",
]
SVG_PATH = next((p for p in svg_candidates if p.exists()), None)


def _render_png_bytes(svg_data: bytes, size: int) -> bytes:
    """Render SVG to RGBA PNG at the given size, return PNG bytes."""
    png = cairosvg.svg2png(bytestring=svg_data, output_width=size, output_height=size)
    return png


def _render_png_resized(svg_data: bytes, size: int, ref_pil: Image.Image) -> bytes:
    """Render at 256 px then downsample via Pillow (LANCZOS) for better AA."""
    out = io.BytesIO()
    ref_pil.resize((size, size), Image.LANCZOS).save(out, format="PNG")
    return out.getvalue()


def main() -> int:
    if SVG_PATH is None:
        print("ERROR: Cannot find ico/logo.svg")
        return 1

    sizes = [16, 32, 48, 256]
    print(f"Reading SVG: {SVG_PATH}")

    svg_data = SVG_PATH.read_bytes()

    # Render the largest size at native resolution for best quality
    hi_res_png = _render_png_bytes(svg_data, 256)
    hi_res_img = Image.open(io.BytesIO(hi_res_png)).convert("RGBA")

    # Build PNG data for each frame
    frame_pngs: list[bytes] = []
    for s in sizes:
        if s == 256:
            frame_pngs.append(hi_res_png)
        else:
            frame_pngs.append(_render_png_resized(svg_data, s, hi_res_img))

    # Build ICO manually:
    #   ICO header:   reserved(2) + type(1=ICO)(2) + count(2)  = 6 bytes
    #   Directory entries: count * 16 bytes
    #   Image data: each frame's PNG bytes
    count = len(sizes)
    header = struct.pack("<HHH", 0, 1, count)

    # Compute offsets: header + directory
    data_offset = 6 + count * 16
    directory = b""
    for i, (s, png_data) in enumerate(zip(sizes, frame_pngs)):
        # ICO directory entry:
        #   bWidth(1), bHeight(1), color_count(1), reserved(1),
        #   planes(2), bpp(2), image_size(4), image_offset(4)
        w = s if s < 256 else 0  # 0 means 256 in ICO
        h = s if s < 256 else 0
        directory += struct.pack(
            "<BBBBHHII",
            w,          # width (0 = 256)
            h,          # height (0 = 256)
            0,          # color count (0 = no palette)
            0,          # reserved
            1,          # planes
            32,         # bits per pixel (RGBA PNG)
            len(png_data),
            data_offset,
        )
        data_offset += len(png_data)

    ico_data = header + directory + b"".join(frame_pngs)

    ICO_PATH.parent.mkdir(parents=True, exist_ok=True)
    ICO_PATH.write_bytes(ico_data)

    print(f"[OK] {ICO_PATH}  ({len(ico_data):,} bytes)")
    for s in sizes:
        print(f"     Frame: {s}x{s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
