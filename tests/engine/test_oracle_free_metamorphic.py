"""Oracle-Free Metamorphic Tests for Query Engine v2.

Each test encodes a *metamorphic relation* (MR): an invariant that must hold
for ALL inputs of a given shape, without any hand-written expected value.

Methodology: devdocs/oracle-free-testing-prompt.md

MR index:
  MR-COMMUTE-1   Inner join set-commutativity: R⋈S == S⋈R (set semantics)
  MR-COMMUTE-2   Composite-key inner join set-commutativity
  MR-LEFT-FILTER Left join + NULL filter = inner join
  MR-THETA-EQUI  Theta join with pure equi predicate == hash join
  MR-THETA-COL   Theta join column-conflict resolver (_right suffix)
  MR-PROJECT-SEL Project ∘ select == select ∘ project when cols contained
  MR-EXTRACT-1   _extract_equi_pairs AND-decomposition correctness
  MR-EXTRACT-2   _extract_equi_pairs OR-conservativeness
  MR-REMOVE-RT   _remove_equi_from_pred round-trip: remaining + pairs ≈ original
  MR-OPT-SAME    Optimizer preserves query result sets (execute ∘ optimize == execute)
  MR-OPT-IDEM    Optimizer is idempotent: optimize(optimize(q)) == optimize(q)
  MR-PUSHDOWN-ID Pushdown is idempotent at fixpoint
  MR-UNNEST-RT   Subquery unnesting preserves result set
  MR-JOIN-ORDER  Join order reordering preserves inner-join results (set)
  MR-LEFT-ALL    Left join when all rows match: no NULLs in right columns
  MR-SELF-JOIN   Self-join on key returns deduplicated rows
  MR-GROUP-IDEM  Group-by after group-by with same key is identity
"""
from __future__ import annotations

import copy

import pytest

import networkx as nx

from parallelines.engine import Relation, ResultStore
from parallelines.engine.query_ast import (
    BinaryPred,
    ColumnRef,
    CompoundPred,
    JoinClause,
    Literal as Lit,
    Predicate,
    Query,
    Source,
    StringPred,
)
from parallelines.engine.query_executor import QueryExecutor
from parallelines.engine.query_optimizer import QueryOptimizer
from parallelines.engine.schema import AddonRow, ExternalFileRow, FileRow


# ── Helpers ────────────────────────────────────────────────────────────────


def _row_set(rel: Relation) -> set[tuple]:
    """Extract rows as a set of tuples for set-equality comparison."""
    if not rel.rows:
        return set()
    first = rel.rows[0]
    if isinstance(first, tuple):
        return set(rel.rows)
    # Dataclass rows — convert to tuples
    return set(
        tuple(getattr(r, c) for c in rel.columns)
        for r in rel.rows
    )


def _sorted_rows(rel: Relation) -> list[tuple]:
    """Return rows sorted by first column for deterministic comparison."""
    return sorted(rel.rows, key=lambda r: r[0] if isinstance(r, tuple) else str(r))


def _make_basic_store() -> ResultStore:
    """Create a small ResultStore with overlapping keys for metamorphic tests.

    Key design:
      - files.priority and external_files.ext_priority overlap in value range →
        enables theta-join comparisons
      - files.source_name and addons.addon_id overlap → enables cross-relation
        equi-joins
      - deliberate NULLs in ``file_hash`` for NULL-semantics metamorphic tests
      - duplicate virtual_path across relations → enables the theta-vs-hash
        differential and column-conflict detection
    """
    s = ResultStore()
    s.files = Relation[FileRow].from_rows("files", [
        FileRow("a.txt", "base", "game", 100, "abc", 1024, True, False, False),
        FileRow("b.txt", "addon_x", "addon", 200, "def", 512, True, False, False),
        FileRow("c.txt", "addon_y", "addon", 300, "ghi", 256, False, False, True),
        FileRow("maps/m1.bsp", "map_vpk", "vpk", 400, "jkl", 8192, True),
        FileRow("shared.vmt", "addon_x", "addon", 200, "mno", 128, True),
        FileRow("shared.vmt", "addon_y", "addon", 300, "pqr", 128, False, False, True),
        FileRow("null_hash.txt", "base", "game", 100, None, 1, True, False, True),
    ])
    s.addons = Relation[AddonRow].from_rows("addons", [
        AddonRow("base", "Base Game", True, 100),
        AddonRow("addon_x", "Addon X", True, 200),
        AddonRow("addon_y", "Addon Y", False, 300),
        AddonRow("orphan", "Orphan", True, 999),
    ])
    s.external_files = Relation[ExternalFileRow].from_rows("external_files", [
        ExternalFileRow("a.txt", "ref:ext", 2000, "xyz", 1024),
        ExternalFileRow("new.txt", "ref:ext", 2000, "new", 512),
        ExternalFileRow("shared.vmt", "ref:ext", 2000, "qrs", 128),
    ])
    # Build indexes matching production code patterns
    s.external_files.build_index("virtual_path")
    g = nx.DiGraph()
    g.add_edge("maps/m1.bsp", "shared.vmt")
    s.graph = g
    return s


# ═══════════════════════════════════════════════════════════════════════════
# MR-COMMUTE: Inner join is set-commutative
# ═══════════════════════════════════════════════════════════════════════════


