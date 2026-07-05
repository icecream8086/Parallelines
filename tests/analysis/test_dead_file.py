"""Tests for parallelines.analysis.dead_file — DeadFileAnalyzer."""

from __future__ import annotations

from parallelines.analysis.dead_file import DeadFileAnalyzer
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
    """a depends on b (edge a->b), entry_points={"a"} -> c is dead, b is live via transit."""
    vfs = VirtualFileSystem()
    vfs.add_file(FileNode("a.txt", "game", "base", priority=10, dependencies={"b.txt"}))
    vfs.add_file(FileNode("b.txt", "game", "base", priority=10))
    vfs.add_file(FileNode("c.txt", "game", "base", priority=10))
    vfs.resolve()

    graph = DependencyGraph()
    graph.add_edges([("a.txt", "b.txt")])

    store = _build_store(vfs)
    analyzer = DeadFileAnalyzer(entry_points={"a.txt"})
    analyzer.analyze(vfs, graph, store)

    dead = [r for r in store.files.rows if r.is_dead]
    live = [r for r in store.files.rows if not r.is_dead]
    assert len(dead) == 1
    assert dead[0].virtual_path == "c.txt"
    assert {r.virtual_path for r in live} == {"a.txt", "b.txt"}


def test_empty_vfs() -> None:
    """None VFS / graph should not raise."""
    analyzer = DeadFileAnalyzer(entry_points={"a.txt"})
    store = ResultStore()
    analyzer.analyze(None, None, store)


def test_no_entry_points() -> None:
    """entry_points=None -> all files live (none marked dead)."""
    vfs = VirtualFileSystem()
    vfs.add_file(FileNode("a.txt", "game", "base", priority=10, dependencies={"b.txt"}))
    vfs.add_file(FileNode("b.txt", "game", "base", priority=10))
    vfs.resolve()

    graph = DependencyGraph()
    graph.add_edges([("a.txt", "b.txt")])

    store = _build_store(vfs)
    analyzer = DeadFileAnalyzer(entry_points=None)
    analyzer.analyze(vfs, graph, store)

    dead = [r for r in store.files.rows if r.is_dead]
    assert len(dead) == 0


def test_all_reachable() -> None:
    """Single file with entry_points={"a.txt"} -> not dead."""
    vfs = VirtualFileSystem()
    vfs.add_file(FileNode("a.txt", "game", "base", priority=10))
    vfs.resolve()

    graph = DependencyGraph()
    graph.add_node("a.txt")

    store = _build_store(vfs)
    analyzer = DeadFileAnalyzer(entry_points={"a.txt"})
    analyzer.analyze(vfs, graph, store)

    dead = [r for r in store.files.rows if r.is_dead]
    assert len(dead) == 0


def test_partial_reachable() -> None:
    """2 entry points, only unreachable file is dead."""
    vfs = VirtualFileSystem()
    vfs.add_file(FileNode("a.txt", "game", "base", priority=10))
    vfs.add_file(FileNode("b.txt", "game", "base", priority=10))
    vfs.add_file(FileNode("c.txt", "game", "base", priority=10))
    vfs.resolve()

    graph = DependencyGraph()
    graph.add_node("a.txt")
    graph.add_node("b.txt")

    store = _build_store(vfs)
    analyzer = DeadFileAnalyzer(entry_points={"a.txt", "b.txt"})
    analyzer.analyze(vfs, graph, store)

    dead = [r for r in store.files.rows if r.is_dead]
    assert len(dead) == 1
    assert dead[0].virtual_path == "c.txt"
