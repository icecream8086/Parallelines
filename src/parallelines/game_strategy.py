"""Game-specific strategy configuration for Source Engine games.

Each Source 1 game can differ in VPK scanning patterns, priority semantics,
manifest paths, and entry-point discovery.  ``GameStrategy`` centralises these
differences so no game-specific hard-coding leaks into VFS or graph builders.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GameStrategy:
    """Source 1 游戏差异化配置。

    每个字段描述一项游戏间不同的行为。VfsBuilder / GraphBuilder /
    EntryPointDiscoverer 读取此配置决定具体逻辑。
    """
    game_id: str = ""

    # ── 文件系统 ───────────────────────────────────────────
    # gameinfo.txt SearchPaths 中需要额外扫描的目录 token
    # Source 1 通用: ["update"]  (对应 "Game update" 条目)
    extra_search_tokens: list[str] = field(default_factory=lambda: ["update"])

    # VPK 文件名模式 (用于 glob)
    vpk_glob: str = "*_dir.vpk"
    addon_vpk_glob: str = "*.vpk"

    # ── Addon 发现 ─────────────────────────────────────────
    # addonlist.txt 相对于 game_root 的路径
    addonlist_path: str = "addonlist.txt"

    # 是否扫描 addons/workshop/ 子目录
    scan_workshop: bool = True

    # addons/disable/ 目录名 (不同游戏可能有不同约定)
    disabled_addon_dir: str = "addons/disable"

    # ── 优先级方向 ─────────────────────────────────────────
    # Source 引擎使用 AddToHead 语义：后挂载的 VPK 被 prepend 到搜索路径最前端
    # 因此文件名排序靠后的 VPK 优先级最高。
    # priority_direction = "descending"  → 排序后从高到低分配
    # priority_direction = "ascending"   → 排序后从低到高分配 (当前错误行为)
    priority_direction: str = "descending"

    # ── 入口点 ─────────────────────────────────────────────
    # 引擎启动时自动加载的 manifest 列表
    auto_manifests: list[str] = field(default_factory=lambda: [
        "scripts/soundscapes_manifest.txt",
        "scripts/game_sounds_manifest.txt",
        "particles/particles_manifest.txt",
    ])

    # 额外的游戏特定 manifest (仅在匹配游戏时追加)
    extra_manifests: list[str] = field(default_factory=list)

    # 脚本/配置入口点
    script_entries: list[str] = field(default_factory=lambda: [
        "cfg/config.cfg",
        "cfg/autoexec.cfg",
    ])

    # ── 解析器选择 ─────────────────────────────────────────
    # 哪些扩展名需要提取依赖
    text_extensions: frozenset[str] = frozenset({".vmt", ".txt", ".nut", ".mdl", ".bsp"})

    # 音效 KeyValues 中提取 wave 引用的字段名列表
    sound_wave_fields: list[str] = field(default_factory=lambda: ["wave", "rndwave"])

    # ── 引擎入口点自动发现 ─────────────────────────────────
    # 入口点 BSP 数量上限 (0 表示全部)
    bsp_entry_limit: int = 0

    # 是否自动从 missions/*.txt 推导地图入口点
    derive_maps_from_missions: bool = True

    # ── source_type 标记名称 ──────────────────────────────
    # addon VPK 在 VFS 中的 source_type 标签
    addon_source_type: str = "addon"
    # 本体 VPK 的 source_type 标签
    game_source_type: str = "vpk"
    # 松散文件
    loose_source_type: str = "game"


# ── 预定义策略注册表 ─────────────────────────────────────


def get_strategy(game_id: str) -> GameStrategy:
    """根据 game_id 返回对应的 GameStrategy。

    未识别的 game_id 返回通用 Source 1 默认策略。
    """
    registry = _build_registry()
    key = game_id.lower().strip()
    if key in registry:
        return registry[key]
    # 回退到通用 Source 1 默认值
    return GameStrategy(game_id=key)


def _build_registry() -> dict[str, GameStrategy]:
    """构建所有已知游戏的策略注册表。"""
    l4d2 = GameStrategy(
        game_id="l4d2",
        extra_manifests=[
            "scripts/melee/melee_manifest.txt",
        ],
        script_entries=[
            "cfg/config.cfg",
            "cfg/autoexec.cfg",
        ],
        bsp_entry_limit=0,  # 全部 BSP 作为入口点
    )

    l4d1 = GameStrategy(
        game_id="l4d1",
        extra_manifests=["scripts/melee/melee_manifest.txt"],
        bsp_entry_limit=0,
    )

    tf2 = GameStrategy(
        game_id="tf2",
        extra_manifests=[
            "scripts/hudanimations_manifest.txt",
        ],
        bsp_entry_limit=0,
    )

    portal2 = GameStrategy(
        game_id="portal2",
        bsp_entry_limit=0,
    )

    csgo = GameStrategy(
        game_id="csgo",
        extra_manifests=[],
        bsp_entry_limit=0,
    )

    hl2 = GameStrategy(
        game_id="hl2",
        extra_manifests=[],
        bsp_entry_limit=0,
    )

    return {
        "l4d2": l4d2,
        "l4d1": l4d1,
        "tf2": tf2,
        "portal2": portal2,
        "portal": GameStrategy(game_id="portal", bsp_entry_limit=0),
        "csgo": csgo,
        "css": GameStrategy(game_id="css", bsp_entry_limit=0),
        "dods": GameStrategy(game_id="dods", bsp_entry_limit=0),
        "hl2": hl2,
        "hl2ep1": GameStrategy(game_id="hl2ep1", bsp_entry_limit=0),
        "hl2ep2": GameStrategy(game_id="hl2ep2", bsp_entry_limit=0),
    }
