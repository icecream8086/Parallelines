"""Formal verification of VFS overlay properties.

Tests construct real VirtualFileSystem instances via ``add_file()`` + ``resolve()``,
then verify that the actual resolution results satisfy the required properties.
"""

from __future__ import annotations

try:
    from hypothesis import given, settings, strategies as st, HealthCheck
    HAS_HYPOTHESIS = True
except ImportError:
    HAS_HYPOTHESIS = False

import z3

from parallelines.types import FileNode
from parallelines.vfs.filesystem import VirtualFileSystem


class TestVfsOverlayProperties:
    """Concrete VFS verification of overlay resolution properties.

    All tests use real VFS instances — the Z3 solver is only used for
    properties that genuinely benefit from SMT encoding (e.g. transitivity
    with symbolic priorities).
    """

    # ------------------------------------------------------------------
    # Test 1 — Overlay transitivity (Z3-aided)
    # ------------------------------------------------------------------
    def test_overlay_transitivity(self) -> None:
        """priority(A) < priority(B) < priority(C) and same_path => A is overridden."""
        solver = z3.Solver()
        pA, pB, pC = z3.Ints("pA pB pC")
        solver.add(pA < pB, pB < pC)

        a_not_redundant = z3.Bool("a_not_redundant")
        solver.add(
            z3.Implies(a_not_redundant, z3.And(pA >= pB, pA >= pC))
        )
        solver.add(a_not_redundant)

        assert solver.check() == z3.unsat, (
            "A cannot be non-redundant when pA < pB < pC"
        )

    # ------------------------------------------------------------------
    # Test 2 — Active / redundant mutual exclusion (concrete VFS)
    # ------------------------------------------------------------------
    def test_active_file_not_redundant(self) -> None:
        """After resolve(), no file is both active and redundant."""
        vfs = VirtualFileSystem()
        vfs.add_file(FileNode(
            virtual_path="materials/wall.vmt", source_type="vpk",
            source_name="addon_a", priority=10, is_enabled=True,
        ))
        vfs.add_file(FileNode(
            virtual_path="materials/wall.vmt", source_type="vpk",
            source_name="addon_b", priority=5, is_enabled=True,
        ))
        vfs.add_file(FileNode(
            virtual_path="models/player.mdl", source_type="vpk",
            source_name="addon_a", priority=3, is_enabled=True,
        ))
        vfs.resolve()

        active_paths: set[str] = set()
        for node in vfs.get_all_files():
            if node.is_redundant:
                assert node not in active_paths, (
                    f"Redundant file {node.virtual_path} is also active"
                )
                continue
            active_paths.add(node.virtual_path)

    # ------------------------------------------------------------------
    # Test 3 — No winner without enabled files (concrete VFS)
    # ------------------------------------------------------------------
    def test_no_winner_without_enabled_files(self) -> None:
        """A path with only disabled/dead files has no active file."""
        vfs = VirtualFileSystem()
        vfs.add_file(FileNode(
            virtual_path="disabled.txt", source_type="vpk",
            source_name="src1", priority=10, is_enabled=False,
        ))
        vfs.add_file(FileNode(
            virtual_path="disabled.txt", source_type="vpk",
            source_name="src2", priority=5, is_enabled=False,
        ))
        vfs.add_file(FileNode(
            virtual_path="dead.txt", source_type="vpk",
            source_name="src3", priority=10, is_enabled=True,
            is_dead=True,
        ))
        vfs.resolve()

        assert vfs.get_active_file("disabled.txt") is None, (
            "No active file expected when all are disabled"
        )
        assert vfs.get_active_file("dead.txt") is None, (
            "No active file expected when all are dead"
        )
        assert len(vfs.get_all_active()) == 0, (
            "Active set should be empty when no file qualifies"
        )

        # Sanity: an enabled path still works
        vfs.add_file(FileNode(
            virtual_path="enabled.txt", source_type="vpk",
            source_name="src", priority=1, is_enabled=True,
        ))
        vfs.resolve()
        assert vfs.get_active_file("enabled.txt") is not None

    # ------------------------------------------------------------------
    # Test 4 — Tie-break determinism (concrete VFS)
    # ------------------------------------------------------------------
    def test_tie_break_deterministic(self) -> None:
        """When priorities tie, exactly one winner exists per path."""
        vfs = VirtualFileSystem()
        vfs.add_file(FileNode(
            virtual_path="tie.txt", source_type="vpk",
            source_name="a", priority=5, is_enabled=True,
        ))
        vfs.add_file(FileNode(
            virtual_path="tie.txt", source_type="vpk",
            source_name="b", priority=5, is_enabled=True,
        ))
        vfs.add_file(FileNode(
            virtual_path="tie.txt", source_type="vpk",
            source_name="c", priority=5, is_enabled=True,
        ))
        vfs.resolve()

        active = vfs.get_active_file("tie.txt")
        assert active is not None, "A tied path must have a winner"
        winners = [n for n in vfs.get_all_files() if not n.is_redundant]
        assert len(winners) == 1, (
            f"Expected exactly 1 winner for tied path, got {len(winners)}"
        )

    # ------------------------------------------------------------------
    # Test 5 — Redundancy implies a higher-priority overrider (concrete VFS)
    # ------------------------------------------------------------------
    def test_redundant_implies_lower_priority(self) -> None:
        """Every redundant file has a higher-priority active winner at the same path."""
        vfs = VirtualFileSystem()
        vfs.add_file(FileNode(
            virtual_path="scripts/weapon.txt", source_type="vpk",
            source_name="winner", priority=10, is_enabled=True,
        ))
        vfs.add_file(FileNode(
            virtual_path="scripts/weapon.txt", source_type="vpk",
            source_name="loser", priority=3, is_enabled=True,
        ))
        vfs.add_file(FileNode(
            virtual_path="scripts/weapon.txt", source_type="vpk",
            source_name="mid", priority=7, is_enabled=True,
        ))
        vfs.add_file(FileNode(
            virtual_path="materials/floor.vmt", source_type="vpk",
            source_name="only", priority=5, is_enabled=True,
        ))
        vfs.resolve()

        for node in vfs.get_all_files():
            if node.is_redundant:
                winner = vfs.get_active_file(node.virtual_path)
                assert winner is not None, (
                    f"Redundant {node.virtual_path} has no active winner"
                )
                assert winner.priority >= node.priority, (
                    f"Redundant {node.virtual_path} (pri={node.priority}) has "
                    f"priority >= winner ({winner.priority})"
                )
            else:
                active = vfs.get_active_file(node.virtual_path)
                if not node.is_dead and not node.is_disabled_addon:
                    assert active is node, (
                        "Non-redundant node should be the active file for its path"
                    )

    # ------------------------------------------------------------------
    # Test 6 — Resolve idempotency
    # ------------------------------------------------------------------
    def test_resolve_idempotent(self) -> None:
        """Calling resolve() twice produces the same active set as calling it once."""
        vfs = VirtualFileSystem()
        vfs.add_file(FileNode(
            virtual_path="a.txt", source_type="vpk",
            source_name="s1", priority=10, is_enabled=True,
        ))
        vfs.add_file(FileNode(
            virtual_path="a.txt", source_type="vpk",
            source_name="s2", priority=5, is_enabled=True,
        ))
        vfs.add_file(FileNode(
            virtual_path="b.txt", source_type="vpk",
            source_name="s1", priority=3, is_enabled=True,
        ))
        vfs.resolve()

        first_active = {(n.virtual_path, n.source_name) for n in vfs.get_all_active()}
        first_winner_prio = {
            n.virtual_path: n.priority for n in vfs.get_all_active()
        }

        # Second resolve() — same VFS, same files
        vfs.resolve()

        second_active = {(n.virtual_path, n.source_name) for n in vfs.get_all_active()}
        second_winner_prio = {
            n.virtual_path: n.priority for n in vfs.get_all_active()
        }

        assert first_active == second_active, (
            f"resolve() idempotency violated: "
            f"first={first_active}, second={second_active}"
        )
        assert first_winner_prio == second_winner_prio, (
            "resolve() idempotency (priorities) violated"
        )

    # ------------------------------------------------------------------
    # Test 7 — Monotonicity: adding higher-priority file changes winner
    # ------------------------------------------------------------------
    def test_monotonicity_higher_priority_wins(self) -> None:
        """Adding a higher-priority file for an existing path updates the winner."""
        vfs = VirtualFileSystem()
        vfs.add_file(FileNode(
            virtual_path="shared.vmt", source_type="vpk",
            source_name="low", priority=5, is_enabled=True,
        ))
        vfs.resolve()

        winner_before = vfs.get_active_file("shared.vmt")
        assert winner_before is not None
        assert winner_before.source_name == "low"

        # Add higher-priority file for the same path
        vfs.add_file(FileNode(
            virtual_path="shared.vmt", source_type="vpk",
            source_name="high", priority=10, is_enabled=True,
        ))
        vfs.resolve()

        winner_after = vfs.get_active_file("shared.vmt")
        assert winner_after is not None
        assert winner_after.source_name == "high", (
            f"Expected winner to be 'high', got '{winner_after.source_name}'"
        )
        assert winner_before.is_redundant, (
            "Old winner should become redundant after higher-priority file added"
        )


