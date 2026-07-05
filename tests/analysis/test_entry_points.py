"""Tests for parallelines.analysis.entry_points — discover_entry_points & filter_entry_points."""

from __future__ import annotations

from parallelines.analysis.entry_points import (
    discover_entry_points,
    filter_entry_points,
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
