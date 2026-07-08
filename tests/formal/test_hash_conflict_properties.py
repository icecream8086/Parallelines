"""Hypothesis property-based tests for HashConflictAnalyzer.

Uses ``hypothesis`` to generate random file-system states and verifies
invariant properties of the hash-conflict detection algorithm.

Properties
----------
1.  All files at the same virtual_path with identical hashes → zero conflicts
2.  Every reported conflict has ``winner_hash ≠ loser_hash``
3.  All virtual_paths unique → zero conflicts

The hash-conflict relation (as defined by ``HashConflictAnalyzer``) is::

    Conflict(f_i, f_j) ⟺ Path(f_i) = Path(f_j)
                       ∧ Hash(f_i) ≠ Hash(f_j)
                       ∧ Enabled(f_i) ∧ Enabled(f_j)
                       ∧ file_hash(f_i) is not None
                       ∧ file_hash(f_j) is not None

A conflict only arises when at least two *enabled* sources share a virtual
path but differ in their content hashes.  The higher-priority source is the
"winner"; all lower-priority sources are "losers".
"""

from __future__ import annotations

import pytest

from parallelines.analysis.hash_conflict import HashConflictAnalyzer
from parallelines.engine.store import ResultStore
from parallelines.engine.schema import HashConflictRow
from parallelines.types import FileNode
from parallelines.vfs.filesystem import VirtualFileSystem


# ── Hypothesis strategies ────────────────────────────────────────────────────

# We import hypothesis lazily inside each test so that the file can be
# collected even when hypothesis is absent.  pytest.importorskip is used
# at function level to produce a clean skip message.

# A single file specification: (virtual_path, source_name, file_hash, priority, is_enabled)
_FileSpec = tuple[str, str, str | None, int, bool]


def _build_vfs_from_specs(specs: list[_FileSpec]) -> VirtualFileSystem:
    """Construct a VirtualFileSystem from a list of file specifications.

    Each spec is ``(virtual_path, source_name, file_hash, priority, is_enabled)``.
    """
    vfs = VirtualFileSystem()
    for path, source, file_hash, priority, enabled in specs:
        vfs.add_file(
            FileNode(
                virtual_path=path,
                source_type="test",
                source_name=source,
                file_hash=file_hash,
                priority=priority,
                is_enabled=enabled,
            )
        )
    vfs.resolve()
    return vfs