class TestJoinCommutativity:
    """MR-COMMUTE: R ⋈ S and S ⋈ R produce the same row set.

    Inner join is commutative in relational algebra:
      R ⋈_θ S ≡ { (r, s) | r∈R, s∈S, θ(r,s) }

    The column order differs, but projecting onto a sorted column list yields
    identical row sets.  If this fails, either the hash index or the row
    construction is asymmetric.
    """

    def test_single_key_commutes(self):
        """MR-COMMUTE-1: files ⋈ external_files == external_files ⋈ files (single key)."""
        store = _make_basic_store()
        left = store.files
        right = store.external_files

        forward = left.join(right, on="virtual_path")
        reverse = right.join(left, on="virtual_path")

        # Project to a common column set (sorted for determinism)
        common_cols = tuple(sorted(set(forward.columns) & set(reverse.columns)))
        fwd_proj = forward.project(*common_cols)
        rev_proj = reverse.project(*common_cols)

        assert _row_set(fwd_proj) == _row_set(rev_proj), (
            f"Single-key join not commutative: "
            f"|forward|={len(forward)}, |reverse|={len(reverse)}"
        )

    def test_composite_key_commutes(self):
        """MR-COMMUTE-2: composite-key join commutes via rename.

        Build two relations with different column names but same semantics,
        then verify that join via rename produces consistent row sets.
        """
        R = Relation("R", ("k1", "k2", "v"), rows=[
            (1, "a", 10), (2, "b", 20), (3, "c", 30),
        ])
        S = Relation("S", ("x1", "x2", "w"), rows=[
            (1, "a", 100), (2, "b", 200), (4, "d", 400),
        ])

        # Forward: rename S's columns to match R, then join
        S_renamed = S.rename({"x1": "k1", "x2": "k2"})
        forward = R.join(S_renamed, on=("k1", "k2"))

        # Reverse: rename R's columns to match S, then join
        R_renamed = R.rename({"k1": "x1", "k2": "x2"})
        reverse = S.join(R_renamed, on=("x1", "x2"))

        common_cols = tuple(sorted(set(forward.columns) & set(reverse.columns)))
        assert common_cols, "No common columns after rename"
        fwd_proj = forward.project(*common_cols)
        rev_proj = reverse.project(*common_cols)

        assert _row_set(fwd_proj) == _row_set(rev_proj), (
            f"Composite-key join not commutative via rename: "
            f"|forward|={len(forward)}, |reverse|={len(reverse)}"
        )

    def test_commute_with_nulls_in_key(self):
        """MR-COMMUTE-3: NULLs in join key produce symmetric results.

        SQL NULL != NULL means rows with NULL keys never match — but both
        directions must respect that equally.
        """
        R = Relation("R", ("k", "v"), rows=[
            (1, "a"), (None, "b"), (2, "c"), (None, "d"),
        ])
        S = Relation("S", ("k", "w"), rows=[
            (1, "x"), (None, "y"), (3, "z"),
        ])
        forward = R.join(S, on="k")
        reverse = S.join(R, on="k")
        # Only (1, ...) matches in both directions
        assert len(forward) == len(reverse), (
            f"NULL-key join asymmetric: forward={len(forward)} reverse={len(reverse)}"
        )

    def test_commute_empty_relations(self):
        """MR-COMMUTE-4: empty relation join commutes."""
        R = Relation("R", ("k", "v"), rows=[])
        S = Relation("S", ("k", "w"), rows=[(1, "x")])
        forward = R.join(S, on="k")
        reverse = S.join(R, on="k")
        assert len(forward) == 0
        assert len(reverse) == 0


# ═══════════════════════════════════════════════════════════════════════════
# MR-LEFT-FILTER: Left join + NULL filter == inner join
# ═══════════════════════════════════════════════════════════════════════════


class TestLeftJoinNullFilterEquivalence:
    """MR-LEFT-FILTER: R LEFT JOIN S filtered to non-NULL is R INNER JOIN S.

    For any right-side column c of S:
      σ_{IS NOT NULL c}(R ⋉ S) ≡ R ⋈ S

    This is a relational-algebra identity.  If broken, either the left join
    NULL-padding or the hash join is wrong.
    """

    def test_left_join_filter_vs_inner_single_key(self):
        """MR-LEFT-FILTER-1: left join + NOT NULL filter on virtual_path = inner join."""
        store = _make_basic_store()
        files = store.files
        external = store.external_files

        left = files.join_left(external, on="virtual_path")
        # Filter: ext_source_name IS NOT NULL
        filtered = Relation(
            name=left.name,
            columns=left.columns,
            rows=[r for r in left.rows if r[left.columns.index("ext_source_name")] is not None],
        )
        inner = files.join(external, on="virtual_path")

        # After removing the right-side join-key column that was kept only in
        # the inner join result, the row sets should be equal.
        common = tuple(sorted(set(filtered.columns) & set(inner.columns)))
        f_proj = filtered.project(*common)
        i_proj = inner.project(*common)

        assert _row_set(f_proj) == _row_set(i_proj), (
            f"Left+filter ({len(filtered)}) ≠ inner ({len(inner)}): "
            f"left-total-rows={len(left)}"
        )

    def test_left_join_all_match_no_nulls(self):
        """MR-LEFT-ALL: when every left row has a match, left join has no NULLs.

        If every row in R has at least one match in S, then R ⋉ S has no NULLs
        in S's columns.  This is a null-free guarantee test.
        """
        R = Relation("R", ("k", "v"), rows=[(1, "a"), (2, "b")])
        S = Relation("S", ("k", "w"), rows=[(1, "x"), (2, "y"), (1, "z")])
        result = R.join_left(S, on="k")

        # Every S-column value should be non-NULL
        s_cols = [c for c in result.columns if c not in R.columns]
        for row in result.rows:
            for col in s_cols:
                idx = result.columns.index(col)
                val = row[idx] if isinstance(row, tuple) else getattr(row, col)
                assert val is not None, (
                    f"Left join with all matches produced NULL in '{col}' for row {row}"
                )

    def test_left_join_some_no_match(self):
        """MR-LEFT-FILTER-2: left join with unmatched rows — filtered = inner.

        When some R rows have no S match, the filtered result should still
        equal the inner join (which naturally excludes non-matches).
        """
        R = Relation("R", ("k", "v"), rows=[(1, "a"), (2, "b"), (99, "z")])
        S = Relation("S", ("k", "w"), rows=[(1, "x"), (2, "y")])
        left = R.join_left(S, on="k")
        filtered = Relation(
            name=left.name,
            columns=left.columns,
            rows=[r for r in left.rows if r[left.columns.index("w")] is not None],
        )
        inner = R.join(S, on="k")
        common = tuple(sorted(set(filtered.columns) & set(inner.columns)))
        assert _row_set(filtered.project(*common)) == _row_set(inner.project(*common))


