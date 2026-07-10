"""Extract image/font references from .res UI resource files."""

from __future__ import annotations
import logging
from parallelines.parsers import normalise_texture_path
from parallelines.parsers.kv_parser import parse_kv

logger = logging.getLogger(__name__)


def _collect_deps(node, deps: set[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("image", "font") and isinstance(value, str):
                deps.add(normalise_texture_path(value))
            elif isinstance(value, (dict, list)):
                _collect_deps(value, deps)
    elif isinstance(node, list):
        for item in node:
            _collect_deps(item, deps)


def extract_res_dependencies(file_content: str) -> set[str]:
    try:
        deps: set[str] = set()
        kv = parse_kv(file_content)
        _collect_deps(kv, deps)
        return deps
    except Exception as exc:
        logger.warning("Failed to parse .res: %s", exc)
        return set()
