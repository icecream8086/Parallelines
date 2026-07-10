"""Extract .wav references from game_sounds_*.txt KeyValues files."""

from __future__ import annotations
import logging
from parallelines.parsers import normalise_sound_path
from parallelines.parsers.kv_parser import parse_kv

logger = logging.getLogger(__name__)


def extract_game_sounds_dependencies(file_content: str) -> set[str]:
    try:
        kv = parse_kv(file_content)
        deps: set[str] = set()
        for sound_name, sound_def in kv.items():
            if not isinstance(sound_def, dict):
                continue
            wave = sound_def.get("wave")
            if isinstance(wave, str):
                deps.add(normalise_sound_path(wave))
            elif isinstance(wave, list):
                for w in wave:
                    deps.add(normalise_sound_path(w))
            rndwave = sound_def.get("rndwave")
            if isinstance(rndwave, dict):
                wave_list = rndwave.get("wave")
                if isinstance(wave_list, str):
                    deps.add(normalise_sound_path(wave_list))
                elif isinstance(wave_list, list):
                    for w in wave_list:
                        deps.add(normalise_sound_path(w))
        return deps
    except Exception as exc:
        logger.warning("Failed to parse game_sounds: %s", exc)
        return set()
