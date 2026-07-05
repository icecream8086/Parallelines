"""ModClassifier — identify each addon's mod type."""

from __future__ import annotations

from collections import defaultdict

from parallelines.analysis.base import Analyzer
from parallelines.engine import Relation, ResultStore
from parallelines.engine.schema import ModTypeRow


class ModClassifier(Analyzer):
    """Classify each addon by mod type and distinguish overlay vs truly orphaned."""

    def __init__(self, base_paths: set[str] | None = None):
        self.base_paths = base_paths or set()

    def analyze(self, vfs, graph, store: ResultStore) -> None:
        if store.files is None:
            return

        # Group files by source_name
        groups = defaultdict(list)
        for row in store.files.rows:
            groups[row.source_name].append(row)

        rows: list[ModTypeRow] = []
        for source_name, file_rows in groups.items():
            exts = {
                "." + r.virtual_path.rsplit(".", 1)[-1]
                for r in file_rows
                if "." in r.virtual_path
            }
            paths = {r.virtual_path for r in file_rows}
            total = len(file_rows)
            dead = sum(1 for r in file_rows if r.is_dead)
            redundant = sum(1 for r in file_rows if r.is_redundant)
            active = sum(1 for r in file_rows if r.is_active and not r.is_dead)
            is_disabled = any(r.is_disabled_addon for r in file_rows)

            mod_type = self._classify(exts, paths, total)
            if is_disabled:
                mod_type = "disabled"

            rows.append(
                ModTypeRow(
                    source_name,
                    mod_type,
                    total,
                    dead,
                    redundant,
                    active,
                    is_disabled,
                )
            )

        store.mod_types = Relation.from_rows("mod_types", rows)

    def _classify(self, exts: set[str], paths: set[str], total: int) -> str:
        if ".bsp" in exts:
            return "map"
        if ".nut" in exts:
            return "script"
        # Replacement mod: > 50% of files overlap with base game paths
        if self.base_paths:
            overlap = len(paths & self.base_paths)
            if overlap > total * 0.5:
                return "replacement"
        if total < 10:
            return "fragment"
        return "resource_pack"
