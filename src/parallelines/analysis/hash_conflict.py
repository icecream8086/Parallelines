"""HashConflictAnalyzer — detect files with same virtual path but different content hashes."""

from __future__ import annotations

from collections import defaultdict

from parallelines.analysis.base import Analyzer
from parallelines.engine import Relation, ResultStore
from parallelines.engine.schema import HashConflictRow


def _is_engine_vpk(source_name: str) -> bool:
    """Check if a VPK name represents an engine/base game VPK."""
    lower = source_name.lower()
    stem = lower[:-4] if lower.endswith(".vpk") else lower
    return stem.endswith("_dir") or lower == "base"


class HashConflictAnalyzer(Analyzer):
    """Detects files that share a virtual_path across different sources but
    have different content hashes -- a sign of potential file conflicts.

    Formal definition:
        Conflict(f_i, f_j) ⟺ Path(f_i) = Path(f_j) ∧ Hash(f_i) ≠ Hash(f_j)
                             ∧ Enabled(f_i) ∧ Enabled(f_j)

    Results include a *severity* field that distinguishes genuine inter-addon
    conflicts (warning) from benign engine-file overrides (info).
    """

    def analyze(self, vfs, graph, store: ResultStore) -> None:
        """Group all FileNodes by virtual_path and flag cross-source hash mismatches.

        Args:
            vfs: VirtualFileSystem instance (may be None in testing contexts).
            graph: DependencyGraph instance (unused by this analyzer).
            store: ResultStore to write results into.
        """
        if vfs is None:
            return

        by_path: dict[str, list] = defaultdict(list)
        for node in vfs.get_all_files():
            by_path[node.virtual_path].append(node)

        rows: list[HashConflictRow] = []
        for virtual_path, nodes in by_path.items():
            sources = {(n.source_name, n.source_path) for n in nodes}
            if len(sources) < 2:
                continue

            enabled = [n for n in nodes if n.is_enabled and n.file_hash]
            hashes = {n.file_hash for n in enabled}
            if len(hashes) <= 1:
                continue

            sorted_nodes = sorted(enabled, key=lambda n: n.priority, reverse=True)
            winner = sorted_nodes[0]
            for loser in sorted_nodes[1:]:
                if loser.file_hash == winner.file_hash:
                    continue
                winner_is_engine = _is_engine_vpk(winner.source_name)
                loser_is_engine = _is_engine_vpk(loser.source_name)
                if winner_is_engine or loser_is_engine:
                    severity = "info"
                else:
                    severity = "warning"
                rows.append(
                    HashConflictRow(
                        virtual_path=virtual_path,
                        winner_source=winner.source_name,
                        loser_source=loser.source_name,
                        winner_hash=winner.file_hash or "",
                        loser_hash=loser.file_hash or "",
                        severity=severity,
                    )
                )

        if rows:
            if store.hash_conflicts is None:
                store.hash_conflicts = Relation.from_rows("hash_conflicts", rows)
            else:
                store.hash_conflicts.rows.extend(rows)
