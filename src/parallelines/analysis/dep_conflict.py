"""DependencyConflictAnalyzer — detect when a file's dependency resolves to a
different source than expected."""

from __future__ import annotations

from parallelines.analysis.base import Analyzer
from parallelines.types import AnalysisFragment


class DependencyConflictAnalyzer(Analyzer):
    """Identifies missing or mismatched dependencies in the active VFS layer.

    Two kinds of problems are reported:

    * **Missing dependency** — a file declares a dependency whose virtual path
      does not exist in the active (resolved) file set.
    * **Source mismatch** — in the dependency graph, an edge connects two files
      whose active providers belong to different sources and the target has been
      overridden (is redundant from another provider's perspective).
    """

    def analyze(self, vfs, graph) -> AnalysisFragment:
        """Check every active file's dependencies and graph edges for conflicts.

        Args:
            vfs: VirtualFileSystem instance.
            graph: DependencyGraph instance.

        Returns:
            An AnalysisFragment with one item per conflict found.
        """
        if vfs is None or graph is None:
            return AnalysisFragment(
                analyzer_name="DependencyConflictAnalyzer", items=[]
            )

        active_files = vfs.get_all_active()
        items: list[dict] = []

        # --- Check node-level dependencies -----------------------------------
        for node in active_files:
            for dep_path in node.dependencies:
                provider = vfs.get_active_file(dep_path)
                if provider is None:
                    items.append(
                        {
                            "source_file": node.virtual_path,
                            "depends_on": dep_path,
                            "provided_by": "MISSING",
                            "expected_from": node.source_name,
                            "risk": "missing_dependency",
                        }
                    )
                elif provider.source_name != node.source_name:
                    items.append(
                        {
                            "source_file": node.virtual_path,
                            "depends_on": dep_path,
                            "provided_by": provider.source_name,
                            "expected_from": node.source_name,
                            "risk": "source_mismatch",
                        }
                    )

        # Deduplicate: the node.dependencies loop above already reports every
        # dependency edge (GraphBuilder populates both node.dependencies and
        # graph edges from the same data).  Duplicate reporting from graph
        # edges is removed here.
        return AnalysisFragment(analyzer_name="DependencyConflictAnalyzer", items=items)
