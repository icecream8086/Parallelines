"""Extract texture paths from hud_textures.txt and mod_textures.txt."""

from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


def extract_texture_list_dependencies(file_content: str) -> set[str]:
    """Parse a simple texture list (one VTF path per line/value)."""
    from parallelines.parsers.kv_parser import parse_kv
    deps: set[str] = set()
    try:
        kv = parse_kv(file_content)
        for key, value in kv.items():
            paths = value if isinstance(value, list) else [str(value)]
            for p in paths:
                p = str(p).replace("\\", "/")
                if not p.lower().endswith((".vtf", ".vmt", ".png")):
                    p += ".vtf"
                if not p.lower().startswith("materials/"):
                    p = "materials/" + p
                deps.add(p)
        return deps
    except Exception:
        return set()