def _run_hash_analyzer(vfs: VirtualFileSystem) -> ResultStore:
    """Run HashConflictAnalyzer on *vfs* and return the store."""
    store = ResultStore()
    analyzer = HashConflictAnalyzer()
    analyzer.analyze(vfs, graph=None, store=store)
    return store


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestNoConflictWhenAllSameHash:
    """Property 1: identical hashes at every shared path → zero conflicts.

    If every FileNode that shares a virtual_path has the *same* file_hash,
    then no hash conflicts can arise — the ``HashConflictAnalyzer`` only
    reports mismatches.
    """

    @pytest.mark.skipif(
        pytest.importorskip("hypothesis") is None,  # pragma: no cover
        reason="hypothesis not installed",
    )
    def test_same_hash_across_all_paths(self) -> None:
        """All paths have the same hash → no conflicts."""
        from hypothesis import given, settings
        from hypothesis import strategies as st

        @given(
            path_hash_pairs=st.lists(
                st.tuples(
                    st.text(min_size=1, max_size=8),  # virtual_path
                    st.text(min_size=1, max_size=8),  # hash (shared for this path)
                    st.lists(
                        st.tuples(
                            st.text(min_size=1, max_size=6),  # source_name
                            st.integers(min_value=0, max_value=10),  # priority
                            st.booleans(),  # is_enabled
                        ),
                        min_size=2,
                        max_size=5,
                        unique_by=lambda t: t[0],
                    ),
                ),
                min_size=0,
                max_size=6,
                unique_by=lambda t: t[0],  # unique virtual_path across groups
            ),
        )
        @settings(max_examples=200)
        def _run(path_hash_pairs):
            specs: list[_FileSpec] = []
            for path, hash_val, sources in path_hash_pairs:
                for source_name, prio, enabled in sources:
                    specs.append((path, source_name, hash_val, prio, enabled))

            vfs = _build_vfs_from_specs(specs)
            store = _run_hash_analyzer(vfs)

            if store.hash_conflicts is not None:
                assert len(store.hash_conflicts) == 0, (
                    f"Expected zero conflicts when all hashes match per path, "
                    f"got {len(store.hash_conflicts)}."
                )

        _run()

    @pytest.mark.skipif(
        pytest.importorskip("hypothesis") is None,  # pragma: no cover
        reason="hypothesis not installed",
    )
    def test_same_hash_with_disabled_and_none(self) -> None:
        """Same hash or None/empty hash → no conflicts (None hashes excluded)."""
        from hypothesis import given, settings
        from hypothesis import strategies as st

        @given(
            path_groups=st.lists(
                st.tuples(
                    st.text(min_size=1, max_size=8),  # path
                    st.lists(
                        st.tuples(
                            st.text(min_size=1, max_size=6),  # source_name
                            st.one_of(
                                st.none(),
                                st.text(min_size=1, max_size=8),
                            ),  # hash: None or some string
                            st.integers(min_value=0, max_value=10),  # priority
                            st.booleans(),  # enabled
                        ),
                        min_size=2,
                        max_size=4,
                        unique_by=lambda t: t[0],
                    ),
                ),
                min_size=1,
                max_size=4,
                unique_by=lambda t: t[0],  # unique virtual_path across groups
            ),
        )
        @settings(max_examples=200)
        def _run(path_groups):
            specs: list[_FileSpec] = []
            for path, sources in path_groups:
                # Force all hashes in this path to be the same value (if not None).
                # Pick a single hash value for all sources at this path.
                shared_hash: str | None = None
                for _, h, _, _ in sources:
                    if h is not None:
                        shared_hash = h
                        break
                for source_name, _, prio, enabled in sources:
                    specs.append((path, source_name, shared_hash, prio, enabled))

            vfs = _build_vfs_from_specs(specs)
            store = _run_hash_analyzer(vfs)

            if store.hash_conflicts is not None:
                assert len(store.hash_conflicts) == 0, (
                    f"Expected zero conflicts when all non-None hashes match "
                    f"per path, got {len(store.hash_conflicts)}."
                )

        _run()

    def test_manual_trivial_no_conflict(self) -> None:
        """Manual baseline: two files, same path, same hash, no conflict."""
        vfs = VirtualFileSystem()
        vfs.add_file(
            FileNode(
                virtual_path="materials/test.vmt",
                source_type="vpk",
                source_name="addon_a",
                priority=5,
                file_hash="abc123",
                is_enabled=True,
            )
        )
        vfs.add_file(
            FileNode(
                virtual_path="materials/test.vmt",
                source_type="vpk",
                source_name="addon_b",
                priority=3,
                file_hash="abc123",
                is_enabled=True,
            )
        )
        vfs.resolve()

        store = _run_hash_analyzer(vfs)
        assert store.hash_conflicts is None or len(store.hash_conflicts) == 0


