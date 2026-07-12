"""Tests for parallelines.analysis.entry_points — discover_entry_points & filter_entry_points."""

from __future__ import annotations

from parallelines.analysis.entry_points import (
    classify_entry_point,
    discover_entry_points,
    filter_entry_points,
    get_known_entry_points,
)
from parallelines.graph.deps import DependencyGraph
from parallelines.types import FileNode
from parallelines.vfs.filesystem import VirtualFileSystem


def test_discover_returns_set() -> None:
    """Basic call with VFS containing gameinfo.txt returns a non-empty set."""
    vfs = VirtualFileSystem()
    vfs.add_file(FileNode("gameinfo.txt", "game", "base", priority=10))
    vfs.resolve()

    result = discover_entry_points(vfs)
    assert isinstance(result, set)
    assert "gameinfo.txt" in result


def test_discover_empty_vfs() -> None:
    """vfs=None returns empty set."""
    result = discover_entry_points(None)
    assert result == set()


def test_filter_entry_points() -> None:
    """Remove entry points with no outgoing edges."""
    graph = DependencyGraph()
    graph.add_edges([("a.txt", "b.txt")])

    result = filter_entry_points({"a.txt", "c.txt"}, None, graph)
    assert "a.txt" in result
    assert "c.txt" not in result


def test_filter_no_match() -> None:
    """All entry points have no outgoing edges -> empty set."""
    graph = DependencyGraph()
    graph.add_node("a.txt")

    result = filter_entry_points({"a.txt"}, None, graph)
    assert result == set()


# ── Helper ─────────────────────────────────────────────────────────────────


def _make_vfs(paths: list[str]) -> VirtualFileSystem:
    """Build a minimal VFS from a list of virtual paths."""
    vfs = VirtualFileSystem()
    for p in paths:
        vfs.add_file(FileNode(p, "game", "test", priority=10))
    vfs.resolve()
    return vfs


# ── discover_entry_points ──────────────────────────────────────────────────


def test_discover_additive_mr() -> None:
    """Additive MR: more active files => entry_points is a superset."""
    vfs_a = _make_vfs(["gameinfo.txt"])
    vfs_b = _make_vfs(["gameinfo.txt", "particles/particles_manifest.txt"])

    result_a = discover_entry_points(vfs_a)
    result_b = discover_entry_points(vfs_b)

    assert result_a.issubset(result_b)
    assert "particles/particles_manifest.txt" in result_b


def test_discover_no_active_files() -> None:
    """Edge case: VFS exists but has zero active files => empty set."""
    vfs = VirtualFileSystem()
    vfs.resolve()
    assert discover_entry_points(vfs) == set()


def test_discover_manifest() -> None:
    """Additive MR: manifest file present => manifest path in entry points."""
    vfs = _make_vfs(["gameinfo.txt", "particles/particles_manifest.txt"])
    result = discover_entry_points(vfs)
    assert "particles/particles_manifest.txt" in result


def test_discover_bsp() -> None:
    """BSP files are NOT entry points by default (no outgoing edges).

    Use --all-maps (bsp_limit=-1) or --maps to include them.
    """
    vfs = _make_vfs(["gameinfo.txt", "maps/c1m1_hotel.bsp"])
    result = discover_entry_points(vfs)
    assert "maps/c1m1_hotel.bsp" not in result
    # With explicit bsp_limit=-1 (--all-maps), they are included
    result_all = discover_entry_points(vfs, bsp_limit=-1)
    assert "maps/c1m1_hotel.bsp" in result_all


def test_discover_soundscapes_auto() -> None:
    """Compositional MR: .bsp + matching soundscapes map => soundscapes discovered."""
    vfs = _make_vfs([
        "gameinfo.txt",
        "maps/c1m1_hotel.bsp",
        "scripts/soundscapes_c1m1_hotel.txt",
    ])
    result = discover_entry_points(vfs)
    assert "scripts/soundscapes_c1m1_hotel.txt" in result


def test_discover_level_sounds_auto() -> None:
    """Compositional MR: .bsp + matching _level_sounds.txt => level_sounds discovered."""
    vfs = _make_vfs([
        "gameinfo.txt",
        "maps/c1m1_hotel.bsp",
        "maps/c1m1_hotel_level_sounds.txt",
    ])
    result = discover_entry_points(vfs)
    assert "maps/c1m1_hotel_level_sounds.txt" in result


def test_discover_vscripts() -> None:
    """Additive MR: any .nut under scripts/vscripts/ => discovered as entry point."""
    vfs = _make_vfs(["gameinfo.txt", "scripts/vscripts/mylib.nut"])
    result = discover_entry_points(vfs)
    assert "scripts/vscripts/mylib.nut" in result


def test_discover_missions() -> None:
    """Additive MR: any missions/*.txt => discovered as entry point."""
    vfs = _make_vfs(["gameinfo.txt", "missions/campaign.txt"])
    result = discover_entry_points(vfs)
    assert "missions/campaign.txt" in result


