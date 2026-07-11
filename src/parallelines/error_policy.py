"""Unified error handling strategies.

Every module that catches exceptions should use these helpers rather than
swallowing exceptions with a bare ``except Exception: pass`` — doing so
ensures users are at least warned when something goes wrong.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def parse_failure(exc: Exception, context: str = "") -> None:
    """Log a warning for a recoverable parse failure.

    Call this when a parser encounters data it cannot handle, but the
    overall analysis can continue.  The warning includes the parser name
    and the original exception message so users know what was skipped.
    """
    tag = f" in {context}" if context else ""
    logger.warning("Parse failure%s: %s", tag, exc)


def cache_write_failure(exc: Exception) -> None:
    """Log a warning for a cache write failure.

    Cache writes are non-critical — analysis results are already in memory.
    But users should know the disk cache was not updated, so the next run
    will rebuild from scratch.
    """
    logger.warning("Cache write failed (analysis results unaffected): %s", exc)


def analysis_failure(exc: Exception, analyzer: str) -> None:
    """Log a recoverable analyzer failure.

    The pipeline continues with the next analyzer — a single crash does
    not abort the analysis.
    """
    logger.error("%s failed: %s", analyzer, exc)
