"""Extract model references from .ani animation definition files.

Source Engine .ani files reference models via key-value entries like:
    "model"  "models/infected/hunter.mdl"
"""

from __future__ import annotations
import logging
import re

from parallelines.error_policy import parse_failure

logger = logging.getLogger(__name__)

_ANI_MODEL_RE = re.compile(r'"model"\s+"([^"]+)"', re.IGNORECASE)


def extract_ani_dependencies(file_content: str) -> set[str]:
    try:
        deps: set[str] = set()
        for match in _ANI_MODEL_RE.finditer(file_content):
            path = match.group(1).replace("\\", "/").lower()
            if path.endswith(".mdl"):
                deps.add(path)
        return deps
    except Exception as exc:
        parse_failure(exc, "ani_parser")
        return set()