# ── filter_entry_points ────────────────────────────────────────────────────


def test_filter_additive_mr() -> None:
    """Additive MR: more graph edges => fewer (or equal) entry points removed."""
    eps = {"a.txt", "c.txt", "e.txt"}
    graph = DependencyGraph()
    graph.add_edges([("a.txt", "b.txt"), ("c.txt", "d.txt")])

    result_a = filter_entry_points(eps, None, graph)
    assert "e.txt" not in result_a  # no outgoing edge => removed

    graph.add_edges([("e.txt", "f.txt")])
    result_b = filter_entry_points(eps, None, graph)
    assert "e.txt" in result_b  # now has an edge => kept

    assert result_a.issubset(result_b)


def test_filter_all_have_edges() -> None:
    """All entry points present in graph with outgoing edges => none removed."""
    graph = DependencyGraph()
    graph.add_edges([("a.txt", "b.txt"), ("c.txt", "d.txt")])
    result = filter_entry_points({"a.txt", "c.txt"}, None, graph)
    assert result == {"a.txt", "c.txt"}


def test_filter_graph_none() -> None:
    """Guard: graph=None returns the original set unchanged."""
    eps = {"a.txt", "b.txt"}
    assert filter_entry_points(eps, None, None) == eps


def test_filter_empty_input() -> None:
    """Guard: empty entry_points set returns empty set."""
    graph = DependencyGraph()
    graph.add_edges([("a.txt", "b.txt")])
    assert filter_entry_points(set(), None, graph) == set()


# ── classify_entry_point ───────────────────────────────────────────────────


def test_classify_manifest() -> None:
    """Permutative MR: classification is case-insensitive for manifest paths."""
    assert classify_entry_point("particles/particles_manifest.txt") == "manifest"
    assert classify_entry_point("PARTICLES/PARTICLES_MANIFEST.TXT") == "manifest"


def test_classify_map() -> None:
    """Permutative MR: case permutation & dir prefix do not change map classification."""
    assert classify_entry_point("maps/c1m1_hotel.bsp") == "map"
    assert classify_entry_point("other/random.bsp") == "map"
    assert classify_entry_point("MAPS/C1M1_HOTEL.BSP") == "map"


def test_classify_mission() -> None:
    """Prefix MR: paths under missions/ directory => 'mission'."""
    assert classify_entry_point("missions/campaign.txt") == "mission"
    assert classify_entry_point("MISSIONS/CAMPAIGN.TXT") == "mission"


def test_classify_soundscape() -> None:
    """Permutative MR: soundscapes_ in path => 'soundscape', regardless of case."""
    assert classify_entry_point("scripts/soundscapes_c1m1.txt") == "soundscape"
    assert classify_entry_point("SCRIPTS/SOUNDSCAPES_C1M1.TXT") == "soundscape"


def test_classify_level_sounds() -> None:
    """Suffix MR: _level_sounds.txt suffix => 'level_sounds'."""
    assert classify_entry_point("maps/c1m1_level_sounds.txt") == "level_sounds"
    assert classify_entry_point("MAPS/C1M1_LEVEL_SOUNDS.TXT") == "level_sounds"


def test_classify_population() -> None:
    """Suffix MR: population.txt suffix => 'population'."""
    assert classify_entry_point("scripts/population.txt") == "population"
    assert classify_entry_point("SCRIPTS/POPULATION.TXT") == "population"


def test_classify_script() -> None:
    """Permutative MR: .nut files and well-known script paths => 'script'."""
    assert classify_entry_point("scripts/vscripts/mylib.nut") == "script"
    assert classify_entry_point("cfg/config.cfg") == "script"
    assert classify_entry_point("cfg/autoexec.cfg") == "script"
    assert classify_entry_point("gameinfo.txt") == "script"
    assert classify_entry_point("scripts/sound_prefetch.txt") == "script"


def test_classify_user_specified() -> None:
    """Fallback: unmatched paths => 'user_specified'."""
    assert classify_entry_point("unknown/file.txt") == "user_specified"
    assert classify_entry_point("data/models/foo.vmdl") == "user_specified"


# ── get_known_entry_points ─────────────────────────────────────────────────


def test_known_empty_game() -> None:
    """Edge case: empty game string returns empty set."""
    assert get_known_entry_points("") == set()
    assert get_known_entry_points(None) == set()  # type: ignore[arg-type]


def test_known_l4d2() -> None:
    """L4D2 known entry points contain default manifests, extra manifests, scripts."""
    result = get_known_entry_points("l4d2")

    # Default auto-manifests
    assert "scripts/soundscapes_manifest.txt" in result
    assert "scripts/game_sounds_manifest.txt" in result
    assert "particles/particles_manifest.txt" in result

    # L4D2-specific extra manifests
    assert "scripts/melee/melee_manifest.txt" in result
    assert "scripts/sprays_manifest.txt" in result

    # Script entries
    assert "scripts/population.txt" in result
    assert "scripts/sound_prefetch.txt" in result

    # Map glob
    assert "maps/*.bsp" in result
