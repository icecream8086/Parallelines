"""Tests for parallelines.analysis.map_conflict — MapConflictAnalyzer."""

from __future__ import annotations

from parallelines.analysis.map_conflict import MapConflictAnalyzer
from parallelines.engine import ResultStore
from parallelines.types import FileNode
from parallelines.vfs.filesystem import VirtualFileSystem


def test_no_external() -> None:
    """No external_sources, single bsp -> no conflicts."""
    vfs = VirtualFileSystem()
    vfs.add_file(FileNode("maps/c1m1.bsp", "game", "base", priority=10))
    vfs.resolve()

    store = ResultStore()
    MapConflictAnalyzer().analyze(vfs, None, store)

    assert store.hash_conflicts is None or len(store.hash_conflicts.rows) == 0


def test_empty_vfs() -> None:
    """None VFS should not raise."""
    store = ResultStore()
    MapConflictAnalyzer().analyze(None, None, store)
    assert store.hash_conflicts is None


def test_basic_conflict() -> None:
    """Two installed sources for the same bsp with different hashes -> conflict."""
    vfs = VirtualFileSystem()
    vfs.add_file(
        FileNode(
            "maps/c1m1.bsp",
            "addon",
            "addon_a",
            priority=50,
            file_hash="abc123",
        )
    )
    vfs.add_file(
        FileNode(
            "maps/c1m1.bsp",
            "addon",
            "addon_b",
            priority=100,
            file_hash="def456",
        )
    )
    vfs.resolve()

    store = ResultStore()
    analyzer = MapConflictAnalyzer(external_sources={"maps/other.bsp": "ext_vpk"})
    analyzer.analyze(vfs, None, store)

    rows = store.hash_conflicts.rows
    assert len(rows) == 1
    assert rows[0].virtual_path == "maps/c1m1.bsp"
    assert rows[0].winner_source == "addon_b"
    assert rows[0].loser_source == "addon_a"
    assert rows[0].winner_hash == "def456"
    assert rows[0].loser_hash == "abc123"
