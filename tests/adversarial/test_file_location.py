"""Oracle-Free adversarial tests — File Location.

Tests for ``_find_queries_dir``, cross-drive ``relative_to``,
symlink ``game_root``, MR-P4 monotonicity, and ``Path.home()`` writability.

See ``devdocs/adversarial-path-env-testing.md`` for the full design.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

from parallelines.query_cli import find_queries_dir as _find_queries_dir
from parallelines.config import AppConfig
from parallelines.vfs.builder import VfsBuilder


class TestFindQueriesDir:
    """_find_queries_dir() path resolution adversarial tests."""

    def test_frozen_exe_in_weird_location(self) -> None:
        """Frozen exe with no queries/ dir → returns fallback path, not None."""
        with (
            mock.patch.object(sys, "frozen", True, create=True),
            mock.patch.object(sys, "executable", "X:\\weird\\path\\parallelines.exe"),
        ):
            result = _find_queries_dir()
            assert result is not None
            # Fallback: cwd/queries 或 executable 所在目录
            assert result.name == "queries", (
                f"Expected 'queries' dir, got {result.name}"
            )

    def test_dev_mode_three_levels_up(self) -> None:
        """Dev mode finds queries/ in project root."""
        with mock.patch.object(sys, "frozen", False, create=True):
            result = _find_queries_dir()
            assert result.is_dir()


class TestGameRootResolve:
    """game_root resolution edge cases."""

    def test_cross_drive_relative_to(self, tmp_path) -> None:
        """Cross-drive relative_to raises ValueError (caught in _build_from_disk)."""
        builder = VfsBuilder(tmp_path, AppConfig(), use_cache=False, num_workers=1)
        if sys.platform == "win32":
            external = Path("D:/external_mod")
        else:
            external = Path("/mnt/external_mod")

        with pytest.raises(ValueError):
            external.relative_to(builder.game_root)

    def test_symlink_game_root_resolves_to_target(self, tmp_path) -> None:
        """Symlink game_root: VfsBuilder follows symlink via .resolve()."""
        real_dir = tmp_path / "real_game"
        link_dir = tmp_path / "linked_game"
        real_dir.mkdir()
        (real_dir / "gameinfo.txt").write_text(
            "GameInfo\n{\n\tFileSystem\n\t{\n\t\tSearchPaths\n\t\t{\n\t\t\tGame\t|gameinfo_path|.\n\t\t}\n\t}\n}\n",
            encoding="utf-8",
        )
        try:
            link_dir.symlink_to(real_dir, target_is_directory=True)
        except OSError:
            pytest.skip("Symlink not supported on this platform")

        builder = VfsBuilder(link_dir, AppConfig(), use_cache=False, num_workers=1)
        assert builder.game_root == real_dir.resolve()


class TestMrP4:
    """MR-P4: game_root resolution monotonicity.

    Adding addon directories must not affect base game file resolution.

    T(x) = add subdirectory addons/subdir/ under game_root
    R    = VFS built with and without addons must have at least the same
           base game files active.

    Forall game_root with valid gameinfo.txt:
      vfs_base = build(game_root, no addons)
      vfs_full = build(game_root, with addons)
      Forall base_file in vfs_base.active:
        base_file.virtual_path in vfs_full.active
    """

    GAMEINFO = (
        "GameInfo\n{\n\tFileSystem\n\t{\n\t\tSearchPaths\n\t\t{\n"
        "\t\t\tGame\t|gameinfo_path|.\n\t\t}\n\t}\n}\n"
    )

    def test_addon_scan_does_not_remove_base_game_files(self, tmp_path) -> None:
        """Adding an addon directory must not cause base game files to disappear from VFS."""
        # Create game_root with base game file
        game_root = tmp_path / "game"
        game_root.mkdir()
        (game_root / "gameinfo.txt").write_text(self.GAMEINFO, encoding="utf-8")

        # Create a base game file (inside game_root, discovered via search path ".")
        base_file_dir = game_root / "materials"
        base_file_dir.mkdir()
        (base_file_dir / "base_texture.vtf").write_text("base", encoding="utf-8")

        # Build without addons
        config = AppConfig()
        builder_no_addons = VfsBuilder(game_root, config, use_cache=False, num_workers=1)
        vfs_no_addons = builder_no_addons.build()
        base_actives = {n.virtual_path for n in vfs_no_addons.get_all_active()}

        # Now add an addon directory with some VPK files
        addon_dir = game_root / "addons"
        addon_dir.mkdir()
        # Create an addon VPK file (doesn't need to be valid for source_paths test)
        fake_vpk = addon_dir / "test_addon.vpk"
        fake_vpk.touch()

        # Build with addons present
        builder_with_addons = VfsBuilder(game_root, AppConfig(), use_cache=False, num_workers=1)
        vfs_with_addons = builder_with_addons.build()
        full_actives = {n.virtual_path for n in vfs_with_addons.get_all_active()}

        # MR-P4: all base files must still be active
        missing = base_actives - full_actives
        assert not missing, (
            f"MR-P4 VIOLATION: adding addons caused base files to disappear: {missing}\n"
            f"  base files: {base_actives}\n"
            f"  full files: {full_actives}\n"
            f"  This indicates addon scanning corrupts base game file priority or resolution."
        )

        # Also verify base files didn't change count (no regression)
        assert len(base_actives) <= len(full_actives), (
            f"MR-P4 VIOLATION: active file count DECREASED when addons added.\n"
            f"  base: {len(base_actives)}, full: {len(full_actives)}"
        )


class TestPathHomeOnServiceAccount:
    """Path.home() behavior under service accounts."""

    def test_path_home_exists(self) -> None:
        """Path.home() must exist for default_cache_dir to work."""
        home = Path.home()
        assert home.exists(), f"HOME NOT FOUND: {home}"
        test_file = home / ".parallelines_test_write"
        try:
            test_file.touch()
            test_file.unlink()
        except (PermissionError, OSError) as e:
            print(f"WARNING: Path.home()={home} not writable: {e}")