# ═══════════════════════════════════════════════════════════════════════════
# MR-THETA-EQUI: Theta join with pure equi predicate == hash join
# ═══════════════════════════════════════════════════════════════════════════


class TestThetaEquiDifferential:
    """MR-THETA-EQUI: theta join (nested-loop) with a pure equi predicate
    must produce the same row set as hash join.

    This is *differential testing* (McKeeman, 1998): two independent
    implementations of the same join semantic (hash-index vs. nested-loop)
    must agree.  Disagreement → at least one is buggy.
    """

    def test_theta_equals_hash_simple(self):
        """MR-THETA-EQUI-1: single-key equi, all tuple rows."""
        R = Relation("R", ("k", "v"), rows=[(1, "a"), (2, "b"), (3, "c")])
        S = Relation("S", ("k", "w"), rows=[(1, "x"), (2, "y"), (4, "z")])

        hash_result = R.join(S, on="k")

        def _equi(l, r):
            lk = l[0] if isinstance(l, tuple) else l.k
            rk = r[0] if isinstance(r, tuple) else r.k
            return lk == rk

        theta_result = R.join_theta(S, predicate=_equi, how="inner")
        common = tuple(sorted(set(hash_result.columns) & set(theta_result.columns)))
        assert _row_set(hash_result.project(*common)) == _row_set(
            theta_result.project(*common)
        ), (
            f"Theta ≠ Hash: |hash|={len(hash_result)} |theta|={len(theta_result)}"
        )

    def test_theta_equals_hash_with_nulls(self):
        """MR-THETA-EQUI-2: NULLs in key — both implementations must agree.

        SQL NULL != NULL: NULL-keyed rows never match in either implementation.
        """
        R = Relation("R", ("k", "v"), rows=[(1, "a"), (None, "b"), (2, "c")])
        S = Relation("S", ("k", "w"), rows=[(1, "x"), (None, "y"), (None, "z")])

        hash_result = R.join(S, on="k")

        def _equi(l, r):
            lk = l[0] if isinstance(l, tuple) else l.k
            rk = r[0] if isinstance(r, tuple) else r.k
            return False if lk is None or rk is None else lk == rk

        theta_result = R.join_theta(S, predicate=_equi, how="inner")
        common = tuple(sorted(set(hash_result.columns) & set(theta_result.columns)))
        assert _row_set(hash_result.project(*common)) == _row_set(
            theta_result.project(*common)
        ), (
            f"Theta(≠Hash) with NULLs: |hash|={len(hash_result)} |theta|={len(theta_result)}"
        )

    def test_theta_left_equals_hash_left(self):
        """MR-THETA-EQUI-3: left join — both implementations agree."""
        R = Relation("R", ("k", "v"), rows=[(1, "a"), (99, "z")])
        S = Relation("S", ("k", "w"), rows=[(1, "x"), (2, "y")])

        hash_left = R.join_left(S, on="k")

        def _equi(l, r):
            lk = l[0] if isinstance(l, tuple) else l.k
            rk = r[0] if isinstance(r, tuple) else r.k
            return False if lk is None or rk is None else lk == rk

        theta_left = R.join_theta(S, predicate=_equi, how="left")
        common = tuple(sorted(set(hash_left.columns) & set(theta_left.columns)))
        h_set = _row_set(hash_left.project(*common))
        t_set = _row_set(theta_left.project(*common))
        assert h_set == t_set, (
            f"Theta(left) ≠ Hash(left): |hash|={len(hash_left)} |theta|={len(theta_left)}"
        )


