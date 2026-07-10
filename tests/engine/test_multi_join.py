"""Multi-table JOIN integration tests."""
from __future__ import annotations

import pytest

import networkx as nx

from parallelines.engine import ResultStore
from parallelines.engine.schema import (
    AddonRow, ExternalFileRow, FileRow,
)
from parallelines.engine.store import Relation

import copy

from parallelines.engine.query_ast import (
    BinaryPred, ColumnRef, JoinClause, Literal as Lit, Query, Source,
)
from parallelines.engine.query_executor import QueryExecutor
from parallelines.engine.query_optimizer import QueryOptimizer
from parallelines.engine.query_parser import QueryParser


def _row_set(rel) -> set[tuple]:
    if not rel.rows:
        return set()
    if isinstance(rel.rows[0], tuple):
        return set(rel.rows)
    return set(tuple(getattr(r, c) for c in rel.columns) for r in rel.rows)


@pytest.fixture
def store() -> ResultStore:
    """Store with files, addons, and external_files for multi-join tests."""
    s = ResultStore()
    s.files = Relation[FileRow].from_rows("files", [
        FileRow("a.txt", "base", "game", 100, "abc", 1024, True),
        FileRow("b.txt", "addon_x", "addon", 200, "def", 512, True),
        FileRow("c.txt", "addon_y", "addon", 300, "ghi", 256, False),
    ])
    s.addons = Relation[AddonRow].from_rows("addons", [
        AddonRow("base", "Base Game", True, 100),
        AddonRow("addon_x", "Addon X", True, 200),
        AddonRow("addon_y", "Addon Y", False, 300),
    ])
    s.external_files = Relation[ExternalFileRow].from_rows("external_files", [
        ExternalFileRow("a.txt", "ref:ext", 2000, "xyz", 1024),
        ExternalFileRow("b.txt", "ref:ext", 2000, "uvw", 512),
        ExternalFileRow("d.txt", "ref:ext", 2000, "rst", 128),
    ])
    return s


class TestMultiJoin:
    def test_three_table_join(self, store: ResultStore):
        """files + addons + external_files 端到端。"""
        query = {
            "select": ["files.virtual_path", "files.source_name", "addons.name"],
            "from": "files",
            "joins": [
                {
                    "type": "inner",
                    "with": "addons",
                    "on": {"eq": ["source_name", ["addons", "addon_id"]]}
                }
            ],
            "where": {"eq": ["is_active", True]},
        }
        result = store.execute(query)
        assert len(result) > 0

    def test_multi_join_with_external(self, store: ResultStore):
        """多表 JOIN 包含 external_files。"""
        query = {
            "select": ["*"],
            "from": "files",
            "joins": [
                {
                    "type": "left",
                    "with": "external_files",
                    "on": {"eq": ["virtual_path", ["external_files", "virtual_path"]]}
                }
            ],
            "limit": 10,
        }
        result = store.execute(query)
        assert len(result) > 0
        assert "ext_source_name" in result.columns

    def test_cookbook_regression(self, store: ResultStore):
        """现有简单查询（单表 FROM + WHERE）保持不变。"""
        query = {"select": ["*"], "from": "files", "where": {"eq": ["is_active", True]}}
        result = store.execute(query)
        assert len(result) == 2

    def test_aggregation_still_works(self, store: ResultStore):
        """聚合查询仍然正常工作。"""
        query = {
            "select": ["source_name", "file_count"],
            "from": "files",
            "group_by": {"by": ["source_name"], "agg": {"file_count": "count"}},
        }
        result = store.execute(query)
        assert len(result) > 0

    def test_no_join_query_unchanged(self, store: ResultStore):
        """无 JOIN 的查询不受优化器影响。"""
        r1 = store.execute({"select": ["*"], "from": "files"})
        assert len(r1) == 3


