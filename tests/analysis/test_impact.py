"""Tests for parallelines.analysis.impact — ImpactAnalyzer."""

from __future__ import annotations

from parallelines.analysis.impact import ImpactAnalyzer
from parallelines.engine import FileRow, Relation, ResultStore
from parallelines.graph.deps import DependencyGraph
from parallelines.types import FileNode
from parallelines.vfs.filesystem import VirtualFileSystem


def _build_store(vfs: VirtualFileSystem) -> ResultStore:
    """Build a ResultStore with files populated from VFS."""
    store = ResultStore()
    file_rows = [
        FileRow(
            virtual_path=node.virtual_path,
            source_name=node.source_name,
            source_type=node.source_type,
            priority=node.priority,
            file_hash=node.file_hash or "",
            file_size=node.file_size,
            is_active=not node.is_redundant,
        )
        for node in vfs.get_all_files()
    ]
    store.files = Relation.from_rows("files", file_rows)
    return store


def test_normal_case() -> None:
    """3 files (a->b->c), impact rows sorted by count desc."""
    vfs = VirtualFileSystem()
    vfs.add_file(FileNode("a.txt", "game", "base", priority=10))
    vfs.add_file(FileNode("b.txt", "game", "base", priority=10))
    vfs.add_file(FileNode("c.txt", "game", "base", priority=10))
    vfs.resolve()

    graph = DependencyGraph()
    graph.add_edges([("a.txt", "b.txt"), ("b.txt", "c.txt")])

    store = _build_store(vfs)
    ImpactAnalyzer(top_n=10).analyze(vfs, graph, store)

    assert store.impact is not None
    rows = store.impact.rows
    assert len(rows) == 3
    # a.txt has 2 descendants (b.txt, c.txt)
    assert rows[0].virtual_path == "a.txt"
    assert rows[0].impact_count == 2
    # b.txt has 1 descendant (c.txt)
    assert rows[1].virtual_path == "b.txt"
    assert rows[1].impact_count == 1
    # c.txt has 0 descendants
    assert rows[2].virtual_path == "c.txt"
    assert rows[2].impact_count == 0


def test_top_n() -> None:
    """Many files with top_n=2, only 2 impact rows returned."""
    n_files = 10
    vfs = VirtualFileSystem()
    for i in range(n_files):
        vfs.add_file(FileNode(f"file_{i}.txt", "game", "base", priority=10))
    vfs.resolve()

    graph = DependencyGraph()
    for i in range(n_files - 1):
        graph.add_edges([(f"file_{i}.txt", f"file_{i + 1}.txt")])

    store = _build_store(vfs)
    ImpactAnalyzer(top_n=2).analyze(vfs, graph, store)

    rows = store.impact.rows
    assert len(rows) == 2
    assert rows[0].impact_count >= rows[1].impact_count


def test_empty_vfs() -> None:
    """None VFS / graph should not raise."""
    store = ResultStore()
    ImpactAnalyzer().analyze(None, None, store)
    assert store.impact is None
