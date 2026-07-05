"""MapConflictAnalyzer — 地图同名版本冲突检测。

传入一组 VPK（已安装 + 外部），提取其中的 .bsp，
对比所有来源的哈希和优先级，识别：
- 实际生效版本
- 被覆盖版本
- 孤立资源风险
"""

from __future__ import annotations

from collections import defaultdict

from parallelines.analysis.base import Analyzer
from parallelines.engine import Relation, ResultStore
from parallelines.engine.schema import HashConflictRow


class MapConflictAnalyzer(Analyzer):
    """检测多 VPK 间同名 .bsp 的版本冲突。

    Args:
        target_maps: 要分析的地图虚拟路径集合 (如 {"maps/c1m1.bsp"})
        external_sources: 外部 VPK 提供的地图 {virtual_path: source_name}
    """

    def __init__(
        self,
        target_maps: set[str] | None = None,
        external_sources: dict[str, str] | None = None,
    ):
        self.target_maps = target_maps
        self.external_sources = external_sources or {}

    def analyze(self, vfs, graph, store: ResultStore) -> None:
        """Detect map version conflicts across VPKs.

        Args:
            vfs: VirtualFileSystem instance.
            graph: DependencyGraph instance (unused by this analyzer).
            store: ResultStore to write results into.
        """
        if vfs is None:
            return

        # 1. 从 VFS 收集所有 .bsp 文件来源
        bsp_sources: dict[str, list[dict]] = defaultdict(list)
        for node in vfs.get_all_files():
            if not node.virtual_path.lower().endswith(".bsp"):
                continue
            bsp_sources[node.virtual_path].append(
                {
                    "source": node.source_name,
                    "priority": node.priority,
                    "enabled": node.is_enabled,
                    "hash": node.file_hash,
                    "type": "installed",
                }
            )

        # 2. 合并外部 VPK 的地图来源
        for vpath, src_name in self.external_sources.items():
            bsp_sources[vpath].append(
                {
                    "source": src_name,
                    "priority": -1,  # 默认低于已安装
                    "enabled": True,
                    "hash": None,
                    "type": "external",
                }
            )

        rows: list[HashConflictRow] = []
        for virtual_path, sources in bsp_sources.items():
            # 跳过不在目标集中的（除非未指定目标集）
            if self.target_maps and virtual_path not in self.target_maps:
                continue

            # 至少两个来源才构成冲突
            unique = {s["source"] for s in sources}
            if len(unique) < 2:
                continue

            # 哈希差异
            hashes = {s["hash"] for s in sources if s["hash"]}
            if len(hashes) <= 1:
                continue

            # 按优先级排序
            sorted_src = sorted(sources, key=lambda x: x["priority"], reverse=True)
            winner = sorted_src[0]
            for loser in sorted_src[1:]:
                rows.append(
                    HashConflictRow(
                        virtual_path=virtual_path,
                        winner_source=winner["source"],
                        loser_source=loser["source"],
                        winner_hash=str(winner["hash"] or ""),
                        loser_hash=str(loser["hash"] or ""),
                    )
                )

        if rows:
            if store.hash_conflicts is None:
                store.hash_conflicts = Relation.from_rows("hash_conflicts", rows)
            else:
                store.hash_conflicts.rows.extend(rows)
