"""Layer 3 — 差分测试：Python API vs JSON DSL 查询引擎。

同一查询的两种 API 路径必须产生相同结果。
如果两个 API 结果不一致，则至少有一个实现存在 bug。
本测试不关心"哪个是正确的"——只检测不一致。
"""
from __future__ import annotations

from typing import Any

import pytest

_HYPOTHESIS_AVAILABLE: bool = False
try:
    from hypothesis import given, settings, strategies as st, HealthCheck

    _HYPOTHESIS_AVAILABLE = True
except ImportError:
    # no-op fallbacks so decorator syntax doesn't crash at module load time
    def given(*args: Any, **kwargs: Any) -> Any:  # type: ignore[misc]
        return lambda f: f

    def settings(*args: Any, **kwargs: Any) -> Any:  # type: ignore[misc]
        return lambda f: f

    st = None  # type: ignore[assignment]


from parallelines.engine import FileRow, Relation, ResultStore


# ── Comparison helper ──────────────────────────────────────────


def _compare(py_rel: Relation, json_rel: Relation) -> None:
    """Assert that two Relations are semantically identical.

    Checks column schema, row count, and sorted row content (as dicts).
    """
    assert py_rel.columns == json_rel.columns, (
        f"Column mismatch:\n"
        f"  Python API: {py_rel.columns}\n"
        f"  JSON DSL:   {json_rel.columns}"
    )
    assert len(py_rel) == len(json_rel), (
        f"Row count mismatch: Python API {len(py_rel)} != JSON DSL {len(json_rel)}"
    )

    def _sort_key(d: dict) -> tuple:
        return tuple(str(v) for k, v in sorted(d.items()))

    py_sorted = sorted(py_rel.to_dicts(), key=_sort_key)
    json_sorted = sorted(json_rel.to_dicts(), key=_sort_key)
    assert py_sorted == json_sorted, (
        "Row content mismatch between Python API and JSON DSL\n"
        f"  Python API rows: {py_sorted}\n"
        f"  JSON DSL rows:   {json_sorted}"
    )


def _make_store(rows: list[FileRow]) -> ResultStore:
    """Build a ResultStore populated with the given FileRow list."""
    store = ResultStore()
    store.files = Relation[FileRow].from_rows("files", rows)
    return store


# ── Hypothesis strategies ──────────────────────────────────────

if _HYPOTHESIS_AVAILABLE:

    @st.composite
    def file_row_lists(draw) -> list[FileRow]:
        """Generate 5--30 random FileRow instances."""
        count = draw(st.integers(min_value=5, max_value=30))
        source_names = [
            "addon_a",
            "addon_b",
            "addon_c",
            "game_base",
            "vpk_patch",
        ]
        source_types = ["vpk", "game", "addon"]

        rows: list[FileRow] = []
        for i in range(count):
            rows.append(
                FileRow(
                    virtual_path=f"materials/test/file_{i:04d}.vmt",
                    source_name=draw(st.sampled_from(source_names)),
                    source_type=draw(st.sampled_from(source_types)),
                    priority=draw(st.integers(min_value=0, max_value=100)),
                    file_hash=draw(
                        st.text(
                            min_size=8,
                            max_size=8,
                            alphabet="0123456789abcdef",
                        )
                    ),
                    file_size=draw(st.integers(min_value=0, max_value=1_000_000)),
                    is_active=draw(st.booleans()),
                    is_redundant=draw(st.booleans()),
                    is_enabled=True,
                )
            )
        return rows


# ── Test: select equivalence (gt predicate) ────────────────────


@pytest.mark.skipif(
    not _HYPOTHESIS_AVAILABLE, reason="hypothesis not installed"
)
@given(rows=file_row_lists())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_select_equivalence(rows: list[FileRow]) -> None:
    """Python ``select(lambda r: r.priority > 50)`` matches JSON ``where: {gt: ...}``."""
    store = _make_store(rows)

    # Python API
    py_result = store.files.select(lambda r: r.priority > 50)

    # JSON DSL
    json_result = store.execute(
        {
            "select": ["*"],
            "from": "files",
            "where": {"gt": ["priority", 50]},
        }
    )

    _compare(py_result, json_result)