class TestConflictRequiresHashDiffer:
    """Property 2: every reported conflict has different hashes.

    If ``HashConflictAnalyzer`` reports a conflict between a winner and a
    loser at the same virtual_path, then ``winner_hash ≠ loser_hash`` must
    hold.
    """

    @pytest.mark.skipif(
        pytest.importorskip("hypothesis") is None,  # pragma: no cover
        reason="hypothesis not installed",
    )
    def test_every_conflict_has_different_hashes(self) -> None:
        """Check all HashConflictRows for winner_hash != loser_hash."""
        from hypothesis import given, settings
        from hypothesis import strategies as st

        @given(
            file_specs=st.lists(
                st.tuples(
                    st.text(min_size=1, max_size=8),  # virtual_path
                    st.text(min_size=1, max_size=6),  # source_name
                    st.one_of(st.none(), st.text(min_size=1, max_size=8)),  # hash
                    st.integers(min_value=0, max_value=10),  # priority
                    st.booleans(),  # enabled
                ),
                min_size=2,
                max_size=20,
            ),
        )
        @settings(max_examples=200)
        def _run(file_specs):
            specs: list[_FileSpec] = [
                (path, src, h, prio, en)
                for path, src, h, prio, en in file_specs
            ]
            vfs = _build_vfs_from_specs(specs)
            store = _run_hash_analyzer(vfs)

            if store.hash_conflicts is not None:
                for row in store.hash_conflicts.rows:
                    assert isinstance(row, HashConflictRow)
                    assert row.winner_hash != row.loser_hash, (
                        f"Hash conflict at '{row.virtual_path}' reports "
                        f"identical hashes ('{row.winner_hash}') for "
                        f"winner '{row.winner_source}' and "
                        f"loser '{row.loser_source}'"
                    )

        _run()

    def test_manual_different_hash_conflict(self) -> None:
        """Manual baseline: same path, different hashes → conflict."""
        vfs = VirtualFileSystem()
        vfs.add_file(
            FileNode(
                virtual_path="scripts/weapon.txt",
                source_type="vpk",
                source_name="addon_x",
                priority=10,
                file_hash="aaaa",
                is_enabled=True,
            )
        )
        vfs.add_file(
            FileNode(
                virtual_path="scripts/weapon.txt",
                source_type="vpk",
                source_name="addon_y",
                priority=5,
                file_hash="bbbb",
                is_enabled=True,
            )
        )
        vfs.resolve()

        store = _run_hash_analyzer(vfs)
        assert store.hash_conflicts is not None
        assert len(store.hash_conflicts) == 1

        row = store.hash_conflicts.rows[0]
        assert isinstance(row, HashConflictRow)
        assert row.winner_hash != row.loser_hash
        assert row.winner_source == "addon_x"
        assert row.loser_source == "addon_y"
        assert row.winner_hash == "aaaa"
        assert row.loser_hash == "bbbb"

    def test_conflict_reported_for_redundant_loser(self) -> None:
        """Conflict is still reported for redundant losers if they have a hash.

        The HashConflictAnalyzer looks at ``vfs.get_all_files()`` (all nodes,
        not just active ones).  Any enabled node with a different hash
        contributes to the conflict set, regardless of whether it was
        overridden by a higher-priority source.
        """
        vfs = VirtualFileSystem()
        vfs.add_file(
            FileNode(
                virtual_path="cfg/autoexec.cfg",
                source_type="addon",
                source_name="overrider",
                priority=10,
                file_hash="hash_A",
                is_enabled=True,
            )
        )
        vfs.add_file(
            FileNode(
                virtual_path="cfg/autoexec.cfg",
                source_type="addon",
                source_name="overridden",
                priority=5,
                file_hash="hash_B",
                is_enabled=True,
            )
        )
        vfs.resolve()

        store = _run_hash_analyzer(vfs)
        assert store.hash_conflicts is not None
        assert len(store.hash_conflicts) == 1

        row = store.hash_conflicts.rows[0]
        assert isinstance(row, HashConflictRow)
        assert row.winner_source == "overrider"
        assert row.loser_source == "overridden"
        assert row.winner_hash == "hash_A"
        assert row.loser_hash == "hash_B"

    def test_no_conflict_when_loser_disabled(self) -> None:
        """Disabled files are excluded from hash comparison."""
        vfs = VirtualFileSystem()
        vfs.add_file(
            FileNode(
                virtual_path="scripts/weapon.txt",
                source_type="vpk",
                source_name="addon_x",
                priority=10,
                file_hash="aaaa",
                is_enabled=True,
            )
        )
        vfs.add_file(
            FileNode(
                virtual_path="scripts/weapon.txt",
                source_type="vpk",
                source_name="addon_y",
                priority=5,
                file_hash="bbbb",
                is_enabled=False,  # disabled → excluded
            )
        )
        vfs.resolve()

        store = _run_hash_analyzer(vfs)
        # Only one enabled source with a hash → no conflict.
        assert store.hash_conflicts is None or len(store.hash_conflicts) == 0


