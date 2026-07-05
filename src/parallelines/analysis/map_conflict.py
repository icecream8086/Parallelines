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
from parallelines.types import AnalysisFragment


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

    def analyze(self, vfs, graph) -> AnalysisFragment:
        if vfs is None:
            return AnalysisFragment(analyzer_name="MapConflictAnalyzer", items=[])

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

        items: list[dict] = []
        for virtual_path, sources in bsp_sources.items():
            # 跳过不在目标集中的（除非未指定目标集）
            if self.target_maps and virtual_path not in self.target_maps:
                continue

            # 至少两个来源才构成冲突
            unique = {s["source"] for s in sources}
            if len(unique) < 2:
                continue

            # 当前生效版本（VFS 中的活跃文件）
            active = vfs.get_active_file(virtual_path)
            active_source = active.source_name if active else "—"

            # 哈希差异
            hashes = {s["hash"] for s in sources if s["hash"]}
            hash_conflict = len(hashes) > 1

            # 按优先级排序
            sorted_src = sorted(sources, key=lambda x: x["priority"], reverse=True)

            items.append(
                {
                    "map": virtual_path,
                    "active_source": active_source,
                    "total_sources": len(unique),
                    "hash_conflict": "是" if hash_conflict else "否",
                    "sources": ", ".join(
                        f"{s['source']}(P{s['priority']})" for s in sorted_src
                    ),
                    "overridden": ", ".join(
                        s["source"] for s in sorted_src if s["source"] != active_source
                    )
                    or "—",
                }
            )

        return AnalysisFragment(analyzer_name="MapConflictAnalyzer", items=items)
