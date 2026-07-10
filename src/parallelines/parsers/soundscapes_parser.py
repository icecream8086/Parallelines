"""Extract .wav references from soundscapes_*.txt files."""

from __future__ import annotations
import logging
import re
from parallelines.parsers import normalise_sound_path

logger = logging.getLogger(__name__)

_WAVE_RE = re.compile(r'"wave"\s+"([^"]+)"')


def extract_soundscapes_dependencies(file_content: str) -> set[str]:
    try:
        deps: set[str] = set()
        for match in _WAVE_RE.finditer(file_content):
            deps.add(normalise_sound_path(match.group(1)))
        return deps
    except Exception as exc:
        logger.warning("Failed to parse soundscapes: %s", exc)
        return set()
