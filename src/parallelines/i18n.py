"""Internationalization — single-file module, auto-detects OS language.

Usage:
    from parallelines.i18n import _, set_language, detect_language

    set_language("zh")          # manual override
    print(_("app.title"))       # → "Parallelines -- Source 引擎 VPK 资源分析工具"
    print(_("report.ok"))       # → "正常"
"""

from __future__ import annotations

import locale
import logging
import os

logger = logging.getLogger(__name__)

ZH: dict[str, str] = {
    "app.title": "Parallelines -- Source 引擎 VPK 资源分析工具",
    "app.quit": "退出",
    "cli.analyze": "分析",
    "cli.external": "外部 VPK 分析",
    "cli.game_required": "请指定游戏 (--game)",
    "cli.game_root_required": "请指定游戏根目录 (--game-root)",
    "analyzer.redundancy": "冗余文件",
    "analyzer.dead_file": "死文件",
    "analyzer.hash_conflict": "哈希冲突",
    "analyzer.dep_conflict": "依赖冲突",
    "analyzer.isolated": "孤立包",
    "analyzer.impact": "影响面",
    "vfs.building": "正在构建虚拟文件系统...",
    "vfs.ready": "VFS 就绪: {active} 个活跃文件",
    "vfs.cache_hit": "从 SSD 缓存加载 VFS",
    "graph.building": "正在构建依赖图...",
    "graph.preread": "正在预读文件...",
    "graph.parsing": "正在并行解析...",
    "graph.mdlbsp": "正在串行提取模型/地图依赖...",
    "graph.ready": "图就绪: {nodes} 节点, {edges} 条边",
    "report.saved": "报告已保存到 {path}",
    "report.summary": "分析摘要",
    "report.title": "Parallelines 分析报告",
    "report.analyzer": "分析器",
    "report.issues": "问题",
    "report.status": "状态",
    "report.ok": "正常",
    "report.found": "发现 {count} 个",
    "external.analyzing": "正在分析外部 VPK: {name}",
    "external.override": "将会覆盖",
    "external.overridden": "将会被覆盖",
    "external.new_files": "新文件",
    "error.interrupted": "用户中断 (Ctrl+C)",
    "error.unexpected": "意外错误: {msg}",
    "lang.current": "当前语言: {lang}",
    "lang.switch": "切换语言",
    "pipeline.cold_boot.title": "冷启动模式 -- 需要读取所有 VPK 文件内容",
    "pipeline.cold_boot.no_cache": "--no-cache 已指定，将跳过 SSD 缓存重建依赖图。",
    "pipeline.cold_boot.first_run": "这是首次运行（或缓存已失效），需要解析 VPK 文件。",
    "pipeline.cold_boot.eta": "预计耗时：2–3 分钟，期间磁盘 I/O 会很高。",
    "pipeline.cold_boot.hint": "如果已有缓存，去掉 --no-cache 即可秒级启动。",
    "pipeline.cold_boot.confirm": "确认继续？[y/N] ",
    "pipeline.cold_boot.cancelled": "已取消。",
    "pipeline.cold_boot.skip_hint": "使用 --yes 跳过此提示。",
}

EN: dict[str, str] = {
    "app.title": "Parallelines -- Source Engine VPK Resource Analysis Tool",
    "app.quit": "Quit",
    "cli.analyze": "Analyze",
    "cli.external": "External VPK Analysis",
    "cli.game_required": "Please specify a game (--game)",
    "cli.game_root_required": "Please specify the game root directory (--game-root)",
    "analyzer.redundancy": "Redundant Files",
    "analyzer.dead_file": "Dead Files",
    "analyzer.hash_conflict": "Hash Conflicts",
    "analyzer.dep_conflict": "Dependency Conflicts",
    "analyzer.isolated": "Isolated Packages",
    "analyzer.impact": "Impact Scope",
    "vfs.building": "Building virtual file system...",
    "vfs.ready": "VFS ready: {active} active files",
    "vfs.cache_hit": "Loaded VFS from SSD cache",
    "graph.building": "Building dependency graph...",
    "graph.preread": "Pre-reading files...",
    "graph.parsing": "Parsing in parallel...",
    "graph.mdlbsp": "Extracting model/map deps...",
    "graph.ready": "Graph ready: {nodes} nodes, {edges} edges",
    "report.saved": "Report saved to {path}",
    "report.summary": "Analysis Summary",
    "report.title": "Parallelines Analysis Report",
    "report.analyzer": "Analyzer",
    "report.issues": "Issues",
    "report.status": "Status",
    "report.ok": "OK",
    "report.found": "Found {count}",
    "external.analyzing": "Analyzing external VPK: {name}",
    "external.override": "Will Override",
    "external.overridden": "Will Be Overridden",
    "external.new_files": "New Files",
    "error.interrupted": "Interrupted by user (Ctrl+C)",
    "error.unexpected": "Unexpected error: {msg}",
    "lang.current": "Current language: {lang}",
    "lang.switch": "Switch Language",
    "pipeline.cold_boot.title": "Cold boot mode — needs to read all VPK files",
    "pipeline.cold_boot.no_cache": "--no-cache specified, will skip SSD cache and rebuild dependency graph.",
    "pipeline.cold_boot.first_run": "First run (or cache invalidated), need to parse VPK files.",
    "pipeline.cold_boot.eta": "Estimated time: 2–3 minutes, disk I/O will be heavy.",
    "pipeline.cold_boot.hint": "If a cache exists, drop --no-cache for near-instant startup.",
    "pipeline.cold_boot.confirm": "Continue? [y/N] ",
    "pipeline.cold_boot.cancelled": "Cancelled.",
    "pipeline.cold_boot.skip_hint": "Use --yes to skip this prompt.",
}

_TRANSLATIONS: dict[str, dict[str, str]] = {"zh": ZH, "en": EN}
_CURRENT: str = ""


def _detect() -> str:
    # Try locale module first (preferred, works when locale is properly set).
    try:
        loc = locale.getlocale()
        if loc and loc[0]:
            code = loc[0].replace("_", "").lower()
            if code.startswith("zh"):
                return "zh"
    except Exception:
        pass
    # Fallback to LCID / OS language query (works in frozen PyInstaller exe
    # where locale module may return (None, None)).
    try:
        import ctypes
        windll = ctypes.windll.kernel32
        # LOCALE_SISO639LANGNAME (0x59) -> "zh", "en", etc.
        buf = ctypes.create_unicode_buffer(32)
        if windll.GetLocaleInfoW(0x400, 0x59, buf, 32):  # 0x400 = LOCALE_USER_DEFAULT
            lang = buf.value.strip().lower()
            if lang.startswith("zh"):
                return "zh"
    except Exception:
        pass
    # Last resort: check common Windows environment variables.
    try:
        for var in ("LANG", "LC_ALL"):
            val = os.environ.get(var, "")
            if val.lower().startswith("zh"):
                return "zh"
    except Exception:
        pass
    return "en"


def detect_language() -> str:
    """Return current language code: ``'zh'`` or ``'en'``."""
    return _CURRENT or _detect()


def set_language(lang: str) -> None:
    """Set language manually, e.g. ``set_language('en')``."""
    global _CURRENT
    if lang in _TRANSLATIONS:
        _CURRENT = lang
    else:
        logger.warning("unsupported language: %s, falling back to en", lang)
        _CURRENT = "en"


def _(key: str) -> str:
    """Translate *key* for the current language.

    Returns *key* itself when no translation is found (safe fallback).
    """
    lang = _CURRENT or _detect()
    return _TRANSLATIONS.get(lang, {}).get(key, key)
