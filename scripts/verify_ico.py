#!/usr/bin/env python
"""Verify ico/logo.ico is a valid Windows ICO with 4 square frames (16, 32, 48, 256)."""

from __future__ import annotations

import struct
import sys
from pathlib import Path

ICO_PATH = Path(__file__).resolve().parent.parent / "ico" / "logo.ico"


def main() -> int:
    if not ICO_PATH.exists():
        print(f"FAIL: {ICO_PATH} does not exist")
        return 1

    data = ICO_PATH.read_bytes()
    size = len(data)
    print(f"File: {ICO_PATH}  ({size:,} bytes)")

    # ICO header: reserved(2) + type(2) + count(2)
    if len(data) < 6:
        print("FAIL: File too small for ICO header")
        return 1

    reserved, icon_type, count = struct.unpack_from("<HHH", data, 0)
    if reserved != 0:
        print(f"FAIL: Reserved field is {reserved}, expected 0")
        return 1
    if icon_type != 1:
        print(f"FAIL: Type is {icon_type}, expected 1 (ICO)")
        return 1

    print(f"Frame count: {count}")
    if count != 4:
        print(f"FAIL: Expected 4 frames, got {count}")
        return 1

    errors = 0
    for i in range(count):
        off = 6 + i * 16
        b_width, b_height, colors, reserved_byte, planes, bpp, img_size, img_offset = (
            struct.unpack_from("<BBBBHHII", data, off)
        )
        width = b_width if b_width != 0 else 256
        height = b_height if b_height != 0 else 256

        status = (
            f"  Frame {i}: {width}x{height}, "
            f"{bpp}-bit, "
            f"image size={img_size} bytes, "
            f"offset={img_offset}"
        )

        if width != height:
            print(f"FAIL: Frame {i} is not square ({width}x{height})")
            errors += 1
            print(status + "  <-- NOT SQUARE")
            continue

        if width not in (16, 32, 48, 256):
            print(f"FAIL: Frame {i} unexpected size {width}")
            errors += 1
            print(status + "  <-- UNEXPECTED SIZE")
            continue

        print(status + "  [OK]")

    if errors:
        print(f"\nFAIL: {errors} frame(s) have issues")
        return 1

    print(f"\n[OK] Valid ICO with {count} square frames (16, 32, 48, 256)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
