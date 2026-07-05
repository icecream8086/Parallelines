"""HashConflictAnalyzer — detect files with same virtual path but different content hashes.

Severity classification based on conflict type and source priority:

- **warning**: addon vs addon conflict (both priority < 100, hashes differ)
- **info**: engine/base file overridden by addon (normal mod behaviour)
- **silent**: multiple sources but all share the same hash (benign overlap)
"""

from __future__ import annotations

from collections import defaultdict

from parallelines.analysis.base import Analyzer
from parallelines.types import AnalysisFragment

# Source names that are considered "engine" rather than "addon".
# Game VPKs are typically named pakNN_dir.vpk; loose game files use "base".
_ENGINE_SOURCE_PREFIXES: set[str] = {"pak", "base"}


def _is_engine_source(source_name: str) -> bool:
    """Return True if *source_name* looks like an engine / base game source."""
    return any(source_name.lower().startswith(p) for p in _ENGINE_SOURCE_PREFIXES)


def _classify(nodes: list, hash_differ: bool) -> str:
    """Classify a cross-source path into warning / info / silent."""
    if not hash_differ:
        return "silent"

    # If the winning node is an engine source and there are addon files
    # behind it with a different hash, this is normal mod overriding → info.
    enabled = [n for n in nodes if n.is_enabled]
    if enabled:
        winner = max(enabled, key=lambda n: n.priority)
        if _is_engine_source(winner.source_name):
            return "info"

    return "warning"


class HashConflictAnalyzer(Analyzer):
    """Detects files that share a virtual_path across different sources but
    have different content hashes — a sign of potential file conflicts.

    Formal definition:
        Conflict(f_i, f_j) ⟺ Path(f_i) = Path(f_j) ∧ Hash(f_i) ≠ Hash(f_j)
                             ∧ Enabled(f_i) ∧ Enabled(f_j)

    Results include a *severity* field that distinguishes genuine inter-addon
    conflicts (warning) from benign engine-file overrides (info).
    """

    def analyze(self, vfs, graph) -> AnalysisFragment:
        """Group all FileNodes by virtual_path and flag cross-source hash mismatches.

        Args:
            vfs: VirtualFileSystem instance (may be None in testing contexts).
            graph: DependencyGraph instance (unused by this analyzer).

        Returns:
            An AnalysisFragment with one item per virtual_path that appears in
            multiple sources.
        """
        if vfs is None:
            return AnalysisFragment(analyzer_name="HashConflictAnalyzer", items=[])

        by_path: dict[str, list] = defaultdict(list)
        for node in vfs.get_all_files():
            by_path[node.virtual_path].append(node)

        items: list[dict] = []
        for virtual_path, nodes in by_path.items():
            sources = {n.source_name for n in nodes}
            if len(sources) < 2:
                continue

            enabled_hashes = {
                n.file_hash for n in nodes if n.is_enabled and n.file_hash is not None
            }
            hash_differ = len(enabled_hashes) > 1

            active = vfs.get_active_file(virtual_path)
            active_source = active.source_name if active else None
            severity = _classify(nodes, hash_differ)

            if hash_differ:
                analysis_text = "同路径文件来自不同来源且哈希不一致，存在冲突风险"
            else:
                analysis_text = "同路径文件来自不同来源但哈希一致，无冲突"

            items.append(
                {
                    "virtual_path": virtual_path,
                    "sources": ",".join(sorted(sources)),
                    "hash_differ": hash_differ,
                    "active_source": active_source,
                    "severity": severity,
                    "analysis": analysis_text,
                }
            )

        return AnalysisFragment(analyzer_name="HashConflictAnalyzer", items=items)
