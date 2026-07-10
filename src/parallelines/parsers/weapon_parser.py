"""Extract model/sound/texture references from weapon_*.txt scripts."""

from __future__ import annotations
import logging
from parallelines.parsers.kv_parser import parse_kv

logger = logging.getLogger(__name__)

_MODEL_KEYS = {"viewmodel", "playermodel", "worldmodel"}


def _normalise_sound(raw: str) -> str:
    path = raw.strip().replace("\\", "/")
    if not path.lower().startswith("sound/"):
        path = "sound/" + path
    return path


def _normalise_texture(raw: str) -> str:
    path = raw.strip().replace("\\", "/")
    if not path.endswith((".vtf", ".vmt", ".png")):
        path += ".vtf"
    if not path.lower().startswith("materials/"):
        path = "materials/" + path
    return path


def extract_weapon_dependencies(file_content: str) -> set[str]:
    try:
        kv = parse_kv(file_content)
        deps: set[str] = set()
        weapon_data = kv.get("weapondata", kv)  # top-level or nested
        if isinstance(weapon_data, dict):
            for key, value in weapon_data.items():
                if not isinstance(value, str):
                    continue
                if key in _MODEL_KEYS:
                    deps.add(value.replace("\\", "/"))
                elif key.startswith("sound_"):
                    deps.add(_normalise_sound(value))
                elif key == "texture":
                    deps.add(_normalise_texture(value))
        return deps
    except Exception as exc:
        logger.warning("Failed to parse weapon script: %s", exc)
        return set()
