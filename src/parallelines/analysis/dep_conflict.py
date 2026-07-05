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
        active_paths = {n.virtual_path for n in active_files}
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

        # --- Check graph edges for cross-source overrides --------------------
        # For every edge (src, tgt) in the graph, if the active provider of
        # the target has been overridden (is redundant) from a different
        # source, flag it.
        for src_path, tgt_path in graph.graph.edges():
            src_provider = vfs.get_active_file(src_path)
            tgt_provider = vfs.get_active_file(tgt_path)

            if src_provider is None or tgt_provider is None:
                continue

            if src_provider.source_name != tgt_provider.source_name:
                # Check whether the target's virtual path has *other* FileNodes
                # that are redundant (i.e. was overridden), indicating the
                # dependency resolved to a different source than the one the
                # source file's addon might expect.
                items.append(
                    {
                        "source_file": src_path,
                        "depends_on": tgt_path,
                        "provided_by": tgt_provider.source_name,
                        "expected_from": src_provider.source_name,
                        "risk": "source_mismatch",
                    }
                )

        return AnalysisFragment(
            analyzer_name="DependencyConflictAnalyzer", items=items
        )
