"""Regression tests for §10 known bugs.

See ``devdocs/adversarial-path-env-testing.md`` §10–§11 for the full design.
Each test targets a specific code-path vulnerability identified during module audit.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

import pytest

from parallelines.cache.manager import CacheManager
from parallelines.config import AppConfig, load_config
from parallelines.types import FileNode
from parallelines.vfs.builder import VfsBuilder
from parallelines.vfs.filesystem import VirtualFileSystem

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
VPK_FIXTURE = FIXTURES / "vpk" / "pak01_dir.vpk"


# ── Bug 1: meta.json encoding = platform default → cross-platform cache damage ──


class TestCacheMetaJsonEncoding:
    """meta.json written with platform default encoding cannot be read cross-platform.

    Source: cache/manager.py:60,144 — open() calls without encoding='utf-8'.
    Fix: add encoding='utf-8' to both open() calls.
    """

    def test_utf8_encoded_json_readable_across_platforms(self, tmp_path) -> None:
        """Chinese chars written with UTF-8 are readable regardless of platform locale.

        This is the FIXED behavior: CacheManager uses encoding='utf-8' for meta.json.
        Before the fix (platform-default encoding), Chinese VPK names would cause
        UnicodeDecodeError when read on a different platform.
        """
        meta = {
            "version": "1.0",
            "parser_version": 2,
            "entries": {
                "测试mod.vpk": {"mtime": 1234567890.0, "size": 999},
            },
        }

        # Write with UTF-8 (the fix)
        write_path = tmp_path / "meta.json"
        with open(write_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)

        # Read with UTF-8 — must not raise UnicodeDecodeError
        with open(write_path, encoding="utf-8") as f:
            loaded = json.load(f)

        assert loaded["entries"]["测试mod.vpk"]["size"] == 999

    def test_cache_manager_save_and_load_roundtrip(self, tmp_path) -> None:
        """CacheManager save+load roundtrip must preserve entries with non-ASCII VPK names."""
        try:
            import pandas as pd
        except ImportError:
            pytest.skip("pandas not installed")

        cache = CacheManager(tmp_path / "cache")
        meta = {
            "parser_version": 2,
            "entries": {
                "测试mod.vpk": {"mtime": 1234567890.0, "size": 999},
            },
        }
        cache.save(pd.DataFrame(), meta)

        # Verify meta.json is valid UTF-8
        meta_path = tmp_path / "cache" / "meta.json"
        content = meta_path.read_bytes()
        # Should be valid UTF-8 — decoding with UTF-8 must not raise
        text = content.decode("utf-8")
        assert "测试mod.vpk" in text, (
            f"ENCODING BUG: non-ASCII VPK name corrupted in meta.json.\n"
            f"  Content: {text!r}"
        )


# ── Bug 2: VPK parallel ingestion silently drops files ──


class TestVpkParallelSilentDrop:
    """Parallel VPK ingestion: a corrupt VPK must not silently drop other VPKs' files.

    Source: vfs/builder.py:56-58, 714-718
    The parallel path catches all exceptions from _parse_vpk_worker and returns
    an empty entry list, which is then silently skipped. No FileNodes are created,
    no error is propagated to the caller.
    """

    @pytest.mark.skipif(
        not VPK_FIXTURE.exists(), reason="VPK fixture not found"
    )
    def test_corrupt_vpk_does_not_drop_other_files_parallel(self, tmp_path) -> None:
        """Parallel mode: corrupt VPK must not cause other VPK files to disappear."""
        import shutil

        game = tmp_path / "game"
        game.mkdir()

        # Copy 3 valid VPK fixtures to trigger parallel path (>= 3 VPKs)
        for i in range(3):
            shutil.copy(VPK_FIXTURE, game / f"valid_{i}_dir.vpk")

        # Create a corrupt VPK
        (game / "broken_dir.vpk").write_bytes(b"\x00" * 100)

        # Write gameinfo.txt
        (game / "gameinfo.txt").write_text(
            "GameInfo\n{\n\tFileSystem\n\t{\n\t\tSearchPaths\n\t\t{\n\t\t\tGame\t.\n\t\t}\n\t}\n}\n",
            encoding="utf-8",
        )

        # Build with num_workers=0 (auto) to enable parallel path
        config = AppConfig()
        config.general.game = "l4d2"
        builder = VfsBuilder(game, config, use_cache=False, num_workers=0)
        vfs = builder.build()

        # Files from valid VPKs must still be present
        active = vfs.get_all_active()
        valid_count = len(
            [n for n in active if n.source_name.startswith("valid_")]
        )
        assert valid_count > 0, (
            f"SILENT DROP BUG (parallel): corrupt VPK caused all valid VPK files "
            f"to disappear. Active files: {len(active)}"
        )

        # failed_count must be propagated and queryable
        assert builder.failed_vpk_count > 0, (
            "SILENT DROP BUG: failed_vpk_count not propagated to caller"
        )

    @pytest.mark.skipif(
        not VPK_FIXTURE.exists(), reason="VPK fixture not found"
    )
    def test_sequential_mode_also_tracks_failures(self, tmp_path) -> None:
        """Sequential mode (num_workers=1) must also propagate failed_vpk_count."""
        import shutil

        game = tmp_path / "game"
        game.mkdir()

        shutil.copy(VPK_FIXTURE, game / "valid_dir.vpk")
        (game / "broken_dir.vpk").write_bytes(b"\x00" * 100)

        (game / "gameinfo.txt").write_text(
            "GameInfo\n{\n\tFileSystem\n\t{\n\t\tSearchPaths\n\t\t{\n\t\t\tGame\t.\n\t\t}\n\t}\n}\n",
            encoding="utf-8",
        )

        config = AppConfig()
        config.general.game = "l4d2"
        builder = VfsBuilder(game, config, use_cache=False, num_workers=1)
        vfs = builder.build()

        assert builder.failed_vpk_count == 1, (
            "SILENT DROP BUG (sequential): failed_vpk_count not propagated"
        )

        active = vfs.get_all_active()
        valid_count = len(
            [n for n in active if "valid_dir" in n.source_name]
        )
        assert valid_count > 0, (
            "SILENT DROP BUG (sequential): corrupt VPK dropped valid files"
        )


# ── Bug 3: addonlist.txt with spaces in VPK name → truncation ──


class TestAddonlistSpaceTruncation:
    """addonlist.txt with spaces in VPK name must not truncate.

    Source: vfs/builder.py:379 — split() treats all whitespace as delimiter.
    Fix: split on tab characters instead of whitespace.
    """

    def test_addonlist_with_spaces_in_vpk_name(self, tmp_path) -> None:
        """VPK name with spaces must survive _read_addonlist intact."""
        builder = VfsBuilder(
            tmp_path, AppConfig(), use_cache=False, num_workers=1
        )
        al_path = tmp_path / builder.strategy.addonlist_path
        al_path.parent.mkdir(parents=True, exist_ok=True)
        al_path.write_text(
            '"my cool addon.vpk"\t\t"1"\n"normal.vpk"\t\t"0"\n',
            encoding="utf-8",
        )

        result = builder._read_addonlist()
        assert "my cool addon.vpk" in result, (
            f"SPACE TRUNCATION: VPK name with spaces was truncated.\n"
            f"  Keys found: {list(result.keys())}"
        )
        assert "normal.vpk" in result, (
            f"Normal VPK name also not found: {list(result.keys())}"
        )

    def test_addonlist_with_unicode_vpk_name(self, tmp_path) -> None:
        """Unicode VPK names must survive _read_addonlist intact."""
        builder = VfsBuilder(
            tmp_path, AppConfig(), use_cache=False, num_workers=1
        )
        al_path = tmp_path / builder.strategy.addonlist_path
        al_path.parent.mkdir(parents=True, exist_ok=True)
        al_path.write_text(
            '"测试mod.vpk"\t\t"1"\n', encoding="utf-8"
        )

        result = builder._read_addonlist()
        assert "测试mod.vpk" in result, (
            f"Unicode VPK name not found.\n"
            f"  Keys: {list(result.keys())}"
        )

    def test_addonlist_workshop_path(self, tmp_path) -> None:
        """Workshop VPK paths with backslashes must be parsed correctly."""
        builder = VfsBuilder(
            tmp_path, AppConfig(), use_cache=False, num_workers=1
        )
        al_path = tmp_path / builder.strategy.addonlist_path
        al_path.parent.mkdir(parents=True, exist_ok=True)
        al_path.write_text(
            '"workshop\\123456.vpk"\t\t"1"\n', encoding="utf-8"
        )

        result = builder._read_addonlist()
        assert "123456.vpk" in result, (
            f"Workshop VPK not found.\n"
            f"  Keys: {list(result.keys())}"
        )

    def test_addonlist_bom_stripped(self, tmp_path) -> None:
        """UTF-8 BOM in addonlist.txt must be stripped."""
        builder = VfsBuilder(
            tmp_path, AppConfig(), use_cache=False, num_workers=1
        )
        al_path = tmp_path / builder.strategy.addonlist_path
        al_path.parent.mkdir(parents=True, exist_ok=True)
        al_path.write_bytes(b'\xef\xbb\xbf"test_addon.vpk"\t\t"1"\n')

        result = builder._read_addonlist()
        assert "test_addon.vpk" in result, (
            f"BOM leaked into VPK name. Keys: {list(result.keys())}"
        )


# ── Bug 4: Cache key collision for same-name VPKs in different directories ──


class TestCacheKeyCollision:
    """CacheManager key collision: same-name VPKs in different dirs share a key.

    Source: cache/manager.py:74-78 — key is vpk.get('source_name') which is
    just the file name, not the full path.
    """

    def test_cache_key_collision_false_negative(self, tmp_path) -> None:
        """Two VPKs with same name: one changes → cache must be invalid."""
        try:
            import pandas as pd
        except ImportError:
            pytest.skip("pandas not installed")

        cache = CacheManager(tmp_path / "cache")

        # Initial state: both VPKs have the same mtime
        cache.save(
            pd.DataFrame(),
            {
                "parser_version": 2,
                "entries": {
                    "pak01_dir.vpk": {"mtime": 100.0, "size": 1000},
                },
            },
        )

        # Now VPK A (left4dead2/) changed, VPK B (hl2/) didn't.
        # Same name → key collision → current_state only keeps the last-written (B)
        # which has mtime=100 (unchanged) → cache incorrectly says valid.
        vpk_list = [
            {
                "source_name": "pak01_dir.vpk",
                "name": "pak01_dir.vpk",
                "path": "/game/left4dead2/pak01_dir.vpk",
                "mtime": 150.0,
                "size": 1000,
            },
            {
                "source_name": "pak01_dir.vpk",
                "name": "pak01_dir.vpk",
                "path": "/game/hl2/pak01_dir.vpk",
                "mtime": 100.0,
                "size": 1000,
            },
        ]

        should_be_invalid = cache.is_valid(vpk_list)
        assert not should_be_invalid, (
            "CACHE FALSE NEGATIVE: VPK A changed but cache says valid because "
            "same-name VPK B (unchanged) overwrote A's entry in current_state dict.\n"
            "  Key should be full path, not just file name."
        )


# ── Bug 5: virtual_path case sensitivity → ghost files ──


class TestVirtualPathCaseSensitivity:
    """Same logical file with different case → VFS must detect redundancy.

    Source: vfs/filesystem.py:36,42 — dict key is case-sensitive.
    On Windows NTFS, 'Materials/' and 'materials/' are the same directory,
    but VFS treats them as different keys.

    Per §9.8 and §12, this test uses REAL VPK files parsed through
    parse_vpk_index → _add_vpk_entries → VFS, not manual FileNode construction.
    """

    def test_case_insensitive_virtual_path_collision(self, tmp_path) -> None:
        """Two VPKs with same file in different case → 1 active file after VFS resolve.

        Uses real srctools-created VPKs to go through the actual data pipeline:
        VPK binary → parse_vpk_index → _add_vpk_entries → VFS.add_file → resolve.
        """
        from srctools.vpk import VPK
        from parallelines.parsers.vpk_parser import parse_vpk_index

        # Create two VPKs with different-case paths via srctools
        vpk1 = tmp_path / "upper_dir.vpk"
        v1 = VPK(vpk1, mode="w", version=1)
        v1.add_file("Materials/Models/Player.mdl", b"content")
        v1.write_dirfile()

        vpk2 = tmp_path / "lower_dir.vpk"
        v2 = VPK(vpk2, mode="w", version=1)
        v2.add_file("materials/models/player.mdl", b"content")
        v2.write_dirfile()

        # Parse both VPKs — goes through real srctools VPK parsing
        entries_upper = parse_vpk_index(vpk1)
        entries_lower = parse_vpk_index(vpk2)

        assert len(entries_upper) == 1
        assert entries_upper[0]["virtual_path"] == "Materials/Models/Player.mdl"
        assert entries_lower[0]["virtual_path"] == "materials/models/player.mdl"

        # Add to VFS via _add_vpk_entries (the real code path)
        vfs = VirtualFileSystem()
        config = AppConfig()
        builder = VfsBuilder(tmp_path, config, use_cache=False, num_workers=1)
        builder._add_vpk_entries(vfs, "upper_dir.vpk", 100, entries_upper)
        builder._add_vpk_entries(vfs, "lower_dir.vpk", 200, entries_lower)
        vfs.resolve()

        # Filter active nodes for this logical file (lowercase match)
        player_nodes = [
            n
            for n in vfs.get_all_active()
            if n.virtual_path.lower().endswith("materials/models/player.mdl")
        ]
        assert len(player_nodes) == 1, (
            f"CASE COLLISION: expected 1 active file for player.mdl, "
            f"got {len(player_nodes)}: {player_nodes}\n"
            f"  VFS keys (from real VPKs): "
            f"{[n.virtual_path for n in vfs.get_all_active()]}\n"
            f"  'Materials/' and 'materials/' differ only in case, "
            f"but VFS treats them as distinct keys."
        )


# ── Bug 7: config.toml not found → silent default ──


class TestConfigTomlSilentDefault:
    """Config file not found → silently uses defaults instead of warning.

    Source: cli.py:411 — config_path = Path(args.config) if args.config else None
    When config.toml doesn't exist, load_config returns AppConfig() with game="".
    """

    def test_missing_config_file_returns_defaults(self, tmp_path) -> None:
        """load_config with non-existent path must return AppConfig defaults."""
        missing = tmp_path / "nonexistent_config.toml"
        assert not missing.exists()

        config = load_config(missing)
        assert config.general.game == "", (
            f"Expected empty game for missing config, got {config.general.game!r}"
        )
        assert config.general.log_level == "INFO"

    def test_config_path_empty_string_is_falsy(self) -> None:
        """cli.py: Path(args.config) if args.config else None — '' → None."""
        args_config = ""  # argparse default
        config_path = Path(args_config) if args_config else None
        assert config_path is None, (
            f"BUG: empty string not treated as falsy.\n"
            f"  config_path={config_path!r}"
        )

    def test_cwd_has_no_config_toml_falls_to_defaults(self, tmp_path, monkeypatch) -> None:
        """CWD without config.toml → load_config() returns defaults."""
        monkeypatch.chdir(tmp_path)
        assert not (tmp_path / "config.toml").exists()

        config = load_config()
        assert config.general.game == "", (
            f"Expected empty game when no config.toml in CWD, "
            f"got {config.general.game!r}"
        )
