"""Hypothesis property tests for Relation algebra laws."""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings, strategies as st

from parallelines.engine import Relation
from parallelines.engine.schema import FileRow


# Strategy: generate random FileRow lists
@st.composite
def file_rows(draw):
    """Generate a list of FileRow for testing."""
    n = draw(st.integers(min_value=0, max_value=10))
    rows = []
    for i in range(n):
        rows.append(
            FileRow(
                virtual_path=f"file_{i}.txt",
                source_name=draw(st.sampled_from(["base", "addon_a", "addon_b"])),
                source_type=draw(st.sampled_from(["game", "addon"])),
                priority=draw(st.integers(min_value=1, max_value=1000)),
                file_hash=draw(st.text(min_size=3, max_size=8)),
                file_size=draw(st.integers(min_value=0, max_value=65536)),
                is_active=True,
                is_dead=draw(st.booleans()),
                is_redundant=False,
            )
        )
    return rows


@given(file_rows())
@settings(suppress_health_check=[HealthCheck.too_slow])
def test_select_idempotent(rows):
    """select(p, select(p, R)) == select(p, R)"""
    rel = Relation.from_rows("files", rows)
    r1 = rel.select(lambda r: r.is_dead).select(lambda r: r.is_dead)
    r2 = rel.select(lambda r: r.is_dead)
    assert len(r1) == len(r2)


@given(file_rows())
@settings(suppress_health_check=[HealthCheck.too_slow])
def test_select_commutative(rows):
    """select(p1, select(p2, R)) == select(p2, select(p1, R))"""
    rel = Relation.from_rows("files", rows)
    r1 = rel.select(lambda r: r.is_dead).select(lambda r: r.source_type == "addon")
    r2 = rel.select(lambda r: r.source_type == "addon").select(lambda r: r.is_dead)
    assert len(r1) == len(r2)
    assert {r.virtual_path for r in r1} == {r.virtual_path for r in r2}


@given(file_rows())
@settings(suppress_health_check=[HealthCheck.too_slow])
def test_select_project_commute(rows):
    """project(select(R)) == select(project(R)) when predicate columns are in projection"""
    if not rows:
        return  # empty relation has no columns; nothing to project
    rel = Relation.from_rows("files", rows)
    # Select first, then project
    r1 = rel.select(lambda r: r.is_dead).project("source_name", "is_dead")
    # Project first, then select (after project, rows are tuples indexed by columns)
    r2 = rel.project("source_name", "is_dead").select(lambda r: r[1])
    # Compare sets of tuples (order may differ)
    assert set(r1.rows) == set(r2.rows)


@given(file_rows())
@settings(suppress_health_check=[HealthCheck.too_slow])
def test_project_idempotent(rows):
    """project(A, project(A, R)) == project(A, R)"""
    if not rows:
        return  # empty relation has no columns; nothing to project
    rel = Relation.from_rows("files", rows)
    r1 = rel.project("source_name").project("source_name")
    r2 = rel.project("source_name")
    assert set(r1.rows) == set(r2.rows)


@given(file_rows())
@settings(suppress_health_check=[HealthCheck.too_slow])
def test_select_no_match(rows):
    """select with always-false predicate returns empty relation."""
    result = Relation.from_rows("files", rows).select(lambda r: False)
    assert len(result) == 0


@given(file_rows())
@settings(suppress_health_check=[HealthCheck.too_slow])
def test_select_all_match(rows):
    """select with always-true predicate returns all rows."""
    rel = Relation.from_rows("files", rows)
    result = rel.select(lambda r: True)
    assert len(result) == len(rel)
