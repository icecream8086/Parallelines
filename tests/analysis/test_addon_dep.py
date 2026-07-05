"""Tests for parallelines.analysis.addon_dep — AddonDependencyAnalyzer."""

from __future__ import annotations

from parallelines.analysis.addon_dep import AddonDependencyAnalyzer
from parallelines.engine import ResultStore
from parallelines.types import FileNode
from parallelines.vfs.filesystem import VirtualFileSystem


def test_empty_vfs() -> None:
    """None VFS should not raise."""
    store = ResultStore()
    AddonDependencyAnalyzer(chain=None).analyze(None, None, store)


def test_no_chain() -> None:
    """chain=None should skip addoninfo parsing, no dep_conflicts added."""
    vfs = VirtualFileSystem()
    vfs.add_file(FileNode("addoninfo.txt", "addon", "test_addon", priority=10))
    vfs.resolve()

    store = ResultStore()
    AddonDependencyAnalyzer(chain=None).analyze(vfs, None, store)

    assert store.dep_conflicts is None or len(store.dep_conflicts.rows) == 0


def test_with_vfs() -> None:
    """Basic VFS without addoninfo files, call analyzer, check no errors."""
    vfs = VirtualFileSystem()
    vfs.add_file(FileNode("a.txt", "game", "base", priority=10))
    vfs.add_file(FileNode("b.txt", "addon", "some_addon", priority=20))
    vfs.resolve()

    store = ResultStore()
    AddonDependencyAnalyzer(chain=None).analyze(vfs, None, store)

    assert store.dep_conflicts is None or len(store.dep_conflicts.rows) == 0
