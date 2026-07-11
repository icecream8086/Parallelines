"""Extract .wav references from game_sounds_*.txt KeyValues files."""

from __future__ import annotations
import logging
from parallelines.error_policy import parse_failure
from parallelines.parsers import normalise_sound_path
from parallelines.parsers.kv_parser import parse_kv

logger = logging.getLogger(__name__)


def _extract_wave(wave, deps: set[str]) -> None:
    """Extract a 'wave' entry, handling both string and list forms."""
    if isinstance(wave, str):
        deps.add(normalise_sound_path(wave))
    elif isinstance(wave, list):
        for w in wave:
            deps.add(normalise_sound_path(w))


def _extract_rndwave(rndwave, deps: set[str]) -> None:
    """Extract 'rndwave', handling dict, list-of-dicts, and list-of-strings forms."""
    if isinstance(rndwave, dict):
        _extract_wave(rndwave.get("wave"), deps)
    elif isinstance(rndwave, list):
        for item in rndwave:
            if isinstance(item, dict):
                _extract_wave(item.get("wave"), deps)
            elif isinstance(item, str):
                deps.add(normalise_sound_path(item))


def extract_game_sounds_dependencies(file_content: str) -> set[str]:
    try:
        kv = parse_kv(file_content)
        deps: set[str] = set()
        for sound_name, sound_def in kv.items():
            if not isinstance(sound_def, dict):
                continue
            _extract_wave(sound_def.get("wave"), deps)
            _extract_rndwave(sound_def.get("rndwave"), deps)
        return deps
    except Exception as exc:
        parse_failure(exc, "game_sounds_parser")
        return set()