# ── Test: project equivalence ──────────────────────────────────


@pytest.mark.skipif(
    not _HYPOTHESIS_AVAILABLE, reason="hypothesis not installed"
)
@given(rows=file_row_lists())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_project_equivalence(rows: list[FileRow]) -> None:
    """Python ``project("virtual_path", "source_name")`` matches JSON ``select: [...]``."""
    store = _make_store(rows)

    # Python API
    py_result = store.files.project("virtual_path", "source_name")

    # JSON DSL
    json_result = store.execute(
        {
            "select": ["virtual_path", "source_name"],
            "from": "files",
        }
    )

    _compare(py_result, json_result)


# ── Test: select + project chain ───────────────────────────────


@pytest.mark.skipif(
    not _HYPOTHESIS_AVAILABLE, reason="hypothesis not installed"
)
@given(rows=file_row_lists())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_select_project_chain(rows: list[FileRow]) -> None:
    """Python ``select(...).project(...)`` matches JSON with both ``select`` and ``where``."""
    store = _make_store(rows)

    # Python API: chain select then project.
    py_result = (
        store.files.select(lambda r: r.priority > 50).project(
            "virtual_path", "source_name"
        )
    )

    # JSON DSL: both select and where in one dict.
    json_result = store.execute(
        {
            "select": ["virtual_path", "source_name"],
            "from": "files",
            "where": {"gt": ["priority", 50]},
        }
    )

    _compare(py_result, json_result)


# ── Test: combined predicates (AND) ────────────────────────────


@pytest.mark.skipif(
    not _HYPOTHESIS_AVAILABLE, reason="hypothesis not installed"
)
@given(rows=file_row_lists())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_combined_predicates(rows: list[FileRow]) -> None:
    """Python compound AND predicate matches JSON ``and``."""
    store = _make_store(rows)

    # Python API: priority > 50 AND is_active == True.
    py_result = store.files.select(
        lambda r: r.priority > 50 and r.is_active
    )

    # JSON DSL
    json_result = store.execute(
        {
            "select": ["*"],
            "from": "files",
            "where": {
                "and": [
                    {"gt": ["priority", 50]},
                    {"eq": ["is_active", True]},
                ]
            },
        }
    )

    _compare(py_result, json_result)


# ── Test: combined predicates (OR) ─────────────────────────────


@pytest.mark.skipif(
    not _HYPOTHESIS_AVAILABLE, reason="hypothesis not installed"
)
@given(rows=file_row_lists())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_combined_predicates_or(rows: list[FileRow]) -> None:
    """Python OR predicate matches JSON ``or``."""
    store = _make_store(rows)

    # Python API: priority < 10 OR is_redundant == True.
    py_result = store.files.select(
        lambda r: r.priority < 10 or r.is_redundant
    )

    # JSON DSL
    json_result = store.execute(
        {
            "select": ["*"],
            "from": "files",
            "where": {
                "or": [
                    {"lt": ["priority", 10]},
                    {"eq": ["is_redundant", True]},
                ]
            },
        }
    )

    _compare(py_result, json_result)


# ── Test: combined predicates (three-way AND) ──────────────────


@pytest.mark.skipif(
    not _HYPOTHESIS_AVAILABLE, reason="hypothesis not installed"
)
@given(rows=file_row_lists())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_three_way_and(rows: list[FileRow]) -> None:
    """Three-way conjunction: both APIs must return the same rows."""
    store = _make_store(rows)

    # Python API: priority > 30 AND is_active AND source_type == "vpk".
    py_result = store.files.select(
        lambda r: r.priority > 30 and r.is_active and r.source_type == "vpk"
    )

    # JSON DSL
    json_result = store.execute(
        {
            "select": ["*"],
            "from": "files",
            "where": {
                "and": [
                    {"gt": ["priority", 30]},
                    {"eq": ["is_active", True]},
                    {"eq": ["source_type", "vpk"]},
                ]
            },
        }
    )

    _compare(py_result, json_result)


