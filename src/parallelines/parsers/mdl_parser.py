"""Extract texture/material dependencies from .mdl model files using srctools."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from srctools.mdl import Model
    from srctools.vmt import Material

    SRCTOOLS_AVAILABLE = True
except ImportError:
    SRCTOOLS_AVAILABLE = False
    Model = None  # type: ignore[assignment]
    Material = None  # type: ignore[assignment]

_TEXTURE_KEYS = {"$basetexture", "$bumpmap", "$normalmap"}


def _normalise_vtf_path(texture: str) -> str:
    tex = texture.strip().replace("\\", "/")
    if not tex.endswith((".vtf", ".vmt", ".png", ".jpg", ".tga")):
        tex += ".vtf"
    if not tex.startswith("materials/"):
        tex = "materials/" + tex
    return tex


def extract_mdl_dependencies(chain, virtual_path: str) -> set[str]:
    """Extract material/texture dependencies from a .mdl model file.

    Returns both ``.vmt`` paths and their referenced ``.vtf`` textures.
    """
    if not SRCTOOLS_AVAILABLE:
        logger.warning("srctools is not installed; cannot parse .mdl files")
        return set()

    dependencies: set[str] = set()

    try:
        file_obj = chain[virtual_path]
    except Exception as exc:
        logger.debug("Failed to open mdl '%s': %s", virtual_path, exc)
        return set()

    try:
        model = Model(chain, file_obj)
    except Exception as exc:
        logger.debug("Failed to parse mdl '%s': %s", virtual_path, exc)
        return set()

    for vmt_path in model.iter_textures():
        if not isinstance(vmt_path, str):
            continue
        dependencies.add(vmt_path)

        try:
            vmt_file = chain[vmt_path]
            content = vmt_file.open_str().read()
        except Exception as exc:
            logger.debug("Could not read VMT '%s': %s", vmt_path, exc)
            continue

        try:
            mat = Material.parse(content, vmt_path)
        except Exception as exc:
            logger.debug("Could not parse VMT '%s': %s", vmt_path, exc)
            continue

        for key in _TEXTURE_KEYS:
            texture = mat.get(key)
            if texture:
                dependencies.add(_normalise_vtf_path(texture))

    return dependencies
