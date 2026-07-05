"""Internationalization — single-file module, auto-detects OS language.

Usage:
    from parallelines.i18n import _, set_language, detect_language

    set_language("zh")          # manual override
    print(_("app.title"))       # → "Parallelines — Source 引擎 VPK 资源分析工具"
    print(_("report.ok"))       # → "正常"
"""

from __future__ import annotations

import locale
import logging

logger = logging.getLogger(__name__)

ZH: dict[str, str] = {
    "app.title": "Parallelines — Source 引擎 VPK 资源分析工具",
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
    "graph.ready": "图就绪: {nodes} 节点, {edges} 条边",
    "report.saved": "报告已保存到 {path}",
    "report.summary": "分析摘要",
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
    "tui.dashboard": "仪表盘",
    "tui.analysis": "分析",
    "tui.report": "报告",
    "tui.settings": "设置",
    "tui.load_report": "加载报告",
    "tui.run_analysis": "运行分析",
    "lang.current": "当前语言: {lang}",
    "lang.switch": "切换语言",
}

EN: dict[str, str] = {
    "app.title": "Parallelines — Source Engine VPK Resource Analysis Tool",
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
    "graph.ready": "Graph ready: {nodes} nodes, {edges} edges",
    "report.saved": "Report saved to {path}",
    "report.summary": "Analysis Summary",
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
    "tui.dashboard": "Dashboard",
    "tui.analysis": "Analysis",
    "tui.report": "Report",
    "tui.settings": "Settings",
    "tui.load_report": "Load Report",
    "tui.run_analysis": "Run Analysis",
    "lang.current": "Current language: {lang}",
    "lang.switch": "Switch Language",
}

_TRANSLATIONS: dict[str, dict[str, str]] = {"zh": ZH, "en": EN}
_CURRENT: str = ""


def _detect() -> str:
    try:
        code, _ = locale.getdefaultlocale()
        if code and code.startswith("zh"):
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
