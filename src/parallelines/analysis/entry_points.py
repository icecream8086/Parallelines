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
from pathlib import Path

from parallelines.error_policy import parse_failure
from parallelines.game_strategy import GameStrategy, get_strategy

logger = logging.getLogger(__name__)


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
    except Exception as exc:
        parse_failure(exc, "entry_points.read_file")
        return []

    lines: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("//", "#")):
            continue
        lines.append(stripped)
    return lines


def discover_entry_points(vfs, chain=None, game: str = "", bsp_limit: int | None = None) -> set[str]:
    """Auto-discover entry points from active files.

    Scans all active files in the VFS and returns the set of virtual paths
    that the Source Engine would load at startup.  This set serves as the
    roots for dead-file reachability analysis.

    When a *chain* is provided, manifest files are read to discover their
    listed dependencies and add those as entry points too.

    When *game* is provided, the corresponding :class:`GameStrategy` is used
    to determine manifests, BSP limits, and script entry points. Otherwise
    the default Source 1 strategy is applied.

    *bsp_limit* overrides the strategy's ``bsp_entry_limit`` when set.
    Pass -1 to include all .bsp files, 0 for none, or N for first N alphabetically.

    Args:
        vfs: VirtualFileSystem instance with resolved active files.
        chain: Optional ``srctools.filesys.FileSystemChain`` for reading file
            content.  When provided, manifest-listed files are also added.
        game: Source Engine game ID (e.g. ``"l4d2"``, ``"tf2"``).
        bsp_limit: Override for the strategy's BSP entry point limit.
            ``None`` (default) uses the strategy value.  0 = all maps.

    Returns:
        A set of virtual paths acting as entry points.  Returns an empty set
        when *vfs* is ``None`` or has no active files.
    """
    if vfs is None:
        logger.debug("discover_entry_points: vfs is None, returning empty set")
        return set()

    try:
        active_files = vfs.get_all_active()
    except Exception as exc:
        parse_failure(exc, "entry_points.discover")
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

    strategy = get_strategy(game) if game else GameStrategy()
    entry_points: set[str] = set()

    # 1. Known manifest paths from strategy (auto + extra).
    manifest_count = 0
    all_manifests = strategy.auto_manifests + strategy.extra_manifests
    for manifest in all_manifests:
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

    # 2. .bsp files are NOT entry points by default — they have no outgoing
    #    edges in the dependency graph, so adding them as roots does nothing
    #    for reachability analysis.  Only include them when:
    #    - User passes --all-maps (bsp_limit = -1)
    #    - User passes --maps N (bsp_limit = N, positive integer)
    #    - bsp_entry_limit in strategy is > 0 (game-specific default)
    bsp_candidates = sorted(
        (lower, original)
        for lower, original in active_paths_lower.items()
        if lower.endswith(".bsp")
    )
    limit = strategy.bsp_entry_limit if bsp_limit is None else bsp_limit
    bsp_count = 0
    bsp_selected = bsp_candidates if limit == -1 else (bsp_candidates[:limit] if limit > 0 else [])
    for lower_path, original_path in bsp_selected:
        entry_points.add(original_path)
        bsp_count += 1
    if bsp_count:
        logger.debug(
            "discover_entry_points: found %d .bsp maps (limit=%s)",
            bsp_count,
            limit,
        )

    # 3. Script / config entry points from strategy.
    script_lower = {p.lower(): p for p in strategy.script_entries}
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

    # 5. soundscapes_<mapname>.txt auto-detection (Section 3.1)
    #     Engine auto-loads scripts/soundscapes_<mapname>.txt when loading a map.
    soundscapes_auto = 0
    for lower_path, original_path in active_paths_lower.items():
        if lower_path.endswith(".bsp"):
            map_name = Path(lower_path).stem
            ss_path = f"scripts/soundscapes_{map_name}.txt"
            if ss_path in active_paths_lower:
                entry_points.add(active_paths_lower[ss_path])
                soundscapes_auto += 1
    if soundscapes_auto:
        logger.debug(
            "discover_entry_points: auto-discovered %d soundscapes entry points",
            soundscapes_auto,
        )

    # 6. maps/*_level_sounds.txt auto-detection (Section 3.2)
    #     Engine auto-loads maps/<mapname>_level_sounds.txt when loading a map.
    levelsounds_auto = 0
    for lower_path, original_path in active_paths_lower.items():
        if lower_path.endswith(".bsp"):
            map_name = Path(lower_path).stem
            ls_path = f"maps/{map_name}_level_sounds.txt"
            if ls_path in active_paths_lower:
                entry_points.add(active_paths_lower[ls_path])
                levelsounds_auto += 1
    if levelsounds_auto:
        logger.debug(
            "discover_entry_points: auto-discovered %d level_sounds entry points",
            levelsounds_auto,
        )

    # 7. missions/*.txt as entry points (Section 3.3)
    missions_count = 0
    for lower_path, original_path in active_paths_lower.items():
        if lower_path.startswith("missions/") and lower_path.endswith(".txt"):
            entry_points.add(original_path)
            missions_count += 1
    if missions_count:
        logger.debug(
            "discover_entry_points: found %d missions entry points",
            missions_count,
        )

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

    strategy = get_strategy(game)

    result: set[str] = set()
    for m in strategy.auto_manifests + strategy.extra_manifests:
        result.add(m)
    for s in strategy.script_entries:
        result.add(s)
    result.add("maps/*.bsp")

    logger.debug(
        "get_known_entry_points: returning %d entries for game '%s'",
        len(result),
        game,
    )
    return result


def classify_entry_point(path: str) -> str:
    """Classify an entry point path into a source_type label.

    Returns one of: ``manifest``, ``map``, ``mission``, ``soundscape``,
    ``level_sounds``, ``population``, ``script``, or ``user_specified``.
    """
    lower = path.lower()
    if "manifest" in lower:
        return "manifest"
    if lower.endswith(".bsp"):
        return "map"
    if lower.startswith("missions/"):
        return "mission"
    if "soundscapes_" in lower and lower.endswith(".txt"):
        return "soundscape"
    if lower.endswith("_level_sounds.txt"):
        return "level_sounds"
    if lower.endswith("population.txt"):
        return "population"
    if lower.endswith(".nut") or lower.startswith("scripts/vscripts/"):
        return "script"
    if lower in (
        "cfg/config.cfg",
        "cfg/autoexec.cfg",
        "gameinfo.txt",
        "scripts/sound_prefetch.txt",
    ):
        return "script"
    return "user_specified"
