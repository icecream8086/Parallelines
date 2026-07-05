"""DependencyConflictAnalyzer — detect when a file's dependency resolves to a
different source than expected."""

from __future__ import annotations

from parallelines.analysis.base import Analyzer
from parallelines.engine import Relation, ResultStore
from parallelines.engine.schema import DepConflictRow


class DependencyConflictAnalyzer(Analyzer):
    """Identifies missing or mismatched dependencies in the active VFS layer.

    Two kinds of problems are reported:

    * **Missing dependency** — a file declares a dependency whose virtual path
      does not exist in the active (resolved) file set.
    * **Source mismatch** — in the dependency graph, an edge connects two files
      whose active providers belong to different sources and the target has been
      overridden (is redundant from another provider's perspective).
    """

    def analyze(self, vfs, graph, store: ResultStore) -> None:
        """Check every active file's dependencies and graph edges for conflicts.

        Args:
            vfs: VirtualFileSystem instance.
            graph: DependencyGraph instance.
            store: ResultStore to write results into.
        """
        if vfs is None:
            return

        rows: list[DepConflictRow] = []
        for node in vfs.get_all_active():
            for dep_path in node.dependencies:
                provider = vfs.get_active_file(dep_path)
                if provider is None:
                    rows.append(
                        DepConflictRow(
                            from_path=node.virtual_path,
                            to_path=dep_path,
                            expected_source=node.source_name,
                            actual_source="MISSING",
                        )
                    )
                elif provider.source_name != node.source_name:
                    rows.append(
                        DepConflictRow(
                            from_path=node.virtual_path,
                            to_path=dep_path,
                            expected_source=node.source_name,
                            actual_source=provider.source_name,
                        )
                    )

        store.dep_conflicts = Relation.from_rows("dep_conflicts", rows)
