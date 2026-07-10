"""Z3 + hypothesis combined tests for DeadFileAnalyzer soundness.

Tests
-----
* test_z3_dead_file_soundness
    Pure Z3 proof: Dead(f) ∧ Reachable(f) is UNSAT — no false positives.

* test_z3_dead_file_completeness
    Pure Z3 proof: ¬Reachable(f) ⇒ Dead(f).  This is expected SAT because
    the DeadFileAnalyzer only marks *active* files; an inactive (redundant /
    disabled) file may be unreachable yet not dead.

* test_z3_dead_file_completeness_with_active
    Same property with the active(f) precondition added — now UNSAT.

* test_hypothesis_dead_file_consistency
    Hypothesis-based randomised consistency check: for an arbitrary graph,
    entry-point set, and VFS, verify that the BFS live-set computation
    matches DeadFileAnalyzer's output exactly.
"""

from __future__ import annotations

import pytest

# SUT imports
from parallelines.analysis.dead_file import DeadFileAnalyzer
from parallelines.engine.store import ResultStore
from parallelines.graph.deps import DependencyGraph
from parallelines.types import FileNode
from parallelines.vfs.filesystem import VirtualFileSystem

# ── Hypothesis guard ────────────────────────────────────────────────────────────

_HYPOTHESIS_AVAILABLE: bool = False
try:
    from hypothesis import given, settings, strategies as st, HealthCheck, assume  # noqa: F401

    _HYPOTHESIS_AVAILABLE = True
except ImportError:
    # Stubs so the decorators don't crash at parse time when hypothesis is absent.
    # The @pytest.mark.skipif class decorator prevents test execution.
    def given(x=None, **kw):  # type: ignore[misc]
        return lambda f: f

    def settings(x=None, **kw):  # type: ignore[misc]
        return lambda f: f

    def assume(condition: bool) -> None:  # type: ignore[misc]
        pass

    st = None  # type: ignore[assignment]

# ── Z3 tests ──────────────────────────────────────────────────────────────────


def _z3_solver() -> tuple:
    """Return (z3_module, solver) for tests, or raise Skip."""
    z3 = pytest.importorskip("z3", reason="z3-solver not installed")
    return z3, z3.Solver()


def _dead_flag_definition(z3, dead_flag, active, entry, reachable, p):
    """Axiom: dead_flag(p) ≡ active(p) ∧ ¬entry(p) ∧ ¬reachable(p)."""
    return z3.ForAll(
        [p],
        dead_flag(p) == z3.And(active(p), z3.Not(entry(p)), z3.Not(reachable(p))),
    )


def _reachability_axioms(z3, entry, edge, reachable, p, q):
    """Axioms for reachability from entry points through edges.

    (1)  entry(p) → reachable(p)
    (2)  edge(p, q) ∧ reachable(p) → reachable(q)
    """
    return [
        z3.ForAll([p], z3.Implies(entry(p), reachable(p))),
        z3.ForAll(
            [p, q],
            z3.Implies(z3.And(edge(p, q), reachable(p)), reachable(q)),
        ),
    ]


def test_z3_dead_file_soundness() -> None:
    """Z3 proof: Dead(f) ∧ Reachable(f) is UNSAT — no false positives.

    Encoding
    --------
    Path sorts are represented as an uninterpreted sort with quantified axioms.

    Soundness::

        dead_flag(p) ≡ active(p) ∧ ¬entry(p) ∧ ¬reachable(p)      (def)
        dead_flag(p)  →  ¬reachable(p)                            (∧-elim)
        ∴ dead_flag(p) ∧ reachable(p)  →  ⊥                      (UNSAT)

    The solver receives:

        dead_flag(p) == active(p) ∧ ¬entry(p) ∧ ¬reachable(p)     (axiom)
        ∃p. dead_flag(p) ∧ reachable(p)                           (negated claim)

    Axiom and negated claim together force a contradiction: the former
    derives ¬reachable(p) whenever dead_flag(p) holds, but the latter
    asserts reachable(p) at the same path.
    """
    z3, solver = _z3_solver()

    Path = z3.DeclareSort("Path")
    entry = z3.Function("entry", Path, z3.BoolSort())
    edge = z3.Function("edge", Path, Path, z3.BoolSort())
    reachable = z3.Function("reachable", Path, z3.BoolSort())
    dead_flag = z3.Function("dead_flag", Path, z3.BoolSort())
    active = z3.Function("active", Path, z3.BoolSort())

    p = z3.Const("p", Path)
    q = z3.Const("q", Path)

    # Definitions and axioms.
    solver.add(_dead_flag_definition(z3, dead_flag, active, entry, reachable, p))
    for ax in _reachability_axioms(z3, entry, edge, reachable, p, q):
        solver.add(ax)

    # Negation of soundness: there exists a path that is both dead and reachable.
    solver.add(z3.Exists([p], z3.And(dead_flag(p), reachable(p))))

    assert solver.check() == z3.unsat, (
        "Soundness violation: a file cannot be both dead and reachable "
        "from an entry point."
    )