# ── Test: empty result ─────────────────────────────────────────


@pytest.mark.skipif(
    not _HYPOTHESIS_AVAILABLE, reason="hypothesis not installed"
)
@given(rows=file_row_lists())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_empty_result(rows: list[FileRow]) -> None:
    """Predicate that matches nothing => both paths return an empty Relation."""
    store = _make_store(rows)

    # Python API: impossible predicate.
    py_result = store.files.select(lambda r: r.priority > 9999)

    # JSON DSL
    json_result = store.execute(
        {
            "select": ["*"],
            "from": "files",
            "where": {"gt": ["priority", 9999]},
        }
    )

    _compare(py_result, json_result)

    # Also verify with projection — columns differ from the wildcard case.
    py_proj = store.files.select(lambda r: r.priority > 9999).project(
        "virtual_path"
    )
    json_proj = store.execute(
        {
            "select": ["virtual_path"],
            "from": "files",
            "where": {"gt": ["priority", 9999]},
        }
    )
    _compare(py_proj, json_proj)


# ── Test: all rows (no filter) ─────────────────────────────────


@pytest.mark.skipif(
    not _HYPOTHESIS_AVAILABLE, reason="hypothesis not installed"
)
@given(rows=file_row_lists())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_all_rows(rows: list[FileRow]) -> None:
    """No filter at all => both paths return every row unchanged."""
    store = _make_store(rows)

    # Python API: no select call, raw relation.
    py_result = store.files

    # JSON DSL: no where clause.
    json_result = store.execute(
        {
            "select": ["*"],
            "from": "files",
        }
    )

    _compare(py_result, json_result)


# ── Test: in predicate ─────────────────────────────────────────


@pytest.mark.skipif(
    not _HYPOTHESIS_AVAILABLE, reason="hypothesis not installed"
)
@given(rows=file_row_lists())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_in_predicate(rows: list[FileRow]) -> None:
    """Python ``r.source_name in ("addon_a", "addon_c")`` matches JSON ``in``."""
    store = _make_store(rows)
    target_sources = ("addon_a", "addon_c")

    # Python API
    py_result = store.files.select(
        lambda r: r.source_name in target_sources
    )

    # JSON DSL
    json_result = store.execute(
        {
            "select": ["*"],
            "from": "files",
            "where": {
                "in": ["source_name", ["addon_a", "addon_c"]]
            },
        }
    )

    _compare(py_result, json_result)


# ── Test: not_in predicate ─────────────────────────────────────


@pytest.mark.skipif(
    not _HYPOTHESIS_AVAILABLE, reason="hypothesis not installed"
)
@given(rows=file_row_lists())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_not_in_predicate(rows: list[FileRow]) -> None:
    """Python ``r.source_name not in ("game_base",)`` matches JSON ``not_in``."""
    store = _make_store(rows)

    # Python API
    py_result = store.files.select(
        lambda r: r.source_name not in ("game_base",)
    )

    # JSON DSL
    json_result = store.execute(
        {
            "select": ["*"],
            "from": "files",
            "where": {
                "not_in": ["source_name", ["game_base"]]
            },
        }
    )

    _compare(py_result, json_result)


# ── Test: eq predicate ─────────────────────────────────────────