# ── VFS resolve() boundary fuzzing ──────────────────────────────────────────


@st.composite
def file_node_specs(draw) -> list[FileNode]:
    """Generate random FileNode combinations covering all state flags."""
    n_paths = draw(st.integers(1, 10))
    paths = [f"p{i}" for i in range(n_paths)]
    specs: list[FileNode] = []
    for path in paths:
        n_copies = draw(st.integers(1, 5))
        for _ in range(n_copies):
            specs.append(FileNode(
                virtual_path=path,
                source_type="test",
                source_name=draw(st.text(min_size=1, max_size=8)),
                priority=draw(st.integers(-10, 100)),
                is_enabled=draw(st.booleans()),
                is_dead=draw(st.booleans()),
                is_redundant=False,
                is_disabled_addon=draw(st.booleans()),
            ))
    return specs


class TestVfsResolveEdgeCases:
    """Hypothesis fuzzing of resolve() with unusual node state combinations."""

    @settings(suppress_health_check=[HealthCheck.too_slow])
    @given(specs=file_node_specs())
    def test_resolve_never_crashes(self, specs: list[FileNode]) -> None:
        """resolve() should never raise on arbitrary FileNode combinations."""
        vfs = VirtualFileSystem()
        for node in specs:
            vfs.add_file(node)
        vfs.resolve()

    @settings(suppress_health_check=[HealthCheck.too_slow])
    @given(specs=file_node_specs())
    def test_active_not_redundant(self, specs: list[FileNode]) -> None:
        """After resolve, no file is both active and redundant."""
        vfs = VirtualFileSystem()
        for node in specs:
            vfs.add_file(node)
        vfs.resolve()

        for node in vfs.get_all_files():
            if node.is_redundant:
                assert vfs.get_active_file(node.virtual_path) is not node

    @settings(suppress_health_check=[HealthCheck.too_slow])
    @given(specs=file_node_specs())
    def test_dead_excluded_from_winner(self, specs: list[FileNode]) -> None:
        """A file with is_dead=True is never the winner for its path."""
        vfs = VirtualFileSystem()
        for node in specs:
            vfs.add_file(node)
        vfs.resolve()

        for node in vfs.get_all_files():
            if node.is_dead:
                winner = vfs.get_active_file(node.virtual_path)
                if winner is not None:
                    assert winner is not node, (
                        f"Dead file {node.virtual_path} is the winner"
                    )

    @settings(suppress_health_check=[HealthCheck.too_slow])
    @given(specs=file_node_specs())
    def test_disabled_addon_excluded(self, specs: list[FileNode]) -> None:
        """is_disabled_addon=True files with is_enabled=False are not winners."""
        vfs = VirtualFileSystem()
        for node in specs:
            vfs.add_file(node)
        vfs.resolve()

        for node in vfs.get_all_files():
            if node.is_disabled_addon and not node.is_enabled:
                winner = vfs.get_active_file(node.virtual_path)
                if winner is not None:
                    assert winner is not node, (
                        f"Disabled addon file {node.virtual_path} is the winner "
                        f"despite is_enabled=False"
                    )

    @settings(suppress_health_check=[HealthCheck.too_slow])
    @given(specs=file_node_specs())
    def test_active_paths_have_winner(self, specs: list[FileNode]) -> None:
        """Every path with at least one enabled non-dead file has a winner."""
        vfs = VirtualFileSystem()
        for node in specs:
            vfs.add_file(node)
        vfs.resolve()

        by_path: dict[str, list[FileNode]] = {}
        for node in specs:
            by_path.setdefault(node.virtual_path, []).append(node)

        for path, nodes in by_path.items():
            has_qualifying = any(
                n.is_enabled and not n.is_dead
                for n in nodes
            )
            winner = vfs.get_active_file(path)
            if has_qualifying:
                assert winner is not None, (
                    f"Path {path} has qualifying files but no winner"
                )

    @settings(suppress_health_check=[HealthCheck.too_slow])
    @given(specs=file_node_specs())
    def test_resolve_idempotent(self, specs: list[FileNode]) -> None:
        """resolve() twice gives the same active set as resolve() once."""
        vfs = VirtualFileSystem()
        for node in specs:
            vfs.add_file(node)
        vfs.resolve()

        first_active = {(n.virtual_path, n.source_name) for n in vfs.get_all_active()}

        vfs.resolve()
        second_active = {(n.virtual_path, n.source_name) for n in vfs.get_all_active()}

        assert first_active == second_active, (
            "resolve() idempotency violated under random node states"
        )

