"""Tests for parallelines.vfs.manifest_collector -- ManifestCollector."""

from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from parallelines.game_strategy import GameStrategy
from parallelines.vfs.manifest_collector import ManifestCollector


class TestManifestCollector(unittest.TestCase):
    """Unit tests for ManifestCollector, a pure discovery unit for VPK manifests."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.strategy = GameStrategy()
        self.collector = ManifestCollector(
            self.strategy, self.tmp, self._resolve
        )

    def tearDown(self) -> None:
        for child in sorted(self.tmp.rglob("*"), reverse=True):
            if child.is_file():
                child.chmod(stat.S_IWUSR)
                child.unlink()
            elif child.is_dir():
                try:
                    child.rmdir()
                except OSError:
                    pass
        try:
            self.tmp.rmdir()
        except OSError:
            pass

    def _resolve(self, path: str) -> Path | None:
        resolved = self.tmp / path
        return resolved if resolved.exists() else None

    def _touch(self, *parts: str) -> Path:
        p = self.tmp.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch()
        return p

    # -- Empty / absent directories ---------------------------------------

    def test_empty_search_paths(self) -> None:
        """Empty search paths yield an empty manifest."""
        result = self.collector.collect({}, [])
        self.assertEqual(result, [])

    def test_nonexistent_game_dir(self) -> None:
        """A search path that resolves to None is skipped."""
        search_paths = {"game": "nonexistent"}
        result = self.collector.collect(search_paths, [])
        self.assertEqual(result, [])

    def test_nonexistent_addon_root(self) -> None:
        """A non-existent addon root is silently skipped."""
        self._touch("game", "pak01_dir.vpk")
        search_paths = {"game": "game"}
        result = self.collector.collect(search_paths, ["nonexistent_addon"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "pak01_dir.vpk")

    # -- Game directory VPKs ----------------------------------------------

    def test_game_dir_vpks(self) -> None:
        """VPKs in a game directory appear in the manifest."""
        self._touch("game", "pak01_dir.vpk")
        self._touch("game", "pak02_dir.vpk")
        search_paths = {"game": "game"}
        result = self.collector.collect(search_paths, [])
        self.assertEqual(len(result), 2)
        names = {e["name"] for e in result}
        self.assertEqual(names, {"pak01_dir.vpk", "pak02_dir.vpk"})

    def test_game_dir_not_a_directory(self) -> None:
        """A game path that points to a file instead of a dir is skipped."""
        self._touch("not_a_dir.vpk")
        search_paths = {"game": "not_a_dir.vpk"}
        result = self.collector.collect(search_paths, [])
        self.assertEqual(result, [])

    def test_vpk_metadata(self) -> None:
        """Each manifest entry contains correct metadata fields."""
        vpk = self._touch("game", "pak01_dir.vpk")
        st = vpk.stat()
        search_paths = {"game": "game"}
        result = self.collector.collect(search_paths, [])
        self.assertEqual(len(result), 1)
        entry = result[0]
        self.assertEqual(entry["source_name"], "pak01_dir.vpk")
        self.assertEqual(entry["name"], "pak01_dir.vpk")
        self.assertEqual(entry["path"], str(vpk))
        self.assertEqual(entry["mtime"], st.st_mtime)
        self.assertEqual(entry["size"], st.st_size)

    def test_multiple_game_dirs(self) -> None:
        """VPKs across multiple game dirs are all collected."""
        self._touch("game1", "a_dir.vpk")
        self._touch("game2", "b_dir.vpk")
        search_paths = {"game": ["game1", "game2"]}
        result = self.collector.collect(search_paths, [])
        self.assertEqual(len(result), 2)

    # -- Addon directory VPKs ---------------------------------------------

    def test_addon_root_vpks(self) -> None:
        """VPKs in an addon root directory appear in the manifest."""
        self._touch("addons", "my_mod.vpk")
        result = self.collector.collect({}, ["addons"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "my_mod.vpk")

    def test_addon_root_filter_non_vpk(self) -> None:
        """Non-.vpk files in addon directories are excluded."""
        self._touch("addons", "readme.txt")
        self._touch("addons", "mod.vpk")
        result = self.collector.collect({}, ["addons"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "mod.vpk")

    def test_addon_root_case_insensitive_suffix(self) -> None:
        """Addon .VPK files with uppercase suffix are still included."""
        self._touch("addons", "MOD.VPK")
        result = self.collector.collect({}, ["addons"])
        self.assertEqual(len(result), 1)

    def test_default_addons_fallback(self) -> None:
        """When addon_roots is empty, falls back to scanning 'addons'."""
        self._touch("addons", "fallback.vpk")
        result = self.collector.collect({}, [])
        self.assertEqual(len(result), 1)

    # -- Workshop VPKs ----------------------------------------------------

    def test_workshop_vpks_included(self) -> None:
        """Workshop VPKs are collected when scan_workshop is True."""
        self._touch("addons", "workshop", "12345.vpk")
        result = self.collector.collect({}, ["addons"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "12345.vpk")

    def test_workshop_disabled(self) -> None:
        """Workshop VPKs are excluded when scan_workshop is False."""
        self.strategy.scan_workshop = False
        self._touch("addons", "workshop", "12345.vpk")
        result = self.collector.collect({}, ["addons"])
        self.assertEqual(len(result), 0)

    def test_workshop_non_vpk_filtered(self) -> None:
        """Non-.vpk files in workshop directory are excluded."""
        self._touch("addons", "workshop", "readme.txt")
        result = self.collector.collect({}, ["addons"])
        self.assertEqual(len(result), 0)

    # -- Deduplication ----------------------------------------------------

    def test_dedup_same_path_via_multiple_game_entries(self) -> None:
        """Same VPK found through multiple search path entries is listed once."""
        self._touch("game", "pak01_dir.vpk")
        search_paths = {"game": ["game"], "game_update": ["game"]}
        result = self.collector.collect(search_paths, [])
        self.assertEqual(len(result), 1)

    def test_different_paths_same_name_both_listed(self) -> None:
        """Same-named VPKs in different directories are both listed."""
        self._touch("game", "pak01_dir.vpk")
        self._touch("addons", "pak01_dir.vpk")
        search_paths = {"game": "game"}
        result = self.collector.collect(search_paths, ["addons"])
        self.assertEqual(len(result), 2)

    # -- Error handling ---------------------------------------------------

    def test_stat_failure_skipped(self) -> None:
        """A VPK that raises OSError on stat() is skipped."""
        vpk = self._touch("game", "broken.vpk")
        os.chmod(vpk, 0o000)  # remove all permissions
        try:
            search_paths = {"game": "game"}
            result = self.collector.collect(search_paths, [])
            self.assertEqual(len(result), 0)
        finally:
            os.chmod(vpk, stat.S_IWUSR | stat.S_IRUSR)

    # -- Strategy glob patterns -------------------------------------------

    def test_custom_vpk_glob_matches_nothing(self) -> None:
        """A custom glob that matches nothing yields no game VPKs."""
        self.strategy.vpk_glob = "nonexistent_*.vpk"
        self._touch("game", "pak01_dir.vpk")
        search_paths = {"game": "game"}
        result = self.collector.collect(search_paths, [])
        self.assertEqual(len(result), 0)

    def test_addonly_glob_used_for_addon(self) -> None:
        """Addon directories use addon_vpk_glob, not vpk_glob."""
        self.strategy.addon_vpk_glob = "custom_*.vpk"
        self._touch("addons", "custom_mod.vpk")
        self._touch("addons", "ignored.vpk")
        result = self.collector.collect({}, ["addons"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "custom_mod.vpk")


if __name__ == "__main__":
    unittest.main()
