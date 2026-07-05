"""Detect global-scope scripts that may pollute all maps."""

from __future__ import annotations

from parallelines.analysis.base import Analyzer
from parallelines.engine import Relation, ResultStore
from parallelines.engine.schema import GlobalScriptRow


class GlobalScriptDetector(Analyzer):
    """List all .nut files in global vscript scope (outside maps/)."""

    def analyze(self, vfs, graph, store: ResultStore) -> None:
        if store.files is None:
            return
        rows = []
        for row in store.files.rows:
            if not row.virtual_path.endswith(".nut"):
                continue
            if "maps/" in row.virtual_path:
                continue
            rows.append(
                GlobalScriptRow(
                    virtual_path=row.virtual_path,
                    source_name=row.source_name,
                    source_type=row.source_type,
                )
            )
        if rows:
            store.global_scripts = Relation.from_rows("global_scripts", rows)