class TestNoConflictOnUniquePaths:
    """Property 3: all paths unique → zero hash conflicts.

    When every FileNode occupies a distinct virtual_path, no two sources
    share a path, so the ``HashConflictAnalyzer`` never finds multiple
    source_names for the same path and reports no conflicts.
    """

    @pytest.mark.skipif(
        pytest.importorskip("hypothesis") is None,  # pragma: no cover
        reason="hypothesis not installed",
    )
    def test_unique_paths_yield_no_conflicts(self) -> None:
        """All virtual_paths unique → exactly zero conflicts."""
        from hypothesis import given, settings
        from hypothesis import strategies as st

        @given(
            file_specs=st.lists(
                st.tuples(
                    st.text(min_size=1, max_size=10),  # virtual_path
                    st.text(min_size=1, max_size=6),  # source_name
                    st.one_of(st.none(), st.text(min_size=1, max_size=8)),  # hash
                    st.integers(min_value=0, max_value=10),  # priority
                ),
                min_size=1,
                max_size=15,
                # Ensure all virtual_paths are unique within a single run
                unique_by=lambda t: t[0],
            ),
        )
        @settings(max_examples=200)
        def _run(file_specs):
            specs: list[_FileSpec] = [
                (path, src, h, prio, True)
                for path, src, h, prio in file_specs
            ]
            vfs = _build_vfs_from_specs(specs)
            store = _run_hash_analyzer(vfs)

            if store.hash_conflicts is not None:
                assert len(store.hash_conflicts) == 0, (
                    f"Expected zero conflicts with {len(specs)} unique-path "
                    f"files, got {len(store.hash_conflicts)}."
                )

        _run()

    def test_manual_unique_paths_no_conflict(self) -> None:
        """Manual baseline: three files, three paths, no conflicts."""
        vfs = VirtualFileSystem()
        vfs.add_file(
            FileNode(
                virtual_path="materials/wall.vmt",
                source_type="vpk",
                source_name="addon_1",
                priority=1,
                file_hash="aaa",
                is_enabled=True,
            )
        )
        vfs.add_file(
            FileNode(
                virtual_path="materials/floor.vmt",
                source_type="vpk",
                source_name="addon_1",
                priority=1,
                file_hash="bbb",
                is_enabled=True,
            )
        )
        vfs.add_file(
            FileNode(
                virtual_path="models/player.mdl",
                source_type="vpk",
                source_name="addon_2",
                priority=5,
                file_hash="ccc",
                is_enabled=True,
            )
        )
        vfs.resolve()

        store = _run_hash_analyzer(vfs)
        assert store.hash_conflicts is None or len(store.hash_conflicts) == 0


