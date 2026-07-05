"""Entry point discovery — find files the engine loads at startup.

Entry points are the roots for dead-file reachability analysis.
For L4D2 these include:
- Known manifest files (soundscapes, particles, game_sounds)
- Map files (.bsp) in the maps/ directory (limited to first N alphabetically)
- Script entry points (cfg/game.cfg, scripts/vscripts/)
- The gameinfo.txt itself
- Direct dependencies listed in discovered manifest files
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Maximum number of .bsp files to automatically add as entry points.
# Maps sorted alphabetically — the first N are typically campaign-start maps.
P2_ENTRY_POINT_LIMIT: int = 5

# Common manifest paths that the Source Engine loads at startup.  These are
# checked against the active VFS during auto-discovery.
_COMMON_MANIFESTS: set[str] = {
    "scripts/soundscapes_manifest.txt",
    "scripts/game_sounds_manifest.txt",
    "particles/particles_manifest.txt",
}

# Well-known script / config entry points checked during auto-discovery.
_COMMON_SCRIPT_ENTRIES: set[str] = {
    "cfg/game.cfg",
    "cfg/autoexec.cfg",
}


def _read_manifest_content(chain, manifest_path: str) -> list[str]:
    """Read a manifest file through *chain* and return non-comment lines.

    Args:
        chain: A ``srctools.filesys.FileSystemChain`` (or compatible) for
            reading file content, or ``None``.
        manifest_path: Virtual path to the manifest file.

    Returns:
        List of stripped, non-comment lines.  Empty list when *chain* is
        ``None`` or the path cannot be read.
    """
    if chain is None:
        return []
    try:
        file_obj = chain[manifest_path]
        content = file_obj.open_str().read()
    except Exception:
        return []

    lines: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("//", "#")):
            continue
        lines.append(stripped)
    return lines


def discover_entry_points(vfs, chain=None) -> set[str]:
    """Auto-discover entry points from active files.

    Scans all active files in the VFS and returns the set of virtual paths
    that the Source Engine would load at startup.  This set serves as the
    roots for dead-file reachability analysis.

    When a *chain* is provided, manifest files are read to discover their
    listed dependencies and add those as entry points too.

    Only the first :data:`P2_ENTRY_POINT_LIMIT` ``.bsp`` files (sorted
    alphabetically) are included to avoid bloating the entry-point set with
    rarely-played maps.

    Args:
        vfs: VirtualFileSystem instance with resolved active files.
        chain: Optional ``srctools.filesys.FileSystemChain`` for reading file
            content.  When provided, manifest-listed files are also added.

    Returns:
        A set of virtual paths acting as entry points.  Returns an empty set
        when *vfs* is ``None`` or has no active files.
    """
    if vfs is None:
        logger.debug("discover_entry_points: vfs is None, returning empty set")
        return set()

    try:
        active_files = vfs.get_all_active()
    except Exception:
        logger.exception("discover_entry_points: failed to get all active files")
        return set()

    if not active_files:
        logger.debug("discover_entry_points: no active files, returning empty set")
        return set()

    # Build a case-insensitive lookup of active virtual paths.
    # Key = lowercased, forward-slash-normalised path;
    # Value = original-case path as stored in the VFS.
    active_paths_lower: dict[str, str] = {}
    for node in active_files:
        lower = node.virtual_path.lower().replace("\\", "/")
        active_paths_lower[lower] = node.virtual_path

    entry_points: set[str] = set()

    # 1. Known manifest paths (case-insensitive matching).
    manifest_count = 0
    for manifest in _COMMON_MANIFESTS:
        if manifest in active_paths_lower:
            entry_points.add(active_paths_lower[manifest])
            manifest_count += 1
            logger.debug(
                "discover_entry_points: found manifest '%s'",
                active_paths_lower[manifest],
            )

    # L4D2 / additional manifests that are safe to include when present.
    for manifest in ("scripts/model_manifest.txt",):
        if manifest in active_paths_lower:
            entry_points.add(active_paths_lower[manifest])
            manifest_count += 1
            logger.debug(
                "discover_entry_points: found manifest '%s'",
                active_paths_lower[manifest],
            )

    if manifest_count:
        logger.debug("discover_entry_points: found %d manifest files", manifest_count)

    # 1b. Direct dependencies from manifest files.
    #     When a chain is available, read manifest content and add any listed
    #     paths that actually exist in the VFS as entry points.
    dep_count = 0
    if chain is not None:
        for lower_path, original_path in active_paths_lower.items():
            if "manifest" in lower_path and lower_path.endswith(".txt"):
                manifest_lines = _read_manifest_content(chain, original_path)
                for line in manifest_lines:
                    lower_line = line.lower().replace("\\", "/")
                    if lower_line in active_paths_lower:
                        entry_points.add(active_paths_lower[lower_line])
                        dep_count += 1
                        logger.debug(
                            "discover_entry_points: manifest dep '%s' from '%s'",
                            active_paths_lower[lower_line],
                            original_path,
                        )
    if dep_count:
        logger.debug(
            "discover_entry_points: found %d manifest dependency entry points",
            dep_count,
        )

    # 2. .bsp files (limited to P2_ENTRY_POINT_LIMIT, sorted alphabetically).
    bsp_candidates = sorted(
        (lower, original)
        for lower, original in active_paths_lower.items()
        if lower.endswith(".bsp")
    )
    bsp_count = 0
    for lower_path, original_path in bsp_candidates[:P2_ENTRY_POINT_LIMIT]:
        entry_points.add(original_path)
        bsp_count += 1
    if bsp_count:
        logger.debug(
            "discover_entry_points: found %d .bsp maps (limited to %d)",
            bsp_count,
            P2_ENTRY_POINT_LIMIT,
        )

    # 3. Common script / config entry points.
    script_lower = {p.lower(): p for p in _COMMON_SCRIPT_ENTRIES}
    for lower_path, original_path in active_paths_lower.items():
        if lower_path in script_lower:
            entry_points.add(original_path)
            logger.debug(
                "discover_entry_points: found script entry '%s'",
                original_path,
            )

        # All .nut files under scripts/vscripts/ are VScript entry points.
        if lower_path.startswith("scripts/vscripts/") and lower_path.endswith(".nut"):
            entry_points.add(original_path)
            logger.debug(
                "discover_entry_points: found vscript '%s'",
                original_path,
            )

    # 4. Ensure gameinfo.txt is always treated as an entry point.
    gameinfo = active_paths_lower.get("gameinfo.txt")
    if gameinfo:
        entry_points.add(gameinfo)
        logger.debug("discover_entry_points: found gameinfo.txt")

    logger.info("discover_entry_points: found %d entry points", len(entry_points))
    return entry_points


def filter_entry_points(
    entry_points: set[str],
    vfs,
    graph,
) -> set[str]:
    """Remove entry points with *no outgoing edges* in the dependency graph.

    An entry point that is not present in the graph or has zero outgoing
    edges contributes nothing to reachability analysis and can be safely
    excluded from the root set.

    The *vfs* parameter is reserved for future validation (e.g. confirming
    that remaining entry points still exist in the active VFS).

    Args:
        entry_points: Set of virtual paths to filter.
        vfs: VirtualFileSystem instance (reserved for future use).
        graph: DependencyGraph instance.

    Returns:
        Filtered set of entry points containing only those with at least one
        outgoing graph edge.  Returns the original set unchanged if *graph*
        is ``None``.
    """
    if not entry_points or graph is None:
        return entry_points

    filtered: set[str] = set()
    removed: int = 0

    for ep in entry_points:
        if ep in graph.graph and graph.graph.out_degree(ep) > 0:
            filtered.add(ep)
        else:
            removed += 1
            logger.debug(
                "filter_entry_points: removing '%s' (no outgoing edges)",
                ep,
            )

    if removed:
        logger.info(
            "filter_entry_points: removed %d entry point(s) with no outgoing edges",
            removed,
        )

    return filtered


def get_known_entry_points(game: str) -> set[str]:
    """Return game-specific known entry points.

    These are well-known paths that the engine is expected to load, regardless
    of whether they currently exist in the VFS.  Callers may use this to
    supplement the auto-discovered set.

    Args:
        game: Source Engine game ID (e.g. ``"l4d2"``, ``"csgo"``, ``"tf2"``).

    Returns:
        A set of virtual paths for the given game.  Returns an empty set if
        *game* is ``None`` or empty.
    """
    if not game:
        logger.debug(
            "get_known_entry_points: game is None or empty, returning empty set"
        )
        return set()

    game = game.lower()

    if game == "l4d2":
        logger.debug("get_known_entry_points: returning L4D2 entry points")
        return {
            "scripts/soundscapes_manifest.txt",
            "scripts/game_sounds_manifest.txt",
            "particles/particles_manifest.txt",
            "scripts/model_manifest.txt",
            "cfg/config.cfg",
            "maps/*.bsp",
        }

    # Unknown game: return the truly common set only.
    logger.debug(
        "get_known_entry_points: unknown game '%s', returning common manifests",
        game,
    )
    return set(_COMMON_MANIFESTS)
