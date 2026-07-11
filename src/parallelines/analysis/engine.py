"""AnalyzerEngine — orchestrates all registered Analyzer instances.

Provides lifecycle hooks, error isolation, and configurable registration.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from parallelines.analysis.addon_dep import AddonDependencyAnalyzer
from parallelines.analysis.base import Analyzer
from parallelines.analysis.cascade_detector import CascadeDetector
from parallelines.analysis.cycle_detector import CycleDetector
from parallelines.analysis.dead_file import DeadFileAnalyzer
from parallelines.analysis.dep_conflict import DependencyConflictAnalyzer
from parallelines.analysis.global_script_detector import GlobalScriptDetector
from parallelines.analysis.hash_conflict import HashConflictAnalyzer
from parallelines.analysis.impact import ImpactAnalyzer
from parallelines.analysis.implicit_dep_detector import ImplicitDepDetector
from parallelines.analysis.isolated import IsolatedPackageAnalyzer
from parallelines.analysis.mod_classify import ModClassifier
from parallelines.analysis.redundancy import RedundancyAnalyzer
from parallelines.config import AnalysisConfig, AppConfig
from parallelines.engine import ResultStore
from parallelines.error_policy import analysis_failure

logger = logging.getLogger(__name__)


class AnalyzerEngine:
    """Orchestrates all registered Analyzer instances.

    Usage::

        engine = AnalyzerEngine.from_config(config, entry_points=eps, chain=ch)
        store = engine.run(vfs, graph, store)

    Features:
    - Dynamic registration via ``register()``
    - Lifecycle hooks ``on_before_analyze`` / ``on_after_analyze``
    - Error isolation — a single analyzer crash does not abort the pipeline
    - Configurable — built-in analyzers are enabled/disabled via config
    """

    def __init__(self, analyzers: list[Analyzer] | None = None) -> None:
        self.analyzers: list[Analyzer] = analyzers or []
        self._before_hooks: list[Callable[[str], None]] = []
        self._after_hooks: list[Callable[[str, bool], None]] = []

    # ── Factory ───────────────────────────────────────────────

    @classmethod
    def from_config(
        cls,
        config: AppConfig,
        *,
        entry_points: set[str] | None = None,
        chain: Any = None,
        base_paths: set[str] | None = None,
    ) -> AnalyzerEngine:
        """Create an AnalyzerEngine from config, auto-registering enabled analyzers."""
        engine = cls()
        ac: AnalysisConfig = config.analysis

        # Built-in analyzers, gated by config
        if ac.detect_redundant:
            engine.register(RedundancyAnalyzer())
        if ac.detect_dead:
            engine.register(DeadFileAnalyzer(entry_points=entry_points if entry_points else None))
        if ac.detect_hash_conflicts:
            engine.register(HashConflictAnalyzer())
        if ac.detect_dependency_conflicts:
            engine.register(DependencyConflictAnalyzer())
        if ac.detect_isolated_packages:
            engine.register(IsolatedPackageAnalyzer())
        if ac.compute_impact:
            engine.register(ImpactAnalyzer(top_n=20))
        engine.register(CycleDetector())
        engine.register(CascadeDetector())
        engine.register(GlobalScriptDetector())
        engine.register(ImplicitDepDetector())
        if base_paths is not None:
            engine.register(ModClassifier(base_paths=base_paths))
        if chain is not None:
            engine.register(AddonDependencyAnalyzer(chain=chain))

        return engine

    # ── Registration ──────────────────────────────────────────

    def register(self, analyzer: Analyzer) -> None:
        """Add a new analyzer to the pipeline."""
        self.analyzers.append(analyzer)

    # ── Lifecycle hooks ───────────────────────────────────────

    def on_before_analyze(self, hook: Callable[[str], None]) -> None:
        """Register a hook called before each analyzer with the analyzer name."""
        self._before_hooks.append(hook)

    def on_after_analyze(self, hook: Callable[[str, bool], None]) -> None:
        """Register a hook called after each analyzer with (name, success)."""
        self._after_hooks.append(hook)

    # ── Execution ─────────────────────────────────────────────

    def run(self, vfs, graph, store: ResultStore) -> ResultStore:
        """Execute all analyzers and collect results.

        Each analyzer runs in a try/except block so a single failure does not
        abort the pipeline.  Failures are logged so the user is aware, but all
        subsequent analyzers still execute.
        """
        for analyzer in self.analyzers:
            name = type(analyzer).__name__
            for hook in self._before_hooks:
                hook(name)
            try:
                analyzer.analyze(vfs, graph, store)
                success = True
            except Exception as exc:
                analysis_failure(exc, name)
                success = False
            finally:
                for hook in self._after_hooks:
                    hook(name, success)
        return store