class TestHashAnalyzerEdgeCases:
    """Edge cases that exercise boundary conditions of the analyzer.

    These are not hypothesis-based but cover corner states that randomised
    tests are unlikely to generate systematically.
    """

    def test_empty_vfs(self) -> None:
        """No files → no conflicts."""
        vfs = VirtualFileSystem()
        vfs.resolve()

        store = _run_hash_analyzer(vfs)
        assert store.hash_conflicts is None

    def test_single_file(self) -> None:
        """Single file → no conflicts (only one source)."""
        vfs = VirtualFileSystem()
        vfs.add_file(
            FileNode(
                virtual_path="materials/foo.vmt",
                source_type="vpk",
                source_name="addon_a",
                priority=5,
                file_hash="deadbeef",
                is_enabled=True,
            )
        )
        vfs.resolve()

        store = _run_hash_analyzer(vfs)
        assert store.hash_conflicts is None or len(store.hash_conflicts) == 0

    def test_multiple_paths_one_source_each(self) -> None:
        """Multiple paths, each from a single source → no conflicts."""
        vfs = VirtualFileSystem()
        for i in range(5):
            vfs.add_file(
                FileNode(
                    virtual_path=f"path_{i}.txt",
                    source_type="vpk",
                    source_name="addon_a",
                    priority=5,
                    file_hash=f"hash_{i}",
                    is_enabled=True,
                )
            )
        vfs.resolve()

        store = _run_hash_analyzer(vfs)
        assert store.hash_conflicts is None or len(store.hash_conflicts) == 0

    def test_same_source_name_not_conflict(self) -> None:
        """Two files at the same path from the same source → no conflict.

        The analyzer checks *source_name* diversity (``len(sources) < 2``).
        If the same addon overrides itself, it is not a cross-source conflict.
        """
        vfs = VirtualFileSystem()
        vfs.add_file(
            FileNode(
                virtual_path="scripts/sound.txt",
                source_type="vpk",
                source_name="same_addon",
                priority=10,
                file_hash="old",
                is_enabled=True,
            )
        )
        vfs.add_file(
            FileNode(
                virtual_path="scripts/sound.txt",
                source_type="vpk",
                source_name="same_addon",
                priority=5,
                file_hash="new",
                is_enabled=True,
            )
        )
        vfs.resolve()

        store = _run_hash_analyzer(vfs)
        assert store.hash_conflicts is None or len(store.hash_conflicts) == 0

    def test_only_none_hashes_no_conflict(self) -> None:
        """Multiple enabled sources at same path but all hashes are None."""
        vfs = VirtualFileSystem()
        vfs.add_file(
            FileNode(
                virtual_path="materials/missing.vmt",
                source_type="vpk",
                source_name="addon_a",
                priority=10,
                file_hash=None,
                is_enabled=True,
            )
        )
        vfs.add_file(
            FileNode(
                virtual_path="materials/missing.vmt",
                source_type="vpk",
                source_name="addon_b",
                priority=5,
                file_hash=None,
                is_enabled=True,
            )
        )
        vfs.resolve()

        store = _run_hash_analyzer(vfs)
        # All hashes are None, so the set of unique hashes is empty.
        # len(hashes) <= 1 → no conflict.
        assert store.hash_conflicts is None or len(store.hash_conflicts) == 0

    def test_mixed_none_and_same_hash_no_conflict(self) -> None:
        """Same path, one None hash and one real hash → only one enabled hash value."""
        vfs = VirtualFileSystem()
        vfs.add_file(
            FileNode(
                virtual_path="materials/partial.vmt",
                source_type="vpk",
                source_name="addon_a",
                priority=10,
                file_hash=None,
                is_enabled=True,
            )
        )
        vfs.add_file(
            FileNode(
                virtual_path="materials/partial.vmt",
                source_type="vpk",
                source_name="addon_b",
                priority=5,
                file_hash="abc",
                is_enabled=True,
            )
        )
        vfs.resolve()

        store = _run_hash_analyzer(vfs)
        # Only one enabled file has a hash → len(hashes) <= 1 → no conflict.
        assert store.hash_conflicts is None or len(store.hash_conflicts) == 0

    def test_three_way_conflict(self) -> None:
        """Three sources at same path: two losers reported from the highest-priority winner.

        Winner (prio=10) vs. Loser1 (prio=7) and Loser2 (prio=3): two
        HashConflictRows should be produced.
        """
        vfs = VirtualFileSystem()
        vfs.add_file(
            FileNode(
                virtual_path="config.cfg",
                source_type="addon",
                source_name="top",
                priority=10,
                file_hash="hash_A",
                is_enabled=True,
            )
        )
        vfs.add_file(
            FileNode(
                virtual_path="config.cfg",
                source_type="addon",
                source_name="mid",
                priority=7,
                file_hash="hash_B",
                is_enabled=True,
            )
        )
        vfs.add_file(
            FileNode(
                virtual_path="config.cfg",
                source_type="addon",
                source_name="bot",
                priority=3,
                file_hash="hash_C",
                is_enabled=True,
            )
        )
        vfs.resolve()

        store = _run_hash_analyzer(vfs)
        assert store.hash_conflicts is not None
        assert len(store.hash_conflicts) == 2

        loser_sources = {row.loser_source for row in store.hash_conflicts.rows}
        assert loser_sources == {"mid", "bot"}
        for row in store.hash_conflicts.rows:
            assert isinstance(row, HashConflictRow)
            assert row.winner_source == "top"
            assert row.winner_hash == "hash_A"
            assert row.loser_hash != row.winner_hash

    def test_conflict_only_between_enabled_with_hash(self) -> None:
        """Disabled and None-hash files are excluded from the conflict set."""
        vfs = VirtualFileSystem()
        # winner: enabled, has hash
        vfs.add_file(
            FileNode(
                virtual_path="data.txt",
                source_type="addon",
                source_name="winner",
                priority=10,
                file_hash="W",
                is_enabled=True,
            )
        )
        # disabled, has different hash → excluded
        vfs.add_file(
            FileNode(
                virtual_path="data.txt",
                source_type="addon",
                source_name="disabled_loser",
                priority=5,
                file_hash="D1",
                is_enabled=False,
            )
        )
        # enabled, no hash → excluded
        vfs.add_file(
            FileNode(
                virtual_path="data.txt",
                source_type="addon",
                source_name="no_hash_loser",
                priority=4,
                file_hash=None,
                is_enabled=True,
            )
        )
        vfs.resolve()

        store = _run_hash_analyzer(vfs)
        # Only "winner" qualifies for the enabled+has_hash set.
        # len(enabled_with_hash_set) <= 1 → no conflict.
        assert store.hash_conflicts is None or len(store.hash_conflicts) == 0
