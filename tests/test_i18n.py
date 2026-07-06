"""Tests for parallelines.i18n — internationalization module."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from parallelines.i18n import _, detect_language, set_language


@pytest.fixture(autouse=True)
def _reset_language() -> None:
    """Reset language state before each test to avoid cross-test contamination."""
    from parallelines import i18n as _i18n

    with patch.object(_i18n, "_CURRENT", ""):
        yield


def test_set_language_zh() -> None:
    """Set language to 'zh' and verify Chinese translation."""
    set_language("zh")
    assert _("app.title") == "Parallelines -- Source 引擎 VPK 资源分析工具"
    assert _("report.ok") == "正常"
    assert _("cli.analyze") == "分析"


def test_set_language_en() -> None:
    """Set language to 'en' and verify English translation."""
    set_language("en")
    assert _("app.title") == "Parallelines -- Source Engine VPK Resource Analysis Tool"
    assert _("report.ok") == "OK"
    assert _("cli.analyze") == "Analyze"


def test_detect_language() -> None:
    """detect_language() returns a valid language code string."""
    lang = detect_language()
    assert isinstance(lang, str)
    assert lang in ("zh", "en")