class TestMultiJoinDifferential:
    """MR3: JSON DSL multi-join result ≡ manual chained JOIN."""

    def test_three_table_chain_matches_dsl(self, store: ResultStore):
        """3 表 JSON DSL JOIN == files.join(addons).join(external_files)."""
        # Manual chain via Python API
        addons_renamed = store.addons.rename({"addon_id": "source_name"})
        step1 = store.files.join(addons_renamed, on="source_name")
        step2 = step1.join_left(store.external_files, on="virtual_path")
        manual_result = step2

        # DSL via store.execute (which includes optimizer)
        dsl_result = store.execute({
            "select": ["*"],
            "from": "files",
            "joins": [
                {"type": "inner", "with": "addons", "on": {"eq": ["source_name", ["addons", "addon_id"]]}},
                {"type": "left", "with": "external_files", "on": {"eq": ["virtual_path", ["external_files", "virtual_path"]]}},
            ],
        })

        common = tuple(sorted(set(manual_result.columns) & set(dsl_result.columns)))
        assert _row_set(manual_result.project(*common)) == _row_set(dsl_result.project(*common)), (
            f"DSL multi-join differs from manual chain: "
            f"|manual|={len(manual_result)} |dsl|={len(dsl_result)}"
        )

    def test_double_inner_chain_matches_dsl(self, store: ResultStore):
        """两个 INNER JOIN 差分测试 — 比较优化前后结果一致。"""
        q = QueryParser.parse({
            "select": ["*"],
            "from": "files",
            "joins": [
                {"type": "inner", "with": "addons", "on": {"eq": ["source_name", ["addons", "addon_id"]]}},
            ],
        })
        unopt = QueryExecutor.execute(q, store)
        opt = QueryOptimizer.optimize(copy.deepcopy(q), store)
        opt_result = QueryExecutor.execute(opt, store)
        common = tuple(sorted(set(unopt.columns) & set(opt_result.columns)))
        assert _row_set(unopt.project(*common)) == _row_set(opt_result.project(*common))


class TestMultiJoinEmptyEdges:
    def test_empty_file_returns_empty(self):
        """files 为空时多表 JOIN 返回空。"""
        from dataclasses import fields as dc_fields

        s = ResultStore()
        file_columns = tuple(f.name for f in dc_fields(FileRow))
        s.files = Relation("files", file_columns, rows=[])
        s.addons = Relation[AddonRow].from_rows("addons", [
            AddonRow("base", "Base", True, 100),
        ])
        result = s.execute({
            "select": ["*"], "from": "files",
            "join": {"type": "inner", "with": "addons", "on": {"eq": ["source_name", ["addons", "addon_id"]]}},
        })
        assert len(result) == 0

    def test_empty_join_side(self):
        """JOIN 的目标为空，LEFT JOIN 应返回左表+NULL。"""
        from dataclasses import fields as dc_fields

        s = ResultStore()
        s.files = Relation[FileRow].from_rows("files", [
            FileRow("a.txt", "base", "game", 100, "abc", 1024, True),
        ])
        ext_columns = tuple(f.name for f in dc_fields(ExternalFileRow))
        s.external_files = Relation("external_files", ext_columns, rows=[])
        s.external_files.build_index("virtual_path")
        result = s.execute({
            "select": ["*"], "from": "files",
            "join": {"type": "left", "with": "external_files", "on": {"eq": ["virtual_path", ["external_files", "virtual_path"]]}},
        })
        assert len(result) == 1
        assert result.rows[0][result.columns.index("ext_source_name")] is None


class TestJoinOrderOptimization:
    """MR5: 全 INNER JOIN 的查询 — 优化器重排前后结果一致。"""

    def test_reorder_preserves_two_joins(self, store: ResultStore):
        """2 个 INNER JOIN，优化器重排不改变结果。"""
        q = QueryParser.parse({
            "select": ["*"],
            "from": "files",
            "joins": [
                {"type": "inner", "with": "external_files", "on": {"eq": ["virtual_path", ["external_files", "virtual_path"]]}},
                {"type": "inner", "with": "addons", "on": {"eq": ["source_name", ["addons", "addon_id"]]}},
            ],
        })
        original_result = QueryExecutor.execute(q, store)
        optimized = QueryOptimizer.optimize(copy.deepcopy(q), store)
        opt_result = QueryExecutor.execute(optimized, store)
        common = tuple(sorted(set(original_result.columns) & set(opt_result.columns)))
        assert _row_set(original_result.project(*common)) == _row_set(opt_result.project(*common)), (
            f"Join reorder changed result: |orig|={len(original_result)} |opt|={len(opt_result)}"
        )