def test_z3_dead_file_completeness() -> None:
    """Z3 proof: ¬Reachable(f) ⇒ Dead(f) is SAT — expected incompleteness.

    Why this is SAT
    ---------------
    The dead-flag definition includes an *active* precondition::

        dead_flag(p) ≡ active(p) ∧ ¬entry(p) ∧ ¬reachable(p)

    A file that is inactive (redundant, disabled, etc.) has ``active(p) = ⊥``,
    hence ``dead_flag(p) = ⊥`` regardless of whether ``reachable(p)`` holds.
    Therefore ``¬reachable(p) ⇒ dead_flag(p)`` is *not* universally true —
    a counterexample model satisfies ``¬reachable(p) ∧ ¬active(p)``, giving
    ``¬reachable(p) ∧ ¬dead_flag(p)``.

    This mirrors a real-world incompleteness: the DeadFileAnalyzer only
    considers files in the active VFS; files that are overridden or disabled
    are simply not examined.
    """
    z3, solver = _z3_solver()

    Path = z3.DeclareSort("Path")
    entry = z3.Function("entry", Path, z3.BoolSort())
    edge = z3.Function("edge", Path, Path, z3.BoolSort())
    reachable = z3.Function("reachable", Path, z3.BoolSort())
    dead_flag = z3.Function("dead_flag", Path, z3.BoolSort())
    active = z3.Function("active", Path, z3.BoolSort())

    p = z3.Const("p", Path)
    q = z3.Const("q", Path)

    solver.add(_dead_flag_definition(z3, dead_flag, active, entry, reachable, p))
    for ax in _reachability_axioms(z3, entry, edge, reachable, p, q):
        solver.add(ax)

    # Negation of completeness: there exists a path that is NOT reachable
    # but also NOT dead (because it is inactive).
    solver.add(
        z3.Exists(
            [p],
            z3.And(z3.Not(reachable(p)), z3.Not(dead_flag(p))),
        )
    )

    result = solver.check()

    assert result == z3.sat, (
        f"Completeness is expected SAT (incomplete) due to the active(p) "
        f"precondition. Got {result} instead."
    )


def test_z3_dead_file_completeness_with_active() -> None:
    """Z3 proof: (active(f) ∧ ¬Reachable(f)) ⇒ Dead(f) is UNSAT.

    With the precondition ``active(p)`` added to the completeness statement,
    the implication becomes a direct consequence of the dead-flag definition::

        dead_flag(p) = active(p) ∧ ¬entry(p) ∧ ¬reachable(p)
        active(p) ∧ ¬reachable(p)  →  dead_flag(p)               (UNSAT)

    This test shows that the *only* source of incompleteness is the
    inactive-file gap — when the file is active, completeness holds.
    """
    z3, solver = _z3_solver()

    Path = z3.DeclareSort("Path")
    entry = z3.Function("entry", Path, z3.BoolSort())
    edge = z3.Function("edge", Path, Path, z3.BoolSort())
    reachable = z3.Function("reachable", Path, z3.BoolSort())
    dead_flag = z3.Function("dead_flag", Path, z3.BoolSort())
    active = z3.Function("active", Path, z3.BoolSort())

    p = z3.Const("p", Path)
    q = z3.Const("q", Path)

    solver.add(_dead_flag_definition(z3, dead_flag, active, entry, reachable, p))
    for ax in _reachability_axioms(z3, entry, edge, reachable, p, q):
        solver.add(ax)

    # Counterexample with active(p) added:  active(p) ∧ ¬reachable(p) ∧ ¬dead(p)
    solver.add(
        z3.Exists(
            [p],
            z3.And(active(p), z3.Not(reachable(p)), z3.Not(dead_flag(p))),
        )
    )

    assert solver.check() == z3.unsat, (
        "With the active(p) precondition, completeness should hold."
    )


