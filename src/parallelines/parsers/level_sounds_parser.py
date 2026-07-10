"""Extract .wav references from maps/*_level_sounds.txt files."""

from __future__ import annotations
import logging
from parallelines.parsers import normalise_sound_path
from parallelines.parsers.kv_parser import parse_kv

logger = logging.getLogger(__name__)


def extract_level_sounds_dependencies(file_content: str) -> set[str]:
    try:
        kv = parse_kv(file_content)
        deps: set[str] = set()
        for key, value in kv.items():
            if isinstance(value, dict):
                sounds = value.get("sound")
                if isinstance(sounds, str):
                    deps.add(normalise_sound_path(sounds))
                elif isinstance(sounds, list):
                    for s in sounds:
                        deps.add(normalise_sound_path(str(s)))
        return deps
    except Exception as exc:
        logger.warning("Failed to parse level_sounds: %s", exc)
        return set()
