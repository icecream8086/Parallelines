"""Extract dependencies from .vmt material files."""

from __future__ import annotations

import logging
import re


logger = logging.getLogger(__name__)

# Texture keys commonly referenced in VMT files that point to external assets.
_TEXTURE_KEYS = {"$basetexture", "$bumpmap", "$normalmap"}

# Pattern matching: $key "value"
_KEY_VALUE_RE = re.compile(r'\$(\w+)\s+"([^"]+)"')


def _normalise_texture_path(texture: str) -> str:
    """Normalise a texture reference to a ``materials/`` relative path.

    - If the texture name has no file extension, ``.vtf`` is appended.
    - If the path does not already start with ``materials/``, the prefix is
      prepended.
    - Backslashes are converted to forward slashes.

    Args:
        texture: Raw texture value from the VMT file.

    Returns:
        Normalised path relative to the game root.
    """
    tex = texture.strip().replace("\\", "/")

    if not tex.endswith((".vtf", ".vmt", ".png", ".jpg", ".tga")):
        tex += ".vtf"

    if not tex.startswith("materials/"):
        tex = "materials/" + tex

    return tex


def extract_vmt_dependencies(file_content: str) -> set[str]:
    """Extract texture dependency paths from VMT material file content.

    Looks for the keys ``$basetexture``, ``$bumpmap``, and ``$normalmap`` and
    returns their values as normalised paths under ``materials/``.

    Args:
        file_content: The full text content of a .vmt file.

    Returns:
        Set of discovered dependency paths. Empty set on failure.
    """
    try:
        dependencies: set[str] = set()

        for key in _TEXTURE_KEYS:
            # Build a pattern for the specific key
            pattern = re.compile(re.escape(key) + r'\s+"([^"]+)"', re.IGNORECASE)
            for match in pattern.finditer(file_content):
                raw_value = match.group(1)
                dependencies.add(_normalise_texture_path(raw_value))

        return dependencies

    except Exception as exc:
        logger.warning("Failed to extract VMT dependencies: %s", exc)
        return set()


def extract_vmt_texture_path(content: str) -> set[str]:
    """Extract all values of ``$``-prefixed keys from VMT content.

    This is a lower-level helper that returns every quoted string value
    associated with any ``$key`` in the material file, providing a hook
    for future extensibility.

    Args:
        content: The full text content of a .vmt file.

    Returns:
        Set of all discovered quoted values following ``$`` keys.
    """
    try:
        values: set[str] = set()
        for match in _KEY_VALUE_RE.finditer(content):
            values.add(match.group(2))
        return values

    except Exception as exc:
        logger.warning("Failed to extract VMT texture paths: %s", exc)
        return set()
