"""Oracle-Free 对抗性测试 — §5.2 Environment Variables.

Metamorphic relations tested in this module:

    MR-E1  default_cache_dir() 在 frozen 模式下的 CWD 无关性
    MR-E2  _detect() 的幂等性
    MR-E3  LANG/LC_ALL 含 zh → detect_language() 返回 "zh"
    MR-E4  LOCALAPPDATA="" + APPDATA 有值时的降级行为

See ``devdocs/adversarial-path-env-testing.md`` for the full design.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

from parallelines.config import default_cache_dir
from parallelines.i18n import _detect, detect_language

_HAS_HYPOTHESIS = False
try:
    from hypothesis import given
    from hypothesis import strategies as st

    _HAS_HYPOTHESIS = True
except ImportError:
    pass


class TestDefaultCacheDir:
    """default_cache_dir() 的对抗测试。"""

    def test_frozen_mode_cwd_independence(self, monkeypatch):
        with mock.patch.object(sys, "frozen", True, create=True):
            with mock.patch.object(sys, "platform", "win32"):
                monkeypatch.setenv("LOCALAPPDATA", "C:\\Users\\test\\AppData\\Local")
                old_cwd = os.getcwd()
                try:
                    result1 = default_cache_dir()
                    os.chdir("C:\\")
                    result2 = default_cache_dir()
                    os.chdir("C:\\Windows\\System32")
                    result3 = default_cache_dir()
                    assert result1 == result2 == result3
                finally:
                    os.chdir(old_cwd)

    def test_windows_frozen_locallappdata_empty_appdata_set(self):
        with (
            mock.patch.object(sys, "frozen", True, create=True),
            mock.patch.object(sys, "platform", "win32"),
            mock.patch.dict(
                os.environ,
                {
                    "LOCALAPPDATA": "",
                    "APPDATA": "C:\\Users\\test\\AppData\\Roaming",
                },
                clear=False,
            ),
        ):
            result = default_cache_dir()
            expected = str(Path("C:/Users/test/AppData/Roaming") / "parallelines" / "cache")
            assert result == expected

    def test_windows_frozen_both_empty_falls_to_temp(self):
        with (
            mock.patch.object(sys, "frozen", True, create=True),
            mock.patch.object(sys, "platform", "win32"),
            mock.patch.dict(os.environ, {"LOCALAPPDATA": "", "APPDATA": ""}, clear=False),
        ):
            import tempfile

            result = default_cache_dir()
            expected = str(Path(tempfile.gettempdir()) / "parallelines" / "cache")
            assert result == expected

    @pytest.mark.skipif(not _HAS_HYPOTHESIS, reason="hypothesis not installed")
    @given(
        st.text(
            min_size=0,
            max_size=200,
            alphabet=st.characters(
                blacklist_categories=("Cs",),
                blacklist_characters="\x00",
            ),
        )
    )
    def test_default_cache_dir_never_returns_empty_string(self, env_value):
        with (
            mock.patch.object(sys, "frozen", True, create=True),
            mock.patch.object(sys, "platform", "win32"),
            mock.patch.dict(
                os.environ,
                {
                    "LOCALAPPDATA": env_value,
                    "APPDATA": "C:\\fallback",
                },
                clear=False,
            ),
        ):
            result = default_cache_dir()
            assert result != ""

    def test_cache_dir_with_trailing_space_in_env_var(self):
        """LOCALAPPDATA with trailing space: Path() preserves trailing spaces on Windows.

        This is a KNOWN behavior: default_cache_dir does not strip trailing spaces.
        Fix: strip() the env var value before using it.
        """
        with (
            mock.patch.object(sys, "frozen", True, create=True),
            mock.patch.object(sys, "platform", "win32"),
            mock.patch.dict(
                os.environ,
                {
                    "LOCALAPPDATA": "C:\\Users\\test\\AppData\\Local  ",
                },
                clear=False,
            ),
        ):
            result = default_cache_dir()
            trailing_spaces = "  "
            assert trailing_spaces not in result, (
                f"TRAILING SPACE: default_cache_dir retained trailing spaces: {result!r}"
            )


class TestLanguageDetection:
    """i18n language detection adversarial tests.

    §9.4 note: MR-E3 originally claimed a bug (H6) where _detect() would return "en"
    when locale.getlocale()=(None,None) and LANG=zh. This bug DOES NOT EXIST —
    the 3-layer fallback correctly returns "zh" via env var fallback.

    Tests below verify the code works correctly, not that it has a bug.
    """

    def test_detect_is_idempotent(self):
        """MR-E2: _detect() must return the same result on consecutive calls."""
        d1 = _detect()
        d2 = _detect()
        assert d1 == d2

    @pytest.mark.parametrize(
        "env_override",
        [
            {"LANG": "zh_CN.UTF-8"},
            {"LC_ALL": "zh_CN.UTF-8"},
            {"LANG": "zh_CN.GB2312"},
            {"LANG": "zh_TW.UTF-8"},
        ],
    )
    def test_zh_env_var_produces_zh_detection(self, env_override, monkeypatch):
        """MR-E3: LANG/LC_ALL starting with 'zh' -> detect_language() == 'zh'.

        This verifies the 3-layer fallback works correctly:
        1. locale.getlocale() -> (None, None)  (simulated)
        2. ctypes.windll.GetLocaleInfoW -> AttributeError on Linux (caught)
        3. os.environ.get("LANG") -> "zh_CN.UTF-8" -> returns "zh"
        """
        import locale as _locale

        def mock_getlocale(category=None):
            return (None, None)

        monkeypatch.setattr(_locale, "getlocale", mock_getlocale)
        for k, v in env_override.items():
            monkeypatch.setenv(k, v)

        import parallelines.i18n as mod

        monkeypatch.setattr(mod, "_CURRENT", "")
        result = detect_language()
        assert result == "zh", (
            f"3-layer fallback FAILED: env={env_override}, "
            f"locale.getlocale()=(None,None), "
            f"but detect_language()={result!r}"
        )

    def test_lang_c_not_mistaken_for_zh(self, monkeypatch):
        """LANG=C must return 'en', not 'zh'."""
        monkeypatch.setenv("LANG", "C")
        import parallelines.i18n as mod

        monkeypatch.setattr(mod, "_CURRENT", "")
        assert detect_language() == "en"

    def test_detect_fallback_chain_priority_over_env(self, monkeypatch):
        """Verify Layer 1 (locale.getlocale) takes priority over Layer 3 (env vars).

        When locale.getlocale() returns a zh locale, _detect() returns "zh"
        immediately at Layer 1, never reaching the env var check at Layer 3.
        This confirms the correct priority: Layer 1 > Layer 2 > Layer 3.
        """
        import locale as _locale

        # Layer 1 returns zh -> should NOT fall through to LANG=en
        def mock_getlocale_zh(category=None):
            return ("zh_CN", "UTF-8")

        monkeypatch.setattr(_locale, "getlocale", mock_getlocale_zh)
        monkeypatch.setenv("LANG", "en_US.UTF-8")

        import parallelines.i18n as mod

        monkeypatch.setattr(mod, "_CURRENT", "")
        assert detect_language() == "zh", (
            "BUG: locale.getlocale() returning zh should take priority over LANG=en"
        )


class TestNoContractsEnvVar:
    """PARALLELINES_NO_CONTRACTS env var controls contract enforcement in filesystem.py.

    The module-level flag _SHOULD_CHECK is set at import time:
        _SHOULD_CHECK = os.environ.get("PARALLELINES_NO_CONTRACTS", "").lower() \
            not in ("1", "true", "yes")
    """

    @pytest.mark.parametrize(
        "value,expect_check",
        [
            ("1", False),
            ("true", False),
            ("yes", False),
            ("TRUE", False),
            ("True", False),
            ("0", True),
            ("false", True),
            ("no", True),
            ("", True),  # empty  -> not in {"1","true","yes"} -> keep checks
            ("YES", False),  # .lower() -> "yes" -> in set -> disable
            ("disabled", True),  # NOT in set -> keep checks
            ("2", True),  # NOT in set -> keep checks
            (None, True),  # unset  -> default "" -> not in set -> keep checks
        ],
    )
    def test_no_contracts_parsing_logic(self, value, expect_check):
        """Verify the .lower() in ("1","true","yes") parsing logic.

        expect_check=True means contracts ARE enforced (no_contracts is NOT active).
        expect_check=False means contracts are DISABLED.
        """
        env_val = value if value is not None else ""
        parsed = env_val.lower() not in ("1", "true", "yes")
        assert parsed == expect_check, (
            f"PARALLELINES_NO_CONTRACTS={value!r}: "
            f"lower={env_val.lower()!r} not in ('1','true','yes') -> {parsed}, "
            f"expected {expect_check}"
        )

    def test_module_flag_reflects_env_var(self, monkeypatch):
        """The _SHOULD_CHECK module flag correctly reflects PARALLELINES_NO_CONTRACTS.

        This test verifies the REAL module-level behavior by reloading filesystem.py.
        """
        from parallelines.vfs import filesystem

        monkeypatch.setenv("PARALLELINES_NO_CONTRACTS", "true")
        importlib.reload(filesystem)
        assert filesystem._SHOULD_CHECK is False, (
            "PARALLELINES_NO_CONTRACTS=true should disable contract checks"
        )

        monkeypatch.delenv("PARALLELINES_NO_CONTRACTS", raising=False)
        importlib.reload(filesystem)
        assert filesystem._SHOULD_CHECK is True, (
            "PARALLELINES_NO_CONTRACTS unset should enable contract checks"
        )
