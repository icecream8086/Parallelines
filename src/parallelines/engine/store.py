from __future__ import annotations

import dataclasses
from collections import defaultdict
from typing import Callable, Generic, Iterator, TypeVar

import networkx as nx

from parallelines.engine.schema import (
    AddonRow,
    CascadeOverrideRow,
    DepConflictRow,
    DependencyCycleRow,
    DependencyRow,
    EntryPointRow,
    FileRow,
    GlobalScriptRow,
    HashConflictRow,
    ImpactRow,
    ImplicitDepRow,
    IsolatedPackageRow,
    ModTypeRow,
)

T = TypeVar("T")


def _classify_entry_point(path: str) -> str:
    """Classify an entry point path into a source_type label."""
    if "manifest" in path.lower():
        return "manifest"
    if path.endswith(".bsp"):
        return "map"
    if path.endswith(".nut") or path.startswith("scripts/vscripts/"):
        return "script"
    if path in ("cfg/game.cfg", "cfg/autoexec.cfg", "gameinfo.txt"):
        return "script"
    return "user_specified"


class Relation(Generic[T]):
    """类型化关系表。内部是 list[T]，支持按列 hash index。"""

    def __init__(
        self,
        name: str,
        columns: tuple[str, ...],
        rows: list[T] | None = None,
        row_type: type | None = None,
    ):
        self.name = name
        self.columns = columns
        self.rows: list[T] = rows or []
        self._row_type: type | None = row_type
        self._index: dict[str, dict] = {}  # col_name -> {value: [row_indices]}

    @classmethod
    def from_rows(cls, name: str, rows: list[T]) -> "Relation[T]":
        """从行列表构造，自动推导 columns 为 T 的所有 dataclass 字段名。"""
        if not rows:
            return cls(name, ())
        row_type = type(rows[0])
        fields = [f.name for f in dataclasses.fields(rows[0])]  # type: ignore[arg-type]
        return cls(name, tuple(fields), rows, row_type=row_type)

    def build_index(self, *col_names: str) -> None:
        """为指定列建立 hash index。多次调用追加索引。"""
        for col in col_names:
            if col not in self.columns:
                raise KeyError(f"Column '{col}' not in {self.name}.columns")
            col_idx = self.columns.index(col)
            idx: dict = defaultdict(list)
            for i, row in enumerate(self.rows):
                val: object
                if isinstance(row, tuple):
                    val = row[col_idx]
                else:
                    val = getattr(row, col)
                idx[val].append(i)
            self._index[col] = dict(idx)

    def lookup(self, col: str, value) -> list[T]:
        """通过 hash index 等值查找（需先 build_index）。"""
        if col not in self._index:
            raise KeyError(
                f"Column '{col}' not indexed. Call build_index('{col}') first."
            )
        indices = self._index[col].get(value, [])
        return [self.rows[i] for i in indices]

    def update_cell(self, predicate: Callable[[T], bool], col: str, value) -> int:
        """对满足 predicate 的行，设置 col = value。返回修改行数。"""
        if col not in self.columns:
            raise KeyError(f"Column '{col}' not in {self.name}.columns")
        count = 0
        for row in self.rows:
            if predicate(row):
                setattr(row, col, value)
                count += 1
        return count

    def select(self, predicate: Callable[[T], bool]) -> "Relation[T]":
        """返回满足 predicate 的行的新 Relation。不修改原 Relation。"""
        selected = [r for r in self.rows if predicate(r)]
        return Relation(name=self.name, columns=self.columns, rows=selected)

    def select_by(self, col: str, value) -> "Relation[T]":
        """等值查询的索引优化路径。先建索引再查。"""
        self.build_index(col)
        matches = self.lookup(col, value)
        return Relation(
            name=f"{self.name}[{col}={value}]",
            columns=self.columns,
            rows=matches,
        )

    def project(self, *attrs: str) -> "Relation":
        """返回仅包含指定列的新 Relation。自动去重。结果行为 tuple。"""
        for a in attrs:
            if a not in self.columns:
                raise KeyError(f"Column '{a}' not in {self.name}.columns")
        indices = [self.columns.index(a) for a in attrs]
        seen: set = set()
        result_rows: list[tuple] = []
        for row in self.rows:
            vals: tuple
            if isinstance(row, tuple):
                vals = tuple(row[i] for i in indices)
            else:
                vals = tuple(getattr(row, a) for a in attrs)
            if vals not in seen:
                seen.add(vals)
                result_rows.append(vals)
        return Relation(name=self.name, columns=attrs, rows=result_rows)

    def join(self, other: "Relation", on: str) -> "Relation":
        """在公共列 *on* 上执行内连接。结果行为 tuple。"""
        if on not in self.columns or on not in other.columns:
            raise ValueError(f"Join column '{on}' not found in both relations")
        other.build_index(on)
        self_on_idx = self.columns.index(on)
        other_cols_without_on = tuple(c for c in other.columns if c != on)
        result_columns = self.columns + other_cols_without_on
        result_rows: list[tuple] = []
        for self_row in self.rows:
            self_val: object
            if isinstance(self_row, tuple):
                self_val = self_row[self_on_idx]
            else:
                self_val = getattr(self_row, on)
            matches = other.lookup(on, self_val)
            for other_row in matches:
                other_vals = tuple(
                    other_row[i]
                    if isinstance(other_row, tuple)
                    else getattr(other_row, c)
                    for i, c in enumerate(other.columns)
                    if c != on
                )
                if isinstance(self_row, tuple):
                    result_rows.append(self_row + other_vals)
                else:
                    self_vals = tuple(getattr(self_row, c) for c in self.columns)
                    result_rows.append(self_vals + other_vals)
        return Relation(
            name=f"{self.name}\N{BOWTIE}{other.name}",
            columns=result_columns,
            rows=result_rows,
        )

    def join_left(self, other: Relation, on: str) -> Relation:
        """左外连接。self 的所有行保留，other 无匹配时填充 None。"""
        if on not in self.columns or on not in other.columns:
            raise ValueError(f"Join column '{on}' not found in both relations")

        other.build_index(on)
        self_on_idx = self.columns.index(on)
        other_cols_without_on = tuple(c for c in other.columns if c != on)
        result_columns = self.columns + other_cols_without_on
        result_rows: list[tuple] = []
        null_other = tuple([None] * len(other_cols_without_on))

        for self_row in self.rows:
            self_val: object
            if isinstance(self_row, tuple):
                self_val = self_row[self_on_idx]
            else:
                self_val = getattr(self_row, on)

            # Guard: None keys never match SQL NULL semantics (no match ≠ NULL).
            matches = other.lookup(on, self_val) if self_val is not None else []

            if not matches:
                if isinstance(self_row, tuple):
                    result_rows.append(self_row + null_other)
                else:
                    self_vals = tuple(getattr(self_row, c) for c in self.columns)
                    result_rows.append(self_vals + null_other)
            else:
                for other_row in matches:
                    other_vals = tuple(
                        other_row[i]
                        if isinstance(other_row, tuple)
                        else getattr(other_row, c)
                        for i, c in enumerate(other.columns)
                        if c != on
                    )
                    if isinstance(self_row, tuple):
                        result_rows.append(self_row + other_vals)
                    else:
                        self_vals = tuple(getattr(self_row, c) for c in self.columns)
                        result_rows.append(self_vals + other_vals)

        return Relation(
            name=f"{self.name}⭤{other.name}",
            columns=result_columns,
            rows=result_rows,
        )

    def join_right(self, other: Relation, on: str) -> Relation:
        """右外连接。等价于 other.join_left(self, on)。"""
        return other.join_left(self, on)

    def join_full(self, other: Relation, on: str) -> Relation:
        """全外连接。left ∪ right，按行去重。"""
        if on not in self.columns or on not in other.columns:
            raise ValueError(f"Join column '{on}' not found in both relations")

        left = self.join_left(other, on)
        right = other.join_left(self, on)

        self_on_idx = self.columns.index(on)
        other_on_idx = other.columns.index(on)

        # Track on values that exist in self (None excluded — NULL != NULL)
        self_on_values: set = set()
        for row in self.rows:
            v = row[self_on_idx] if isinstance(row, tuple) else getattr(row, on)
            if v is not None:
                self_on_values.add(v)

        merged: list[tuple] = list(left.rows)

        for row in right.rows:
            on_val = row[other_on_idx] if isinstance(row, tuple) else getattr(row, on)
            if on_val not in self_on_values:
                # Unmatched other row — convert to left's column order
                if isinstance(row, tuple):
                    self_part: list = [None] * len(self.columns)
                    self_part[self_on_idx] = on_val
                    other_part = tuple(
                        row[i] for i, c in enumerate(other.columns) if c != on
                    )
                    merged.append(tuple(self_part) + other_part)
                else:
                    self_vals: list = [None] * len(self.columns)
                    self_vals[self_on_idx] = on_val
                    other_vals = tuple(
                        getattr(row, c) for c in other.columns if c != on
                    )
                    merged.append(tuple(self_vals) + other_vals)

        return Relation(
            name=f"{self.name}⟗{other.name}",
            columns=left.columns,
            rows=merged,
        )

    def group_by(self, key: str, agg: dict[str, Callable]) -> "Relation":
        """按 *key* 列分组，对每组应用聚合函数。结果行为 tuple。"""
        if key not in self.columns:
            raise KeyError(f"Group key '{key}' not in {self.name}.columns")
        key_idx = self.columns.index(key)
        groups: dict = {}
        for row in self.rows:
            k: object
            if isinstance(row, tuple):
                k = row[key_idx]
            else:
                k = getattr(row, key)
            groups.setdefault(k, []).append(row)
        result_columns = (key,) + tuple(agg.keys())
        result_rows = [
            (k,) + tuple(fn(group_rows) for fn in agg.values())
            for k, group_rows in groups.items()
        ]
        return Relation(
            name=f"{self.name}_grouped",
            columns=result_columns,
            rows=result_rows,
        )

    def __len__(self) -> int:
        return len(self.rows)

    def __iter__(self) -> Iterator[T]:
        return iter(self.rows)

    def to_rows(self) -> list[T]:
        """返回类型化行列表。"""
        return list(self.rows)

    def to_dicts(self) -> list[dict]:
        """转换为 dict 列表，键为 column 名。向后兼容现有报告生成器。"""
        return [
            {
                c: row[i] if isinstance(row, tuple) else getattr(row, c)
                for i, c in enumerate(self.columns)
            }
            for row in self.rows
        ]

    def to_dataframe(self):
        """转换为 pandas DataFrame。需要 pandas 已安装。"""
        import pandas as pd

        return pd.DataFrame(self.to_dicts(), columns=list(self.columns))


