"""Extract file dependencies from .bsp map files using srctools."""

from __future__ import annotations

import logging
import os
import tempfile

logger = logging.getLogger(__name__)


def extract_bsp_dependencies(chain, virtual_path: str) -> set[str]:
    """Extract dependencies from a .bsp map file.

    Uses ``srctools.bsp.BSP`` (lazy imported).  Texture names are converted
    to ``materials/<name>.vmt`` paths; static prop model paths are returned
    as-is.

    Because ``srctools.bsp.BSP`` reads from a file path on disk (not from a
    VPK), the function writes the file content to a temporary file, parses
    it, and then cleans up.

    Args:
        chain: A ``srctools.filesys.FileSystemChain`` (or compatible) for
            reading file content from combined VPKs / loose directories.
        virtual_path: Virtual path to the ``.bsp`` file
            (e.g. ``"maps/c1m1_hotel.bsp"``).

    Returns:
        Set of dependency paths (texture ``.vmt`` paths, model ``.mdl`` paths).
        Returns an empty set when ``srctools.bsp`` is not available or parsing
        fails.
    """
    try:
        from srctools.bsp import BSP
    except ImportError:
        logger.debug("srctools.bsp not available; skipping BSP parsing")
        return set()

    dependencies: set[str] = set()
    tmp_path: str | None = None

    try:
        # Read from chain and write to a temporary file on disk.
        file_obj = chain[virtual_path]
        raw = file_obj.open_bin().read()

        fd, tmp_path = tempfile.mkstemp(suffix=".bsp")
        os.write(fd, raw)
        os.close(fd)

        bsp = BSP(tmp_path)

        # Extract texture names — they are bare names like
        # "nature/dirtfloor008a" which need to become materials/ paths.
        for tex in bsp.textures:
            if tex and isinstance(tex, str):
                vmt_path = f"materials/{tex}.vmt"
                dependencies.add(vmt_path)

        # Extract static prop model paths.
        for model_path in bsp.static_prop_models():
            if model_path and isinstance(model_path, str):
                dependencies.add(model_path)

    except Exception as exc:
        logger.debug("Failed to parse bsp '%s': %s", virtual_path, exc)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    return dependencies