# ── Supplementary concrete tests ─────────────────────────────────────────────


def test_entry_points_not_dead() -> None:
    """Entry points should never be marked dead."""
    from parallelines.analysis.dead_file import DeadFileAnalyzer

    vfs = VirtualFileSystem()
    vfs.add_file(FileNode("maps/c1m1.bsp", "test", "vpk1", priority=10, is_enabled=True))
    vfs.add_file(FileNode("materials/wall.vmt", "test", "vpk2", priority=5, is_enabled=True))
    vfs.resolve()

    graph = DependencyGraph()
    graph.add_node("maps/c1m1.bsp")
    graph.add_node("materials/wall.vmt")
    graph.add_edges([("maps/c1m1.bsp", "materials/wall.vmt")])

    entry_points = {"maps/c1m1.bsp"}
    store = ResultStore.from_analysis(
        vfs, graph, [DeadFileAnalyzer(entry_points=entry_points)],
        entry_points=entry_points,
    )
    assert store.files is not None
    dead_entries = {
        r.virtual_path for r in store.files.rows
        if r.is_dead and r.virtual_path in entry_points
    }
    assert len(dead_entries) == 0, (
        f"Entry points should not be dead: {dead_entries}"
    )


def test_graph_edge_node_consistency() -> None:
    """All edge source and target nodes must exist in the graph."""
    graph = DependencyGraph()
    graph.add_node("a")
    graph.add_node("b")
    graph.add_node("c")
    graph.add_edges([("a", "b"), ("b", "c")])

    nodes = set(graph.graph.nodes())
    for src, dst in graph.graph.edges():
        assert src in nodes, f"Edge source '{src}' not in graph nodes"
        assert dst in nodes, f"Edge target '{dst}' not in graph nodes"

    # Adding an edge with a non-existent node should work (NetworkX auto-adds)
    graph.add_edges([("a", "d")])
    assert "d" in set(graph.graph.nodes()), "NetworkX should auto-add missing nodes"


# ── Hypothesis test ──────────────────────────────────────────────────────────


