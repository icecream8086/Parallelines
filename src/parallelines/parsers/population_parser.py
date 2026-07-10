"""Extract model dependencies from scripts/population.txt."""

from __future__ import annotations
import logging
from parallelines.parsers.kv_parser import parse_kv

logger = logging.getLogger(__name__)

_CLASS_TO_MODEL: dict[str, str] = {
    "hunter": "models/infected/hunter.mdl",
    "smoker": "models/infected/smoker.mdl",
    "boomer": "models/infected/boomer.mdl",
    "tank": "models/infected/hulk.mdl",
    "charger": "models/infected/charger.mdl",
    "spitter": "models/infected/spitter.mdl",
    "jockey": "models/infected/jockey.mdl",
    "witch": "models/infected/witch.mdl",
}


def extract_population_dependencies(file_content: str) -> set[str]:
    try:
        kv = parse_kv(file_content)
        deps: set[str] = set()
        for class_name, class_def in kv.items():
            if not isinstance(class_def, dict):
                continue
            zombie_class = class_def.get("zombie_class")
            if isinstance(zombie_class, str):
                lower = zombie_class.lower()
                if lower in _CLASS_TO_MODEL:
                    deps.add(_CLASS_TO_MODEL[lower])
                else:
                    deps.add(f"models/infected/{lower}.mdl")
        return deps
    except Exception as exc:
        logger.warning("Failed to parse population.txt: %s", exc)
        return set()
