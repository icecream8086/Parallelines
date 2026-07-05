"""Tests for parallelines.analysis.dep_conflict — DependencyConflictAnalyzer."""

from __future__ import annotations

from parallelines.analysis.dep_conflict import DependencyConflictAnalyzer
from parallelines.engine import ResultStore
from parallelines.types import FileNode
from parallelines.vfs.filesystem import VirtualFileSystem


def test_missing_dep() -> None:
    """FileNode a.txt depends on "missing.txt" -> DepConflictRow with MISSING."""
    vfs = VirtualFileSystem()
    vfs.add_file(
        FileNode("a.txt", "addon", "addon_a", priority=50, dependencies={"missing.txt"})
    )
    vfs.resolve()

    store = ResultStore()
    DependencyConflictAnalyzer().analyze(vfs, None, store)

    assert store.dep_conflicts is not None
    rows = store.dep_conflicts.rows
    assert len(rows) == 1
    assert rows[0].from_path == "a.txt"
    assert rows[0].to_path == "missing.txt"
    assert rows[0].expected_source == "addon_a"
    assert rows[0].actual_source == "MISSING"


def test_cross_source_dep() -> None:
    """Two file nodes with different source_names -> conflict."""
    vfs = VirtualFileSystem()
    vfs.add_file(
        FileNode("a.txt", "addon", "source_a", priority=50, dependencies={"b.txt"})
    )
    vfs.add_file(FileNode("b.txt", "addon", "source_b", priority=100))
    vfs.resolve()

    store = ResultStore()
    DependencyConflictAnalyzer().analyze(vfs, None, store)

    rows = store.dep_conflicts.rows
    assert len(rows) == 1
    assert rows[0].from_path == "a.txt"
    assert rows[0].to_path == "b.txt"
    assert rows[0].expected_source == "source_a"
    assert rows[0].actual_source == "source_b"


def test_same_source_dep() -> None:
    """Two file nodes with same source_name -> no conflict."""
    vfs = VirtualFileSystem()
    vfs.add_file(
        FileNode("a.txt", "addon", "same_source", priority=50, dependencies={"b.txt"})
    )
    vfs.add_file(FileNode("b.txt", "addon", "same_source", priority=100))
    vfs.resolve()

    store = ResultStore()
    DependencyConflictAnalyzer().analyze(vfs, None, store)

    assert store.dep_conflicts is None or len(store.dep_conflicts.rows) == 0


def test_empty_vfs() -> None:
    """None VFS should not raise."""
    store = ResultStore()
    DependencyConflictAnalyzer().analyze(None, None, store)
    assert store.dep_conflicts is None


def test_no_deps() -> None:
    """File with empty dependencies set -> no conflict."""
    vfs = VirtualFileSystem()
    vfs.add_file(FileNode("a.txt", "game", "base", priority=10))
    vfs.resolve()

    store = ResultStore()
    DependencyConflictAnalyzer().analyze(vfs, None, store)

    assert store.dep_conflicts is None or len(store.dep_conflicts.rows) == 0