@pytest.mark.skipif(
    not _HYPOTHESIS_AVAILABLE, reason="hypothesis not installed"
)
@given(rows=file_row_lists())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_eq_predicate(rows: list[FileRow]) -> None:
    """Python ``==`` matches JSON ``eq`` (exercises hash-index fast path)."""
    store = _make_store(rows)

    # Python API: linear scan equality.
    py_result = store.files.select(lambda r: r.is_active is True)

    # JSON DSL: eq triggers the select_by fast path.
    json_result = store.execute(
        {
            "select": ["*"],
            "from": "files",
            "where": {"eq": ["is_active", True]},
        }
    )

    _compare(py_result, json_result)


# ── Test: neq predicate ────────────────────────────────────────


@pytest.mark.skipif(
    not _HYPOTHESIS_AVAILABLE, reason="hypothesis not installed"
)
@given(rows=file_row_lists())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_neq_predicate(rows: list[FileRow]) -> None:
    """Python ``!=`` matches JSON ``neq``."""
    store = _make_store(rows)

    # Python API
    py_result = store.files.select(
        lambda r: r.is_redundant is not True
    )

    # JSON DSL
    json_result = store.execute(
        {
            "select": ["*"],
            "from": "files",
            "where": {"neq": ["is_redundant", True]},
        }
    )

    _compare(py_result, json_result)


# ── Test: gte / lte predicates ─────────────────────────────────


@pytest.mark.skipif(
    not _HYPOTHESIS_AVAILABLE, reason="hypothesis not installed"
)
@given(rows=file_row_lists())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_gte_lte_predicates(rows: list[FileRow]) -> None:
    """Python ``>=`` / ``<=`` matches JSON ``gte`` / ``lte``."""
    store = _make_store(rows)

    # Python API: compound with >= and <=.
    py_result = store.files.select(
        lambda r: r.priority >= 30 and r.file_size <= 500_000
    )

    # JSON DSL
    json_result = store.execute(
        {
            "select": ["*"],
            "from": "files",
            "where": {
                "and": [
                    {"gte": ["priority", 30]},
                    {"lte": ["file_size", 500_000]},
                ]
            },
        }
    )

    _compare(py_result, json_result)


# ── Test: not predicate ────────────────────────────────────────


@pytest.mark.skipif(
    not _HYPOTHESIS_AVAILABLE, reason="hypothesis not installed"
)
@given(rows=file_row_lists())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_not_predicate(rows: list[FileRow]) -> None:
    """Python ``not (expr)`` matches JSON ``not``."""
    store = _make_store(rows)

    # Python API: not (priority > 80).
    py_result = store.files.select(lambda r: not (r.priority > 80))

    # JSON DSL
    json_result = store.execute(
        {
            "select": ["*"],
            "from": "files",
            "where": {"not": {"gt": ["priority", 80]}},
        }
    )

    _compare(py_result, json_result)


# ── Test: multi-column project ─────────────────────────────────


@pytest.mark.skipif(
    not _HYPOTHESIS_AVAILABLE, reason="hypothesis not installed"
)
@given(rows=file_row_lists())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_multi_column_project(rows: list[FileRow]) -> None:
    """Project different column subsets — output schema must match."""
    store = _make_store(rows)
    cols = ("source_name", "virtual_path", "priority", "file_size")

    # Python API
    py_result = store.files.project(*cols)

    # JSON DSL
    json_result = store.execute(
        {
            "select": list(cols),
            "from": "files",
        }
    )

    _compare(py_result, json_result)


# ── Test: project on filtered, empty result ────────────────────


@pytest.mark.skipif(
    not _HYPOTHESIS_AVAILABLE, reason="hypothesis not installed"
)
@given(rows=file_row_lists())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_empty_with_projection(rows: list[FileRow]) -> None:
    """Empty filter result combined with projection — both empty with same columns."""
    store = _make_store(rows)

    # Python API.
    py_result = store.files.select(
        lambda r: r.priority < 0
    ).project("virtual_path", "source_name")

    # JSON DSL.
    json_result = store.execute(
        {
            "select": ["virtual_path", "source_name"],
            "from": "files",
            "where": {"lt": ["priority", 0]},
        }
    )

    _compare(py_result, json_result)