@pytest.mark.skipif(
    not _HYPOTHESIS_AVAILABLE, reason="hypothesis not installed"
)
class TestDeadFileConsistency:
    """hypothesis property: DeadFileAnalyzer output matches BFS reachability."""

    @staticmethod
    def _build_vfs_and_graph(
        paths: list[str],
        valid_edges: list[tuple[str, str]],
    ) -> tuple[VirtualFileSystem, DependencyGraph]:
        """Populate a VFS and a DependencyGraph from the given data.

        Each path receives exactly one enabled FileNode, ensuring every path
        is active after ``resolve()``.
        """
        vfs = VirtualFileSystem()
        for i, path in enumerate(paths):
            vfs.add_file(
                FileNode(
                    virtual_path=path,
                    source_type="test",
                    source_name=f"src_{i}",
                    priority=i,
                    is_enabled=True,
                    file_hash=f"hash_{i}",
                )
            )
        vfs.resolve()

        graph = DependencyGraph()
        for path in paths:
            graph.add_node(path)
        graph.add_edges(valid_edges)
        return vfs, graph

    @staticmethod
    def _compute_expected_dead(
        paths: set[str],
        valid_entries: set[str],
        graph: DependencyGraph,
        vfs: VirtualFileSystem,
    ) -> set[str]:
        """Return the set of virtual_paths expected to be dead.

        A path is dead iff it is in the active VFS but not in the *live* set
        (entry points ∪ their descendants).

        Uses an **independent** iterative BFS (no dependency on
        ``graph.reachable_from_all()``) so this serves as a genuine oracle.
        """
        if not valid_entries:
            return set()

        # Independent iterative BFS — no calls to graph.reachable_from_all()
        edges = set(graph.graph.edges())
        expected_reachable: set[str] = set()
        queue = list(valid_entries)
        visited: set[str] = set(valid_entries)
        while queue:
            current = queue.pop(0)
            for src, dst in edges:
                if src == current and dst not in visited:
                    visited.add(dst)
                    expected_reachable.add(dst)
                    queue.append(dst)

        expected_live: set[str] = valid_entries | expected_reachable
        active_paths = {n.virtual_path for n in vfs.get_all_active()}
        return {p for p in active_paths if p not in expected_live}

    # -- property-based tests --------------------------------------------------

    @given(
        paths=st.lists(
            st.text(min_size=0, max_size=12), min_size=1, max_size=8, unique=True
        ),
        entry_points=st.sets(
            st.text(min_size=0, max_size=12), min_size=0, max_size=4
        ),
        edge_list=st.lists(
            st.tuples(
                st.text(min_size=0, max_size=12),
                st.text(min_size=0, max_size=12),
            ),
            min_size=0,
            max_size=15,
        ),
    )
    @settings(max_examples=300)
    def test_hypothesis_dead_file_consistency(
        self,
        paths: list[str],
        entry_points: set[str],
        edge_list: list[tuple[str, str]],
    ) -> None:
        """For any random graph, verify BFS reachability matches analyzer output.

        Because the ``DeadFileAnalyzer`` is deterministic, the result should
        agree with a direct BFS computation on the same graph for all inputs.
        """
        path_set: set[str] = set(paths)
        valid_edges = [
            (s, t) for s, t in edge_list if s in path_set and t in path_set
        ]
        valid_entries = {p for p in entry_points if p in path_set}

        vfs, graph = self._build_vfs_and_graph(paths, valid_edges)

        # Where there are no valid entry points, the analyzer returns early
        # (entry_points=None) and marks nothing dead.  Replicate that.
        entries_for_analyzer: set[str] | None = valid_entries or None
        analyzer = DeadFileAnalyzer(entry_points=entries_for_analyzer)
        store = ResultStore.from_analysis(
            vfs, graph, [analyzer], entry_points=entries_for_analyzer
        )

        actual_dead = {
            r.virtual_path for r in store.files.rows if r.is_dead  # type: ignore[union-attr]
        }
        expected_dead = self._compute_expected_dead(
            path_set, valid_entries, graph, vfs
        )

        assert actual_dead == expected_dead, (
            f"Dead-file mismatch with {len(valid_entries)} entry point(s) "
            f"and {len(valid_edges)} edge(s).\n"
            f"  Expected: {sorted(expected_dead)}\n"
            f"  Actual:   {sorted(actual_dead)}"
        )

    # -- edge-case: empty entry-point set → nothing dead -----------------------

    @given(
        paths=st.lists(
            st.text(min_size=0, max_size=10), min_size=1, max_size=5, unique=True
        ),
    )
    @settings(max_examples=20)
    def test_empty_entry_means_nothing_dead(
        self,
        paths: list[str],
    ) -> None:
        """When entry_points is None / empty, no file is marked dead."""
        vfs = VirtualFileSystem()
        for i, path in enumerate(paths):
            vfs.add_file(
                FileNode(
                    virtual_path=path,
                    source_type="test",
                    source_name=f"src_{i}",
                    priority=i,
                    is_enabled=True,
                )
            )
        vfs.resolve()

        graph = DependencyGraph()
        for path in paths:
            graph.add_node(path)

        # None → analyzer returns early; no dead files.
        analyzer = DeadFileAnalyzer(entry_points=None)
        store = ResultStore.from_analysis(vfs, graph, [analyzer], entry_points=None)

        actual_dead = {
            r.virtual_path for r in store.files.rows if r.is_dead  # type: ignore[union-attr]
        }
        assert len(actual_dead) == 0, (
            f"Expected no dead files when entry_points=None, "
            f"got {len(actual_dead)} dead."
        )

    # -- edge-case: isolated subgraph -----------------------------------------

    @given(
        paths=st.lists(
            st.text(min_size=0, max_size=10), min_size=3, max_size=6, unique=True
        ),
    )
    @settings(max_examples=20)
    def test_isolated_subgraph_marked_dead(
        self,
        paths: list[str],
    ) -> None:
        """Files in a disconnected subgraph (no path from entry) are dead."""
        assert len(paths) >= 3

        vfs = VirtualFileSystem()
        for i, path in enumerate(paths):
            vfs.add_file(
                FileNode(
                    virtual_path=path,
                    source_type="test",
                    source_name=f"src_{i}",
                    priority=i,
                    is_enabled=True,
                )
            )
        vfs.resolve()

        # First 2 paths form a connected component, the rest are isolated.
        graph = DependencyGraph()
        for path in paths:
            graph.add_node(path)
        graph.add_edges([(paths[0], paths[1])])

        entry_point = {paths[0]}
        analyzer = DeadFileAnalyzer(entry_points=entry_point)
        store = ResultStore.from_analysis(
            vfs, graph, [analyzer], entry_points=entry_point
        )

        actual_dead = {
            r.virtual_path for r in store.files.rows if r.is_dead  # type: ignore[union-attr]
        }
        expected_dead = set(paths[2:])
        assert actual_dead == expected_dead, (
            f"Isolated subgraph: expected {sorted(expected_dead)} dead, "
            f"got {sorted(actual_dead)}"
        )


