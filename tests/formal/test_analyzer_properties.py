"""Hypothesis property-based tests for analyzer invariants.

Tests verify formal properties of the analysis pipeline:
    - Redundancy soundness: every redundant file has a higher-priority override
    - Dead-file soundness:   every dead-marked file is unreachable from entry points
    - Completeness (negatives): unique paths => no redundancy;
      all-reachable graph => no dead files
"""

from __future__ import annotations

import string

from hypothesis import assume, given, settings, HealthCheck
from hypothesis import strategies as st

from parallelines.analysis.dead_file import DeadFileAnalyzer
from parallelines.analysis.redundancy import RedundancyAnalyzer
from parallelines.engine import ResultStore
from parallelines.engine.schema import FileRow
from parallelines.engine.store import Relation
from parallelines.graph.deps import DependencyGraph
from parallelines.types import FileNode
from parallelines.vfs.filesystem import VirtualFileSystem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_mini_vfs(
    files: list[tuple[str, str, int]] | list[tuple[str, str, int, bool]],
    *,
    is_enabled: bool = True,
) -> VirtualFileSystem:
    """Build and resolve a VFS from 3 or 4-tuples.

    Supports: ``(virtual_path, source_name, priority)`` or
    ``(virtual_path, source_name, priority, is_enabled)``.
    """
    vfs = VirtualFileSystem()
    for entry in files:
        if len(entry) == 4:
            path, src, pri, enabled = entry
        else:
            path, src, pri = entry
            enabled = is_enabled
        vfs.add_file(FileNode(
            virtual_path=path,
            source_type="test",
            source_name=src,
            priority=pri,
            is_enabled=enabled,
        ))
    vfs.resolve()
    return vfs


def build_store_from_vfs(vfs: VirtualFileSystem) -> ResultStore:
    """Build a ResultStore with files populated from *vfs*.

    ``is_active`` mirrors ``not node.is_redundant``, following the convention
    from the existing unit tests and ``ResultStore.from_analysis``.
    """
    store = ResultStore()
    rows = [
        FileRow(
            virtual_path=n.virtual_path,
            source_name=n.source_name,
            source_type=n.source_type,
            priority=n.priority,
            file_hash=n.file_hash or "",
            file_size=n.file_size,
            is_active=not n.is_redundant,
            is_redundant=n.is_redundant,
            is_enabled=n.is_enabled,
            is_disabled_addon=n.is_disabled_addon,
        )
        for n in vfs.get_all_files()
    ]
    store.files = Relation[FileRow].from_rows("files", rows)
    return store


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

_ASCII = string.ascii_lowercase


@st.composite
def redundant_file_lists(draw) -> list[tuple[str, str, int, bool]]:
    """Generate a list of (path, source_name, priority, is_enabled) with shared paths.

    A small pool of paths is created, with 1-3 files per path.  Roughly 20%
    of files are disabled to test that ``RedundancyAnalyzer`` handles disabled
    sources correctly.
    """
    n_paths = draw(st.integers(min_value=1, max_value=5))
    paths = [f"p{i}" for i in range(n_paths)]

    specs: list[tuple[str, str, int, bool]] = []
    for path in paths:
        n_copies = draw(st.integers(min_value=1, max_value=3))
        for _ in range(n_copies):
            src = draw(st.text(min_size=1, max_size=8, alphabet=_ASCII))
            pri = draw(st.integers(min_value=0, max_value=100))
            enabled = draw(st.booleans()) if n_copies > 1 else True
            specs.append((path, src, pri, enabled))
    return specs


@st.composite
def paths_edges_and_entry_points(draw):
    """Generate a random scenario for dead-file analysis.

    Returns ``(paths, edges, entry_points)`` where:
    * ``paths`` -- a list of distinct virtual paths (size 2-8); at least 2 so
      non-entry-point paths always exist.
    * ``edges`` -- a list of ``(source, target)`` tuples (may include self-loops).
    * ``entry_points`` -- a non-empty strict subset of ``paths``.
    """
    n_paths = draw(st.integers(min_value=2, max_value=8))
    paths = draw(st.lists(
        st.text(min_size=1, max_size=10, alphabet=_ASCII),
        min_size=n_paths,
        max_size=n_paths,
        unique=True,
    ))

    edges = draw(st.lists(
        st.tuples(st.sampled_from(paths), st.sampled_from(paths)),
        min_size=0,
        max_size=20,
    ))

    n_entry = draw(st.integers(min_value=1, max_value=n_paths - 1))
    entry_points = set(draw(st.lists(
        st.sampled_from(paths),
        min_size=n_entry,
        max_size=n_entry,
        unique=True,
    )))
    return paths, edges, entry_points


# ---------------------------------------------------------------------------
# Properties: Redundancy
# ---------------------------------------------------------------------------


