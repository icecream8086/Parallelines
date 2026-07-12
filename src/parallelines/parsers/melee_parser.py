"""Extract model references from scripts/melee/*.txt weapon definitions."""

from __future__ import annotations
import logging
from parallelines.parsers.kv_parser import parse_kv

logger = logging.getLogger(__name__)

_MODEL_KEYS = {"viewmodel", "worldmodel"}


def extract_melee_dependencies(file_content: str) -> set[str]:
    try:
        kv = parse_kv(file_content)
        deps: set[str] = set()
        for weapon_name, weapon_def in kv.items():
            if not isinstance(weapon_def, dict):
                continue
            for key in _MODEL_KEYS:
                val = weapon_def.get(key)
                if isinstance(val, str) and val:
                    deps.add(val.replace("\\", "/"))
        return deps
    except Exception as exc:
        logger.warning("Failed to parse melee: %s", exc)
        return set()
