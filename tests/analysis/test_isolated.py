"""Tests for parallelines.analysis.isolated — IsolatedPackageAnalyzer."""

from __future__ import annotations

from parallelines.analysis.isolated import IsolatedPackageAnalyzer
from parallelines.engine import ResultStore
from parallelines.types import FileNode
from parallelines.vfs.filesystem import VirtualFileSystem


def test_normal_case() -> None:
    """2 files from same source, both redundant -> dead_file_count=2."""
    vfs = VirtualFileSystem()
    vfs.add_file(FileNode("a.txt", "addon", "addon_x", priority=10))
    vfs.add_file(FileNode("a.txt", "addon", "addon_y", priority=50))
    vfs.add_file(FileNode("b.txt", "addon", "addon_x", priority=10))
    vfs.add_file(FileNode("b.txt", "addon", "addon_y", priority=50))
    vfs.resolve()

    store = ResultStore()
    IsolatedPackageAnalyzer().analyze(vfs, None, store)

    rows = store.isolated.rows
    assert len(rows) == 2
    row_x = [r for r in rows if r.source_name == "addon_x"][0]
    row_y = [r for r in rows if r.source_name == "addon_y"][0]
    assert row_x.dead_file_count == 2
    assert row_y.dead_file_count == 0


def test_partial_dead() -> None:
    """2 files same source, 1 dead, 1 live."""
    vfs = VirtualFileSystem()
    a = FileNode("a.txt", "addon", "addon_x", priority=10)
    b = FileNode("b.txt", "addon", "addon_x", priority=10)
    b.is_dead = True
    vfs.add_file(a)
    vfs.add_file(b)

    store = ResultStore()
    IsolatedPackageAnalyzer().analyze(vfs, None, store)

    rows = store.isolated.rows
    assert len(rows) == 1
    assert rows[0].source_name == "addon_x"
    assert rows[0].dead_file_count == 1
    assert rows[0].example_paths == ["b.txt"]


def test_no_dead() -> None:
    """No dead or redundant files -> dead_file_count 0."""
    vfs = VirtualFileSystem()
    vfs.add_file(FileNode("a.txt", "addon", "addon_x", priority=10))
    vfs.add_file(FileNode("b.txt", "addon", "addon_x", priority=10))

    store = ResultStore()
    IsolatedPackageAnalyzer().analyze(vfs, None, store)

    rows = store.isolated.rows
    assert len(rows) == 1
    assert rows[0].source_name == "addon_x"
    assert rows[0].dead_file_count == 0
    assert rows[0].example_paths == []


def test_empty_vfs() -> None:
    """None VFS should not raise."""
    store = ResultStore()
    IsolatedPackageAnalyzer().analyze(None, None, store)
    assert store.isolated is None