class ResultStore:
    """分析结果的唯一容器。"""

    def __init__(self):
        self.files: Relation[FileRow] | None = None
        self.dependencies: Relation[DependencyRow] | None = None
        self.addons: Relation[AddonRow] | None = None
        self.hash_conflicts: Relation[HashConflictRow] | None = None
        self.dep_conflicts: Relation[DepConflictRow] | None = None
        self.isolated: Relation[IsolatedPackageRow] | None = None
        self.impact: Relation[ImpactRow] | None = None
        self.entry_points: Relation[EntryPointRow] | None = None
        self.graph: nx.DiGraph | None = None
        self.dependency_cycles: Relation[DependencyCycleRow] | None = None
        self.cascade_overrides: Relation[CascadeOverrideRow] | None = None
        self.global_scripts: Relation[GlobalScriptRow] | None = None
        self.implicit_deps: Relation[ImplicitDepRow] | None = None
        self.mod_types: Relation[ModTypeRow] | None = None

    @classmethod
    def from_analysis(
        cls,
        vfs,
        graph,
        analyzers: list,
        entry_points: set[str] | None = None,
        addon_manifests: list | None = None,
    ) -> ResultStore:
        """Orchestrate the full analysis pipeline.

        Creates a ResultStore, populates it from the VFS, runs each analyzer,
        then runs each analyzer via ``analyzer.analyze(vfs, graph, store)``.

        Args:
            vfs: VirtualFileSystem instance (resolved active files).
            graph: DependencyGraph instance.
            analyzers: List of Analyzer instances to run.
            entry_points: Optional set of entry point virtual paths.
            addon_manifests: Optional list of AddonManifest objects.

        Returns:
            A populated ResultStore instance.
        """
        store = cls()

        # ── 1. Populate files from VFS ─────────────────────────────────
        if vfs is not None:
            file_rows: list[FileRow] = []
            for node in vfs.get_all_files():
                file_rows.append(
                    FileRow(
                        virtual_path=node.virtual_path,
                        source_name=node.source_name,
                        source_type=node.source_type,
                        priority=node.priority,
                        file_hash=node.file_hash or "",
                        file_size=node.file_size,
                        is_active=not node.is_redundant,
                        is_redundant=node.is_redundant,
                        is_enabled=node.is_enabled,
                        is_disabled_addon=getattr(node, "is_disabled_addon", False),
                    )
                )
            store.files = Relation[FileRow].from_rows("files", file_rows)

        # ── 2. Populate entry points ────────────────────────────────────
        if entry_points:
            store.entry_points = Relation[EntryPointRow].from_rows(
                "entry_points",
                [
                    EntryPointRow(virtual_path=p, source_type=_classify_entry_point(p))
                    for p in entry_points
                ],
            )

        # ── 3. Populate dependencies from graph edges ───────────────────
        if graph is not None:
            edge_rows: list[DependencyRow] = []
            for src, dst in graph.graph.edges():
                src_node = vfs.get_active_file(src) if vfs else None
                edge_rows.append(
                    DependencyRow(
                        from_path=src,
                        to_path=dst,
                        expected_source=src_node.source_name if src_node else "",
                    )
                )
            store.dependencies = Relation[DependencyRow].from_rows(
                "dependencies", edge_rows
            )

        # ── 4. Populate addon manifests ─────────────────────────────────
        if addon_manifests:
            store.addons = Relation[AddonRow].from_rows(
                "addons",
                [
                    AddonRow(a.addon_id, a.name, a.is_enabled, a.priority)
                    for a in addon_manifests
                ],
            )

        # ── 5. Store graph reference ────────────────────────────────────
        if graph is not None:
            store.graph = graph.graph if hasattr(graph, "graph") else graph

        # ── 6. Run analyzers ────────────────────────────────────────────
        for analyzer in analyzers:
            analyzer.analyze(vfs, graph, store)

        return store

    def descendants(self, path: str) -> Relation[FileRow]:
        """从图中计算传递闭包，返回可达文件的 FileRow 子集。"""
        if self.graph is None or self.files is None:
            return Relation[FileRow].from_rows("descendants", [])
        try:
            reachable = nx.descendants(self.graph, path)
        except nx.NetworkXError:
            return Relation[FileRow].from_rows("descendants", [])
        matched = [r for r in self.files.rows if r.virtual_path in reachable]
        return Relation[FileRow].from_rows("descendants", matched)

    def ancestors(self, path: str) -> Relation[FileRow]:
        """图中反向可达的 FileRow 子集。"""
        if self.graph is None or self.files is None:
            return Relation[FileRow].from_rows("ancestors", [])
        try:
            reachable = nx.ancestors(self.graph, path)
        except nx.NetworkXError:
            return Relation[FileRow].from_rows("ancestors", [])
        matched = [r for r in self.files.rows if r.virtual_path in reachable]
        return Relation[FileRow].from_rows("ancestors", matched)

    def to_dict(self) -> dict:
        """将所有关系序列化为 {relation_name: [dict, ...]} 用于 JSON 输出。"""
        result: dict = {}
        for attr in (
            "files",
            "dependencies",
            "addons",
            "hash_conflicts",
            "dep_conflicts",
            "isolated",
            "impact",
            "entry_points",
            "dependency_cycles",
            "cascade_overrides",
            "global_scripts",
            "implicit_deps",
            "mod_types",
        ):
            rel = getattr(self, attr, None)
            if rel is not None:
                result[attr] = [dataclasses.asdict(r) for r in rel.rows]
            else:
                result[attr] = []
        return result

    def execute(self, query_json: dict) -> Relation:
        """Parse and execute a JSON query against this store.

        Args:
            query_json: A JSON-compatible dict representing the query.

        Returns:
            A Relation with the query results.

        Raises:
            QueryParseError: If the query dict cannot be parsed.
            QueryValidationError: If the query fails schema validation.
        """
        from parallelines.engine.query_parser import QueryParser
        from parallelines.engine.query_validator import (
            QueryValidationError,
            QueryValidator,
        )
        from parallelines.engine.query_executor import QueryExecutor

        ast = QueryParser.parse(query_json)
        errors = QueryValidator.validate(ast, self)
        if errors:
            raise QueryValidationError(errors)
        return QueryExecutor.execute(ast, self)
