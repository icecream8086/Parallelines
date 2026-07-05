"""Detect implicit cross-addon dependencies."""

from __future__ import annotations

from parallelines.analysis.base import Analyzer
from parallelines.engine import Relation, ResultStore
from parallelines.engine.schema import ImplicitDepRow


class ImplicitDepDetector(Analyzer):
    """Find files where addon A depends on addon B's files."""

    def analyze(self, vfs, graph, store: ResultStore) -> None:
        if store.graph is None or store.files is None:
            return
        # Build path -> source_name map
        path_to_source = {}
        for row in store.files.rows:
            path_to_source[row.virtual_path] = row.source_name

        rows = []
        for src, dst in store.graph.edges():
            src_source = path_to_source.get(src)
            dst_source = path_to_source.get(dst)
            if (
                src_source is not None
                and dst_source is not None
                and src_source != dst_source
            ):
                rows.append(
                    ImplicitDepRow(
                        dependent_addon=src_source,
                        provider_addon=dst_source,
                        virtual_path=dst,
                    )
                )

        # Deduplicate
        seen = set()
        unique_rows = []
        for r in rows:
            key = (r.dependent_addon, r.provider_addon, r.virtual_path)
            if key not in seen:
                seen.add(key)
                unique_rows.append(r)

        if unique_rows:
            store.implicit_deps = Relation.from_rows("implicit_deps", unique_rows)