class TestRedundancyProperties:
    """Property-based tests for RedundancyAnalyzer."""

    @settings(suppress_health_check=[HealthCheck.too_slow])
    @given(specs=redundant_file_lists())
    def test_redundant_file_has_higher_priority_override(
        self,
        specs: list[tuple[str, str, int, bool]],
    ) -> None:
        """Property: every redundant file has a higher-priority active winner at the same path."""
        vfs = build_mini_vfs(specs)
        redundant = [n for n in vfs.get_all_files() if n.is_redundant]
        enabled_redundant = [n for n in redundant if n.is_enabled]
        assume(len(enabled_redundant) > 0)

        store = build_store_from_vfs(vfs)
        RedundancyAnalyzer().analyze(vfs, None, store)

        assert store.files is not None
        for row in store.files.rows:
            if not row.is_redundant or not row.is_enabled:
                continue

            winner = vfs.get_active_file(row.virtual_path)
            assert winner is not None, (
                f"Redundant file {row.virtual_path!r} (src={row.source_name}) "
                f"has no active winner"
            )
            assert winner.priority >= row.priority, (
                f"Redundant file {row.virtual_path!r} (src={row.source_name}, "
                f"pri={row.priority}) has higher priority than winner "
                f"{winner.source_name} (pri={winner.priority})"
            )

    @settings(suppress_health_check=[HealthCheck.too_slow])
    @given(specs=redundant_file_lists())
    def test_no_redundant_when_all_unique_paths(
        self,
        specs: list[tuple[str, str, int, bool]],
    ) -> None:
        """Property: when every virtual path appears exactly once, zero files are redundant."""
        seen: set[str] = set()
        unique_specs: list[tuple[str, str, int, bool]] = []
        for entry in specs:
            path = entry[0]
            if path not in seen:
                seen.add(path)
                unique_specs.append(entry)

        assume(len(unique_specs) >= 1)

        vfs = build_mini_vfs(unique_specs)
        store = build_store_from_vfs(vfs)
        RedundancyAnalyzer().analyze(vfs, None, store)

        assert store.files is not None
        redundant = [r for r in store.files.rows if r.is_redundant]
        assert len(redundant) == 0, (
            f"Expected 0 redundant files with unique paths, "
            f"got {len(redundant)}: "
            f"{[(r.virtual_path, r.source_name) for r in redundant]}"
        )


# ---------------------------------------------------------------------------
# Properties: Dead files
# ---------------------------------------------------------------------------


class TestDeadFileProperties:
    """Property-based tests for DeadFileAnalyzer."""

    @settings(suppress_health_check=[HealthCheck.too_slow])
    @given(scenario=paths_edges_and_entry_points())
    def test_dead_files_soundness(self, scenario):
        """Property: every file marked dead is unreachable from any entry point."""
        paths, edges, entry_points = scenario

        vfs = VirtualFileSystem()
        for p in paths:
            vfs.add_file(FileNode(p, "test", f"src_{p}", priority=10))
        vfs.resolve()

        graph = DependencyGraph()
        graph.add_edges(edges)

        store = build_store_from_vfs(vfs)
        analyzer = DeadFileAnalyzer(entry_points=entry_points)
        analyzer.analyze(vfs, graph, store)

        # Independent iterative BFS oracle (no dependency on
        # graph.reachable_from_all(), which is what the analyzer uses internally)
        edges = set(graph.graph.edges())
        bfs_reachable: set[str] = set()
        queue = list(entry_points)
        visited: set[str] = set(entry_points)
        while queue:
            current = queue.pop(0)
            for src, dst in edges:
                if src == current and dst not in visited:
                    visited.add(dst)
                    bfs_reachable.add(dst)
                    queue.append(dst)
        live = entry_points | bfs_reachable

        assert store.files is not None
        for row in store.files.rows:
            if row.is_dead:
                assert row.virtual_path not in live, (
                    f"File {row.virtual_path!r} marked dead but its path IS in "
                    f"the live set (entry_points={entry_points}, "
                    f"bfs_reachable={bfs_reachable})"
                )

    @settings(suppress_health_check=[HealthCheck.too_slow])
    @given(paths=st.lists(
        st.text(min_size=1, max_size=10, alphabet=_ASCII),
        min_size=1,
        max_size=10,
        unique=True,
    ))
    def test_no_dead_when_all_reachable(self, paths):
        """Property: in a star graph where every file is reachable, no files are dead."""
        entry = paths[0]

        vfs = VirtualFileSystem()
        for p in paths:
            vfs.add_file(FileNode(p, "test", "src", priority=10))
        vfs.resolve()

        graph = DependencyGraph()
        graph.add_node(entry)
        if len(paths) > 1:
            edges = [(entry, p) for p in paths[1:]]
            graph.add_edges(edges)

            store = build_store_from_vfs(vfs)
            analyzer = DeadFileAnalyzer(entry_points={entry})
            analyzer.analyze(vfs, graph, store)

            assert store.files is not None
            dead = [r for r in store.files.rows if r.is_dead]
            assert len(dead) == 0, (
                f"Expected 0 dead files in all-reachable graph, "
                f"got {len(dead)}: "
                f"{[(r.virtual_path, r.source_name) for r in dead]}"
            )
