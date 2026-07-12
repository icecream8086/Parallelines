"""Extract file dependencies from .bsp map files using srctools."""

from __future__ import annotations

import logging
import os
import re
import tempfile

from parallelines.error_policy import parse_failure

logger = logging.getLogger(__name__)

# Matches ``exec`` calls within console commands.
_EXEC_RE = re.compile(r'\bexec\s+(\S+)', re.IGNORECASE)


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
        file_obj = chain[virtual_path]
        raw = file_obj.open_bin().read()

        fd, tmp_path = tempfile.mkstemp(suffix=".bsp")
        os.write(fd, raw)
        os.close(fd)

        bsp = BSP(tmp_path)

        # Extract texture names.
        for tex in bsp.textures:
            if tex and isinstance(tex, str):
                vmt_path = f"materials/{tex}.vmt"
                dependencies.add(vmt_path)

        # Extract static prop model paths.
        for model_path in bsp.static_prop_models():
            if model_path and isinstance(model_path, str):
                dependencies.add(model_path)

        # Extract entity side effects (§5.3).
        side_effects = extract_bsp_entity_side_effects(bsp)
        for cmd in side_effects.get("commands", []):
            for m in _EXEC_RE.finditer(cmd):
                exec_target = m.group(1).strip().replace("\\", "/").strip('"')
                if not exec_target.endswith(".cfg"):
                    exec_target += ".cfg"
                if "/" not in exec_target:
                    exec_target = "cfg/" + exec_target
                dependencies.add(exec_target)

    except Exception as exc:
        parse_failure(exc, "bsp_parser.extract_deps")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    return dependencies


def extract_bsp_entity_side_effects(bsp) -> dict[str, list[str]]:
    """Extract side-effecting entity keyvalues from a parsed BSP.

    Inspects entities with classnames that have persistent engine-wide
    side effects:

    * ``point_servercommand`` — its ``command`` keyvalue executes arbitrary
      console commands (may ``exec`` config files).
    * ``env_global`` — its ``globalstate`` keyvalue sets named global state.

    Returns:
        ``{"commands": [...], "globalstates": [...]}``
    """
    effects: dict[str, list[str]] = {"commands": [], "globalstates": []}
    try:
        if not hasattr(bsp, "ents"):
            return effects
        ents = bsp.ents.entities if hasattr(bsp.ents, "entities") else bsp.ents
        for ent in ents:
            classname = str(ent.get("classname", "")).strip().lower()
            if classname == "point_servercommand":
                cmd = str(ent.get("command", "")).strip()
                if cmd:
                    effects["commands"].append(cmd)
            elif classname == "env_global":
                gs = str(ent.get("globalstate", "")).strip()
                if gs:
                    effects["globalstates"].append(gs)
    except Exception as exc:
        parse_failure(exc, "bsp_parser.entity_extract")
    return effects