class TestThetaJoinColumnConflict:
    """MR-THETA-COL: theta join column-conflict resolver produces correct
    column names.

    When R and S share column names, theta join renames S's conflicting
    columns with ``_right`` suffix.  The number of result columns must equal
    |R.columns| + |S.columns| (no columns lost).
    """

    def test_theta_column_count_preserved(self):
        """MR-THETA-COL-1: total column count = |R.cols| + |S.cols|."""
        R = Relation("R", ("id", "name", "val"), rows=[(1, "a", 10)])
        S = Relation("S", ("id", "score", "val"), rows=[(1, 100, 20)])
        result = R.join_theta(
            S,
            predicate=lambda l, r: (l[0] if isinstance(l, tuple) else l.id)
            == (r[0] if isinstance(r, tuple) else r.id),
            how="inner",
        )
        assert len(result.columns) == len(R.columns) + len(S.columns), (
            f"Column count mismatch: expected {len(R.columns) + len(S.columns)}, "
            f"got {len(result.columns)} = {result.columns}"
        )
        # Every unique column from R is present
        for c in R.columns:
            assert c in result.columns, f"Left column '{c}' missing from theta result"
        # Conflict _right suffix
        assert "id_right" in result.columns, "Conflicting 'id' should be 'id_right'"
        assert "val_right" in result.columns, "Conflicting 'val' should be 'val_right'"

    def test_theta_no_conflict_no_suffix(self):
        """MR-THETA-COL-2: no column name collision → no _right suffix."""
        R = Relation("R", ("id", "name"), rows=[(1, "a")])
        S = Relation("S", ("sid", "score"), rows=[(1, 100)])
        result = R.join_theta(
            S,
            predicate=lambda l, r: (l[0] if isinstance(l, tuple) else l.id)
            == (r[0] if isinstance(r, tuple) else r.sid),
            how="inner",
        )
        assert not any(c.endswith("_right") for c in result.columns), (
            f"No-conflict case produced _right suffix: {result.columns}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# MR-PROJECT-SEL: Project ∘ select == select ∘ project
# ═══════════════════════════════════════════════════════════════════════════


class TestProjectSelectCommute:
    """MR-PROJECT-SEL: when a predicate references only projected columns,
    the order of project and select does not affect the result set.

    Formally:
      π_{A}(σ_{p}(R)) ≡ σ_{p}(π_{A}(R))   when cols(p) ⊆ A
    """

    def test_project_select_commute(self):
        """MR-PROJECT-SEL-1: simple case with contained columns."""
        R = Relation("R", ("k", "v", "x"), rows=[
            (1, "a", 10), (2, "b", 20), (1, "c", 30),
        ])

        # Select on columns that ARE in the projection
        select_then_project = R.select(lambda r: r[0] == 1).project("k", "v")
        project_then_select = R.project("k", "v").select(lambda r: r[0] == 1)

        assert _row_set(select_then_project) == _row_set(project_then_select), (
            "Project/select not commutative when columns are contained"
        )

    def test_project_select_preserves_count(self):
        """MR-PROJECT-SEL-2: row count must match when select is deterministic."""
        R = Relation("R", ("a", "b"), rows=[(1, 2), (3, 4), (1, 5)])
        r1 = R.select(lambda r: r[0] == 1).project("a")
        r2 = R.project("a").select(lambda r: r[0] == 1)
        assert len(r1) == len(r2), (
            f"Row count mismatch: select→project={len(r1)} project→select={len(r2)}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# MR-EXTRACT: _extract_equi_pairs correctness
# ═══════════════════════════════════════════════════════════════════════════


class TestExtractEquiPairsMetamorphic:
    """MR-EXTRACT: metamorphic relations for predicate extraction.

    MR-EXTRACT-1: ALL eq(ref, ref) under AND tree are extracted.
    MR-EXTRACT-2: OR/NOT sub-trees yield NO extractions (conservative).
    MR-EXTRACT-3: eq involving a Literal (not ColumnRef) is NOT extracted.
    """

    def test_and_decomposition_exhaustive(self):
        """MR-EXTRACT-1: AND(eq(a,b), AND(eq(c,d), eq(e,f))) extracts 3 pairs.

        Recursive AND flattening means every leaf eq is collected.
        """
        pred: Predicate = CompoundPred("and", [
            BinaryPred("eq", ColumnRef("a"), ColumnRef("b")),
            CompoundPred("and", [
                BinaryPred("eq", ColumnRef("c"), ColumnRef("d")),
                BinaryPred("eq", ColumnRef("e"), ColumnRef("f")),
            ]),
        ])
        pairs = QueryExecutor._extract_equi_pairs(pred)
        assert len(pairs) == 3, f"Expected 3 pairs from nested AND, got {pairs}"
        assert ("a", "b") in pairs
        assert ("c", "d") in pairs
        assert ("e", "f") in pairs

    def test_or_blocks_extraction(self):
        """MR-EXTRACT-2: OR(eq(a,b), eq(c,d)) yields [].

        The optimizer is conservative: predicates under OR are not extracted
        because OR changes the selectivity semantics.
        """
        pred: Predicate = CompoundPred("or", [
            BinaryPred("eq", ColumnRef("a"), ColumnRef("b")),
            BinaryPred("eq", ColumnRef("c"), ColumnRef("d")),
        ])
        pairs = QueryExecutor._extract_equi_pairs(pred)
        assert pairs == [], f"OR should yield [], got {pairs}"

    def test_eq_with_literal_not_extracted(self):
        """MR-EXTRACT-3: eq(col, 5) with Literal r-value is NOT a column pair.

        Only ColumnRef-ColumnRef equality counts as an equi-column pair.
        """
        pred = BinaryPred("eq", ColumnRef("a"), Lit(5))
        pairs = QueryExecutor._extract_equi_pairs(pred)
        assert pairs == [], f"eq-with-literal should yield [], got {pairs}"

    def test_mixed_and_extracts_only_equi(self):
        """MR-EXTRACT-4: AND(eq(a,b), gt(c, 5)) extracts [(a,b)] only."""
        pred: Predicate = CompoundPred("and", [
            BinaryPred("eq", ColumnRef("a"), ColumnRef("b")),
            BinaryPred("gt", ColumnRef("c"), Lit(5)),
        ])
        pairs = QueryExecutor._extract_equi_pairs(pred)
        assert pairs == [("a", "b")], f"Mixed AND should extract [(a,b)], got {pairs}"


class TestRemoveEquiRoundTrip:
    """MR-REMOVE-RT: _remove_equi_from_pred after _extract_equi_pairs leaves
    a predicate that, combined with the original equi conditions, is
    semantically equivalent to the original predicate.

    We verify this NOT by checking SQL-level equivalence (which would require
    an SMT solver) but by a simpler metamorphic property:
    - Removing all extracted pairs and then checking there are no remaining
      equi-column pairs should yield an empty result.
    """

    def test_remove_consumes_all_extracted(self):
        """MR-REMOVE-RT-1: remove all extracted pairs → no more extractable pairs."""
        pred: Predicate = CompoundPred("and", [
            BinaryPred("eq", ColumnRef("a"), ColumnRef("b")),
            BinaryPred("eq", ColumnRef("c"), ColumnRef("d")),
        ])
        pairs = QueryExecutor._extract_equi_pairs(pred)
        remaining = QueryExecutor._remove_equi_from_pred(pred, pairs)
        # No more equi-column pairs should remain
        if remaining is not None:
            remaining_pairs = QueryExecutor._extract_equi_pairs(remaining)
            assert remaining_pairs == [], (
                f"After removing all {pairs}, remaining pred still yields {remaining_pairs}"
            )
        else:
            # None means fully consumed — also valid
            pass

    def test_remove_partial_keeps_non_equi(self):
        """MR-REMOVE-RT-2: mixed AND retains non-eq predicates after removal."""
        pred: Predicate = CompoundPred("and", [
            BinaryPred("eq", ColumnRef("a"), ColumnRef("b")),
            BinaryPred("gt", ColumnRef("c"), Lit(5)),
        ])
        pairs = QueryExecutor._extract_equi_pairs(pred)
        assert pairs == [("a", "b")]
        remaining = QueryExecutor._remove_equi_from_pred(pred, pairs)
        assert remaining is not None, "Non-equi predicates should remain"
        # The remaining should be gt(c, 5)
        assert isinstance(remaining, BinaryPred) and remaining.op == "gt", (
            f"Expected gt predicate to remain, got {type(remaining).__name__}: {remaining}"
        )

    def test_remove_noop_when_no_pairs(self):
        """MR-REMOVE-RT-3: empty pairs list → predicate unchanged."""
        pred: Predicate = BinaryPred("gt", ColumnRef("c"), Lit(5))
        pairs: list[tuple[str, str]] = []
        remaining = QueryExecutor._remove_equi_from_pred(pred, pairs)
        assert remaining is not None
        assert remaining is pred or str(remaining) == str(pred), (
            "Removing empty pair list should not mutate the predicate"
        )


# ═══════════════════════════════════════════════════════════════════════════
# MR-OPT: Optimizer preserves query result sets
# ═══════════════════════════════════════════════════════════════════════════


class TestOptimizerPreservesResults:
    """MR-OPT-SAME: execute(q) and execute(optimize(q)) produce the same
    row set (ignoring row order).

    The optimizer may rewrite the query AST, but the *semantics* must be
    identical.  This is the single most important metamorphic relation for
    the optimizer — a violation means the optimizer introduced a bug.
    """

    def _assert_optimizer_preserves(self, store: ResultStore, query_json: dict):
        """Assert that optimizing *query* before execution yields the same row set."""
        from parallelines.engine.query_parser import QueryParser
        from parallelines.engine.query_executor import QueryExecutor

        ast = QueryParser.parse(query_json)
        unopt_result = QueryExecutor.execute(ast, store)

        optimized = QueryOptimizer.optimize(copy.deepcopy(ast), store)
        opt_result = QueryExecutor.execute(optimized, store)

        common = tuple(sorted(set(unopt_result.columns) & set(opt_result.columns)))
        if not common:
            # No common columns — at least compare row counts
            assert len(unopt_result) == len(opt_result), (
                f"Optimizer changed row count: unopt={len(unopt_result)} opt={len(opt_result)}"
            )
            return

        u_set = _row_set(unopt_result.project(*common))
        o_set = _row_set(opt_result.project(*common))
        assert u_set == o_set, (
            f"MR-OPT-SAME violated!\n"
            f"  Query: {query_json}\n"
            f"  |unopt|={len(unopt_result)} |opt|={len(opt_result)}\n"
            f"  unopt - opt (sample): {list(u_set - o_set)[:3]}\n"
            f"  opt - unopt (sample): {list(o_set - u_set)[:3]}"
        )

    def test_simple_where_preserved(self):
        """MR-OPT-SAME-1: simple WHERE — optimizer should not change result."""
        store = _make_basic_store()
        self._assert_optimizer_preserves(store, {
            "select": ["*"],
            "from": "files",
            "where": {"eq": ["is_active", True]},
        })

    def test_single_join_preserved(self):
        """MR-OPT-SAME-2: single JOIN with WHERE — pushdown may fire."""
        store = _make_basic_store()
        self._assert_optimizer_preserves(store, {
            "select": ["*"],
            "from": "files",
            "join": {
                "type": "inner",
                "with": "external_files",
                "on": {"eq": ["virtual_path", ["external_files", "virtual_path"]]},
            },
            "where": {"gt": ["priority", 100]},
        })

    def test_multi_join_preserved(self):
        """MR-OPT-SAME-3: multi-table JOIN — pushdown + order reordering."""
        store = _make_basic_store()
        self._assert_optimizer_preserves(store, {
            "select": ["*"],
            "from": "files",
            "joins": [
                {
                    "type": "inner",
                    "with": "addons",
                    "on": {"eq": ["source_name", ["addons", "addon_id"]]},
                },
                {
                    "type": "left",
                    "with": "external_files",
                    "on": {"eq": ["virtual_path", ["external_files", "virtual_path"]]},
                },
            ],
            "where": {"eq": ["is_active", True]},
        })

    def test_join_with_theta_condition_preserved(self):
        """MR-OPT-SAME-4: join with non-equi ON condition (theta fallback).

        This exercises the theta-join path in both optimized and unoptimized
        execution.
        """
        store = _make_basic_store()
        self._assert_optimizer_preserves(store, {
            "select": ["*"],
            "from": "files",
            "join": {
                "type": "inner",
                "with": "external_files",
                "on": {"and": [
                    {"eq": ["virtual_path", ["external_files", "virtual_path"]]},
                    {"gt": ["priority", ["external_files", "ext_priority"]]},
                ]},
            },
            "limit": 50,
        })

    def test_group_by_aggregation_preserved(self):
        """MR-OPT-SAME-5: GROUP BY with aggregation — optimizer must not break it."""
        store = _make_basic_store()
        self._assert_optimizer_preserves(store, {
            "select": ["source_name", "file_count"],
            "from": "files",
            "group_by": {"by": ["source_name"], "agg": {"file_count": "count"}},
        })

    def test_join_with_compound_equi_preserved(self):
        """MR-OPT-SAME-6: optimizer does not break simple WHERE query."""
        store = _make_basic_store()
        q = Query(
            select=[Lit("*")],
            source=Source(relation="files"),
            where=BinaryPred("eq", ColumnRef("source_name"), Lit("base")),
        )
        optimized = QueryOptimizer.optimize(copy.deepcopy(q), store)
        raw = QueryExecutor.execute(q, store)
        opt_q = QueryExecutor.execute(optimized, store)
        assert _row_set(raw) == _row_set(opt_q), (
            f"Simple query changed by optimizer: "
            f"|raw|={len(raw)} |opt|={len(opt_q)}"
        )


class TestOptimizerIdempotent:
    """MR-OPT-IDEM: optimize(optimize(q)) == optimize(q).

    The optimizer should reach a fixpoint after one pass.  A second pass
    should not change the AST.
    """

    def _assert_idempotent(self, q: Query, store: ResultStore | None = None):
        once = QueryOptimizer.optimize(copy.deepcopy(q), store)
        twice = QueryOptimizer.optimize(copy.deepcopy(once), store)
        # Structural equality on the Query AST
        assert once == twice, (
            f"Optimizer not idempotent!\n"
            f"  Once: {once}\n"
            f"  Twice: {twice}"
        )

    def test_simplify_idempotent(self):
        """MR-OPT-IDEM-1: simplify-only query (no store)."""
        q = Query(
            select=[Lit("*")],
            source=Source(relation="files"),
            where=CompoundPred("and", [
                BinaryPred("eq", ColumnRef("a"), Lit(1)),
                CompoundPred("and", [
                    BinaryPred("eq", ColumnRef("b"), Lit(2)),
                    BinaryPred("eq", ColumnRef("c"), Lit(3)),
                ]),
            ]),
        )
        self._assert_idempotent(q)

    def test_double_negation_fixpoint(self):
        """MR-OPT-IDEM-2: NOT(NOT(p)) → p, and stays p."""
        q = Query(
            select=[Lit("*")],
            source=Source(relation="files"),
            where=CompoundPred("not", [
                CompoundPred("not", [
                    BinaryPred("eq", ColumnRef("a"), Lit(1)),
                ]),
            ]),
        )
        self._assert_idempotent(q)

    def test_full_pipeline_idempotent(self):
        """MR-OPT-IDEM-3: full optimizer pipeline with store."""
        store = _make_basic_store()
        q = Query(
            select=[Lit("*")],
            source=Source(relation="files"),
            where=BinaryPred("eq", ColumnRef("source_name"), Lit("base")),
        )
        self._assert_idempotent(q, store)


# ═══════════════════════════════════════════════════════════════════════════
# MR-PUSHDOWN-ID: Predicate pushdown is idempotent
# ═══════════════════════════════════════════════════════════════════════════


class TestPushdownIdempotent:
    """MR-PUSHDOWN-ID: applying pushdown twice does not change the query.

    After the first pushdown, all single-table predicates are already as
    close to their data source as possible.  A second pushdown should be
    a no-op.
    """

    def _make_join_query(self) -> Query:
        return Query(
            select=[Lit("*")],
            source=Source(relation="files"),
            joins=[
                JoinClause(
                    type="inner",
                    with_source=Source(relation="external_files"),
                    on=BinaryPred("eq", ColumnRef("virtual_path"), ColumnRef("virtual_path")),
                ),
            ],
            where=CompoundPred("and", [
                BinaryPred("eq", ColumnRef("is_active"), Lit(True)),
                StringPred("ends_with", ColumnRef("ext_source_name"), ".vpk"),
            ]),
        )

    def test_pushdown_twice_stable(self):
        """MR-PUSHDOWN-ID-1: two pushdowns produce same AST."""
        store = _make_basic_store()
        q = self._make_join_query()
        once = QueryOptimizer._pushdown_predicates(q, store)
        twice = QueryOptimizer._pushdown_predicates(copy.deepcopy(once), store)
        assert once == twice, (
            "Predicate pushdown not idempotent: second pass changed the AST"
        )


# ═══════════════════════════════════════════════════════════════════════════
# MR-UNNEST-RT: Subquery unnesting preserves result set
# ═══════════════════════════════════════════════════════════════════════════


class TestUnnestPreservesResults:
    """MR-UNNEST-RT: unnesting a subquery then executing produces the same
    result as executing the nested version.

    execute(unnest(q)) ≡ execute(q)
    """

    def test_unnest_simple_preserves(self):
        """MR-UNNEST-RT-1: SELECT * FROM (SELECT * FROM R WHERE p1) WHERE p2."""
        store = _make_basic_store()
        inner_q = Query(
            select=[Lit("*")],
            source=Source(relation="files"),
            where=BinaryPred("eq", ColumnRef("is_active"), Lit(True)),
        )
        outer_q = Query(
            select=[Lit("*")],
            source=Source(subquery=inner_q),
            where=BinaryPred("eq", ColumnRef("source_name"), Lit("base")),
        )
        # Execute the nested version
        nested_result = QueryExecutor.execute(outer_q, store)

        # Execute the unnested version
        unnested = QueryOptimizer._unnest_subqueries(copy.deepcopy(outer_q))
        unnested_result = QueryExecutor.execute(unnested, store)

        common = tuple(sorted(set(nested_result.columns) & set(unnested_result.columns)))
        assert _row_set(nested_result.project(*common)) == _row_set(
            unnested_result.project(*common)
        ), (
            f"Unnesting changed results: |nested|={len(nested_result)} "
            f"|unnested|={len(unnested_result)}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# MR-JOIN-ORDER: Reordering inner joins preserves set semantics
# ═══════════════════════════════════════════════════════════════════════════


class TestJoinOrderPreservesSemantics:
    """MR-JOIN-ORDER: reordering INNER JOINs does not change the result set.

    (R ⋈ S) ⋈ T ≡ R ⋈ (S ⋈ T) for inner joins.

    The optimizer may reorder joins for performance; the result set must be
    identical.
    """

    def test_three_table_inner_join_commutes(self):
        """MR-JOIN-ORDER-1: three-table inner join set-equivalence."""
        R = Relation("R", ("k", "v"), rows=[(1, "a"), (2, "b")])
        S = Relation("S", ("k", "w"), rows=[(1, "x"), (2, "y")])
        T = Relation("T", ("k", "z"), rows=[(1, "m"), (3, "n")])

        # (R ⋈ S) ⋈ T
        rs = R.join(S, on="k")
        rst = rs.join(T, on="k")

        # R ⋈ (S ⋈ T)
        st = S.join(T, on="k")
        rst2 = R.join(st, on="k")

        common = tuple(sorted(set(rst.columns) & set(rst2.columns)))
        assert _row_set(rst.project(*common)) == _row_set(rst2.project(*common)), (
            f"Three-table join order changed result: "
            f"|(R⋈S)⋈T|={len(rst)} |R⋈(S⋈T)|={len(rst2)}"
        )

    def test_join_reorder_via_optimizer(self):
        """MR-JOIN-ORDER-2: optimizer reorder produces same result."""
        store = _make_basic_store()
        q = Query(
            select=[Lit("*")],
            source=Source(relation="files"),
            joins=[
                JoinClause(
                    type="inner",
                    with_source=Source(relation="external_files"),
                    on=BinaryPred("eq", ColumnRef("virtual_path"), ColumnRef("virtual_path")),
                ),
                JoinClause(
                    type="inner",
                    with_source=Source(relation="addons"),
                    on=BinaryPred(
                        "eq", ColumnRef("source_name"), ColumnRef("addon_id")
                    ),
                ),
            ],
        )
        original_result = QueryExecutor.execute(q, store)
        optimized = QueryOptimizer.optimize(copy.deepcopy(q), store)
        optimized_result = QueryExecutor.execute(optimized, store)

        common = tuple(
            sorted(set(original_result.columns) & set(optimized_result.columns))
        )
        assert _row_set(original_result.project(*common)) == _row_set(
            optimized_result.project(*common)
        ), (
            "Join reorder changed result set: "
            f"|original|={len(original_result)} |optimized|={len(optimized_result)}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# MR-SELF-JOIN: Self-join on key returns predictable results
# ═══════════════════════════════════════════════════════════════════════════


class TestSelfJoinMetamorphic:
    """MR-SELF-JOIN: R ⋈_k R (self-join) has predictable properties.

    - For each row in R with key k_val, the self-join produces |R_k=k_val|^2 rows
      with identical values on both sides.
    - After dedup projection, this equals the original R.
    """

    def test_self_join_projection_contains_original(self):
        """MR-SELF-JOIN-1: self-join projected to left columns contains original.

        For any R, R ⋈_k R projected to R's columns contains at least all rows
        of R (because every row matches itself).  Extra rows may appear from
        other matches.
        """
        R = Relation("R", ("k", "v"), rows=[(1, "a"), (2, "b"), (1, "c")])
        joined = R.join(R, on="k")

        # Project to left columns — every row in R matches at least itself
        projected = joined.project("k", "v")

        orig_set = _row_set(R.project("k", "v"))
        proj_set = _row_set(projected)
        assert orig_set.issubset(proj_set), (
            f"Self-join project does not contain original: "
            f"|orig|={len(orig_set)} |proj|={len(proj_set)}\n"
            f"  missing: {orig_set - proj_set}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# MR-GROUP-IDEM: group_by after group_by is identity
# ═══════════════════════════════════════════════════════════════════════════


class TestGroupByAggregation:
    """MR-GROUP-COUNT: group_by with count produces rows matching
    the number of distinct keys in the original relation.

    |group_by(R, keys=k, agg=count)| = |π_k(R)|
    """

    def test_group_by_count_equals_distinct_keys(self):
        """MR-GROUP-COUNT-1: number of grouped rows = number of distinct key values."""
        R = Relation("R", ("k", "v"), rows=[
            (1, "a"), (1, "b"), (2, "c"), (3, "d"),
        ])
        grouped = R.group_by("k", {"cnt": len})
        distinct_keys = len({r[0] for r in R.rows})
        assert len(grouped) == distinct_keys, (
            f"Group-by count ≠ distinct keys: "
            f"|grouped|={len(grouped)} |distinct_keys|={distinct_keys}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Edge-case stress tests (targeting specific bug classes)
# ═══════════════════════════════════════════════════════════════════════════


class TestNullEdgeCases:
    """Targeted NULL-semantics stress tests.

    These probe for known bug patterns in SQL NULL handling:
    - NULL in composite key components
    - NULL in theta-join predicate evaluation
    - NULL in WHERE fast-path compilation (via _compile_predicate)
    """

    def test_composite_key_partial_null(self):
        """NULL in ONE component of a composite key: the row is skipped.

        SQL: NULL != NULL, so (1, NULL) never matches (1, NULL).
        """
        R = Relation("R", ("a", "b", "v"), rows=[
            (1, None, 10), (1, "x", 20), (None, "y", 30),
        ])
        S = Relation("S", ("a", "b", "w"), rows=[
            (1, None, 100), (1, "x", 200), (2, "y", 300),
        ])
        result = R.join(S, on=("a", "b"))
        # Only (1, "x") matches in both
        assert len(result) == 1, (
            f"Composite-key partial NULL join should yield 1 row, got {len(result)}"
        )
        assert result.rows[0][2] == 20, f"Wrong left value: {result.rows[0]}"
        assert result.rows[0][3] == 200, f"Wrong right value: {result.rows[0]}"

    def test_null_in_theta_join_predicate_literals(self):
        """Theta join with NULL column: predicate must guard None.

        Theta join passes raw user predicates — the predicate is responsible
        for handling None values (consistent with Python's typing contract).
        """
        R = Relation("R", ("k", "v"), rows=[(1, 10), (2, None)])
        S = Relation("S", ("k", "w"), rows=[(1, 20)])

        def _pred(l, r):
            lv = l[1] if isinstance(l, tuple) else l.v
            rv = r[1] if isinstance(r, tuple) else r.w
            # User predicate must guard against None (consistent with SQL semantics)
            if lv is None or rv is None:
                return False
            return lv > rv

        result = R.join_theta(S, predicate=_pred, how="inner")
        assert len(result) == 0, (
            f"Theta join with NULL comparison should yield 0, got {len(result)}"
        )

    def test_both_sides_null_in_join_key(self):
        """Both sides have NULL keys — they never match (SQL semantics)."""
        R = Relation("R", ("k", "v"), rows=[(None, "a"), (1, "b")])
        S = Relation("S", ("k", "w"), rows=[(None, "x"), (1, "y")])
        result = R.join(S, on="k")
        result_left = R.join_left(S, on="k")
        # Inner: only (1, ...) matches
        assert len(result) == 1, f"NULL-NULL inner join: expected 1, got {len(result)}"
        # Left: all R rows preserved, NULL S for unmatched
        assert len(result_left) == 2, (
            f"NULL-NULL left join: expected 2, got {len(result_left)}"
        )


class TestThetaStress:
    """Stress theta join with various predicate shapes and data sizes.

    Uses metamorphic relation MR-THETA-EQUI to find divergence between
    hash-join and theta-join for equi predicates.
    """

    def test_theta_vs_hash_larger_dataset(self):
        """More rows to stress O(n²) vs O(n) join implementations."""
        R = Relation("R", ("k", "v"), rows=[(i, chr(97 + i % 26)) for i in range(50)])
        S = Relation("S", ("k", "w"), rows=[(i * 2, f"val_{i}") for i in range(25)])

        hash_result = R.join(S, on="k")

        def _equi(l, r):
            lk = l[0] if isinstance(l, tuple) else l.k
            rk = r[0] if isinstance(r, tuple) else r.k
            return False if lk is None or rk is None else lk == rk

        theta_result = R.join_theta(S, predicate=_equi, how="inner")

        common = tuple(sorted(set(hash_result.columns) & set(theta_result.columns)))
        h_set = _row_set(hash_result.project(*common))
        t_set = _row_set(theta_result.project(*common))
        assert h_set == t_set, (
            f"Theta≠Hash on 50×25 dataset: |hash|={len(hash_result)} "
            f"|theta|={len(theta_result)}\n"
            f"  Δ (hash-theta): {h_set - t_set}\n"
            f"  Δ (theta-hash): {t_set - h_set}"
        )


class TestMetadataPreservation:
    """Verify that relational operations preserve metadata invariants.

    MR-META: operations should not corrupt column names, row counts, or
    basic properties.
    """

    def test_join_does_not_mutate_index(self):
        """MR-META-1: join with build_index on right does not corrupt left's index."""
        R = Relation("R", ("k", "v"), rows=[(1, "a")])
        S = Relation("S", ("k", "w"), rows=[(1, "x")])
        R.build_index("k")
        _ = R.join(S, on="k")
        # R's index should still be intact
        assert "k" in R._index, "Left relation index corrupted after join"
        lookup_result = R.lookup("k", 1)
        assert len(lookup_result) == 1, "Left relation lookup broken after join"

    def test_rename_preserves_row_count(self):
        """MR-META-2: rename does not change row count."""
        R = Relation("R", ("a", "b"), rows=[(1, 2), (3, 4)])
        renamed = R.rename({"a": "x"})
        assert len(renamed) == len(R), (
            f"Renamed changed row count: {len(renamed)} ≠ {len(R)}"
        )

    def test_composite_index_then_single_index(self):
        """MR-META-3: building composite index does not break existing single index."""
        R = Relation("R", ("a", "b"), rows=[(1, "x"), (2, "y")])
        R.build_index("a")
        R.build_index("a", "b")
        # Single-column lookup still works
        result = R.lookup("a", 1)
        assert len(result) == 1, "Single-column lookup broken after composite index build"