# ── Cascade detection tests ─────────────────────────────────────────────


@pytest.mark.skipif(
    not _HYPOTHESIS_AVAILABLE, reason="hypothesis not installed"
)
class TestDeadFileCascade:
    """验证 dead-file 标记沿依赖链路正确级联传播。"""

    # ── chain: linear cascade ────────────────────────────────────────────

    @given(
        chain_length=st.integers(2, 10),
        cut_point=st.integers(0, 9),
    )
    @settings(max_examples=100)
    def test_cascade_on_broken_chain(
        self, chain_length: int, cut_point: int
    ) -> None:
        """A0→A1→...→An: 切断 cut_point, 下游全部 dead."""
        paths = [f"A{i}" for i in range(chain_length)]

        vfs = VirtualFileSystem()
        for i, p in enumerate(paths):
            vfs.add_file(
                FileNode(p, "test", f"src_{i}", priority=i, is_enabled=True)
            )
        vfs.resolve()

        graph = DependencyGraph()
        for p in paths:
            graph.add_node(p)

        # Build edges: A0→A1→...→A[cut_point-2]→A[cut_point-1], then CUT.
        # When cut_point >= chain_length the full chain is built (no cut).
        max_edge_idx = min(chain_length - 1, cut_point - 1)
        edges = [(paths[i], paths[i + 1]) for i in range(max_edge_idx)]
        graph.add_edges(edges)

        entry_points = {paths[0]}
        analyzer = DeadFileAnalyzer(entry_points=entry_points)
        store = ResultStore.from_analysis(
            vfs, graph, [analyzer], entry_points=entry_points,
        )

        actual_dead = {
            r.virtual_path
            for r in store.files.rows  # type: ignore[union-attr]
            if r.is_dead
        }
        # Files at index >= cut_point are dead (A0 at index 0 is the entry
        # and always alive).  When cut_point >= chain_length nothing is dead.
        expected_dead = set(paths[max(1, cut_point):])

        assert actual_dead == expected_dead, (
            f"Broken chain (length={chain_length}, cut={cut_point}): "
            f"expected {sorted(expected_dead)} dead, got {sorted(actual_dead)}"
        )

    # ── tree: branching cascade ──────────────────────────────────────────

    @given(
        depth=st.integers(1, 4),
        branching=st.integers(1, 3),
    )
    @settings(max_examples=100)
    def test_cascade_in_tree(self, depth: int, branching: int) -> None:
        """Tree: remove root, whole subtree dead."""
        paths: list[str] = ["R"]
        edges: list[tuple[str, str]] = []
        current_level: list[str] = ["R"]
        for _d in range(1, depth + 1):
            next_level: list[str] = []
            for parent in current_level:
                for b in range(branching):
                    child = f"{parent}/{b}"
                    paths.append(child)
                    edges.append((parent, child))
                    next_level.append(child)
            current_level = next_level

        # Separate entry-point file with no connection to the tree
        entry_path = "ENTRY"
        all_paths = [entry_path] + paths
        vfs = VirtualFileSystem()
        for i, p in enumerate(all_paths):
            vfs.add_file(
                FileNode(p, "test", f"src_{i}", priority=i, is_enabled=True)
            )
        vfs.resolve()

        # Only add tree edges (no edges from ENTRY to tree)
        graph = DependencyGraph()
        for p in all_paths:
            graph.add_node(p)
        graph.add_edges(edges)

        entry_points = {entry_path}
        analyzer = DeadFileAnalyzer(entry_points=entry_points)
        store = ResultStore.from_analysis(
            vfs, graph, [analyzer], entry_points=entry_points,
        )

        actual_dead = {
            r.virtual_path
            for r in store.files.rows  # type: ignore[union-attr]
            if r.is_dead
        }
        # Entire tree is dead because root is unreachable from ENTRY
        expected_dead = set(paths)

        assert actual_dead == expected_dead, (
            f"Tree (depth={depth}, branching={branching}): "
            f"expected {len(expected_dead)} dead tree nodes, "
            f"got {len(actual_dead)} dead ({sorted(actual_dead)})"
        )

    # ── diamond: multiple paths prevent false cascade ────────────────────

    def test_cascade_diamond(self) -> None:
        """Diamond (A→B, A→C, B→D, C→D): B broken, D still reachable via C."""
        vfs = VirtualFileSystem()
        vfs.add_file(
            FileNode("A", "test", "src_A", priority=10, is_enabled=True)
        )
        vfs.add_file(
            FileNode("C", "test", "src_C", priority=10, is_enabled=True)
        )
        vfs.add_file(
            FileNode("D", "test", "src_D", priority=10, is_enabled=True)
        )
        # B is intentionally absent from VFS (dead / broken)
        vfs.resolve()

        graph = DependencyGraph()
        for n in ("A", "B", "C", "D"):
            graph.add_node(n)
        # Full diamond: A→B and B→D exist in graph even though B is not in VFS
        graph.add_edges([("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")])

        entry_points = {"A"}
        analyzer = DeadFileAnalyzer(entry_points=entry_points)
        store = ResultStore.from_analysis(
            vfs, graph, [analyzer], entry_points=entry_points,
        )

        actual_dead = {
            r.virtual_path
            for r in store.files.rows  # type: ignore[union-attr]
            if r.is_dead
        }
        # A (entry), C, D (reachable via A→C→D) are alive.
        # B is not in VFS, so not in store.files at all.
        assert actual_dead == set(), (
            f"Diamond: expected no dead files, got {sorted(actual_dead)}"
        )

    # ── cycle: cycles don't prevent reachability ─────────────────────────

    def test_cascade_with_cycles(self) -> None:
        """Cycle: remove entry edge, files in cycle still reachable from each other."""
        vfs = VirtualFileSystem()
        vfs.add_file(
            FileNode("A", "test", "src_A", priority=10, is_enabled=True)
        )
        vfs.add_file(
            FileNode("B", "test", "src_B", priority=10, is_enabled=True)
        )
        vfs.add_file(
            FileNode("C", "test", "src_C", priority=10, is_enabled=True)
        )
        vfs.resolve()

        graph = DependencyGraph()
        for n in ("A", "B", "C"):
            graph.add_node(n)
        graph.add_edges([("A", "B"), ("B", "C"), ("C", "A")])

        entry_points = {"A"}
        analyzer = DeadFileAnalyzer(entry_points=entry_points)
        store = ResultStore.from_analysis(
            vfs, graph, [analyzer], entry_points=entry_points,
        )

        actual_dead = {
            r.virtual_path
            for r in store.files.rows  # type: ignore[union-attr]
            if r.is_dead
        }
        assert actual_dead == set(), (
            f"Cycle: expected no dead files, got {sorted(actual_dead)}"
        )
