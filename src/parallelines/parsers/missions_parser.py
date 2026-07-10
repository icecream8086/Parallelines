"""Extract map references from missions/*.txt campaign definitions."""

from __future__ import annotations
import logging
from parallelines.parsers.kv_parser import parse_kv

logger = logging.getLogger(__name__)


def extract_missions_dependencies(file_content: str) -> set[str]:
    try:
        kv = parse_kv(file_content)
        deps: set[str] = set()
        modes = kv.get("modes")
        if not isinstance(modes, dict):
            return deps
        for mode_name, mode_def in modes.items():
            if not isinstance(mode_def, dict):
                continue
            for entry_key, entry_def in mode_def.items():
                if not isinstance(entry_def, dict):
                    continue
                map_name = entry_def.get("map")
                if isinstance(map_name, str):
                    deps.add(f"maps/{map_name}.bsp")
        return deps
    except Exception as exc:
        logger.warning("Failed to parse missions: %s", exc)
        return set()
