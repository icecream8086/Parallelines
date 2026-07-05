"""IsolatedPackageAnalyzer — detect addons/packages where all files are dead."""

from __future__ import annotations

from collections import Counter, defaultdict

from parallelines.analysis.base import Analyzer
from parallelines.engine import Relation, ResultStore
from parallelines.engine.schema import IsolatedPackageRow


class IsolatedPackageAnalyzer(Analyzer):
    """Identifies sources (addons / VPKs) where every file is marked as dead.

    A package whose every file is dead contributes nothing to the final build
    and can likely be disabled or removed entirely.  This analyzer reports both
    fully-isolated packages and partially-dead ones so the user can decide
    whether to clean them up.
    """

    def analyze(self, vfs, graph, store: ResultStore) -> None:
        """Group all files by source and flag sources with 100 % dead files.

        Args:
            vfs: VirtualFileSystem instance.
            graph: DependencyGraph instance (unused by this analyzer).
            store: ResultStore to write results into.
        """
        if vfs is None:
            return

        total: Counter[str] = Counter()
        dead: Counter[str] = Counter()
        examples: dict[str, list[str]] = defaultdict(list)

        for node in vfs.get_all_files():
            total[node.source_name] += 1
            if node.is_dead or node.is_redundant:
                dead[node.source_name] += 1
                if len(examples[node.source_name]) < 3:
                    examples[node.source_name].append(node.virtual_path)

        rows: list[IsolatedPackageRow] = []
        for source_name in sorted(total):
            rows.append(
                IsolatedPackageRow(
                    source_name=source_name,
                    dead_file_count=dead[source_name],
                    example_paths=examples[source_name],
                )
            )

        store.isolated = Relation.from_rows("isolated", rows)
