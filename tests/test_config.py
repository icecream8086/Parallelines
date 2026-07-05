"""Tests for parallelines.config — AppConfig defaults and TOML loading."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import NamedTemporaryFile

from parallelines.config import (
    AnalysisConfig,
    AppConfig,
    EntryPointsConfig,
    GeneralConfig,
    OutputConfig,
    load_config,
)


class TestConfig(unittest.TestCase):
    """Verify AppConfig defaults and TOML merge behaviour."""

    def test_default_config(self) -> None:
        """Default AppConfig should have expected default values."""
        config = AppConfig()

        # GeneralConfig defaults
        self.assertEqual(config.general.game, "")
        self.assertEqual(config.general.game_root, "")
        self.assertEqual(config.general.cache_dir, "./cache")
        self.assertTrue(config.general.enable_cache)
        self.assertEqual(config.general.cache_strategy, "mtime")
        self.assertEqual(config.general.num_workers, 0)
        self.assertEqual(config.general.memory_limit, "")
        self.assertFalse(config.general.nolimit)
        self.assertEqual(config.general.log_level, "INFO")

        # AnalysisConfig defaults
        self.assertTrue(config.analysis.detect_redundant)
        self.assertTrue(config.analysis.detect_dead)
        self.assertTrue(config.analysis.detect_dependency_conflicts)
        self.assertTrue(config.analysis.detect_isolated_packages)
        self.assertFalse(config.analysis.compute_impact)
        self.assertFalse(config.analysis.include_disabled_addons)

        # EntryPointsConfig defaults
        self.assertTrue(config.entry_points.auto_manifests)
        self.assertTrue(config.entry_points.all_maps_as_entries)
        self.assertEqual(config.entry_points.custom_entries, [])
        self.assertFalse(config.entry_points.use_pure_server_whitelist)
        self.assertEqual(config.entry_points.pure_server_whitelist_path, "")

        # OutputConfig defaults
        self.assertEqual(config.output.format, "json")
        self.assertEqual(config.output.output_dir, "./reports")
        self.assertTrue(config.output.include_dependency_chain)
        self.assertFalse(config.output.generate_graphviz)

    def test_load_config_not_found(self) -> None:
        """Loading a non-existent config file returns defaults."""
        config = load_config(Path("/nonexistent/path/config.toml"))
        self.assertIsInstance(config, AppConfig)
        self.assertEqual(config.general.game, "")
        self.assertEqual(config.general.log_level, "INFO")

    def test_merge_config(self) -> None:
        """Verify merging TOML data works correctly."""
        toml_data = {
            "general": {
                "game": "l4d2",
                "game_root": "C:/Program Files (x86)/Steam/steamapps/common/Left 4 Dead 2",
                "log_level": "DEBUG",
                "num_workers": 4,
            },
            "analysis": {
                "detect_redundant": False,
                "compute_impact": True,
            },
            "output": {
                "format": "csv",
            },
        }

        config = AppConfig()
        # Import and call the internal merge function directly
        from parallelines.config import _merge_config

        _merge_config(config, toml_data)

        self.assertEqual(config.general.game, "l4d2")
        self.assertEqual(
            config.general.game_root,
            "C:/Program Files (x86)/Steam/steamapps/common/Left 4 Dead 2",
        )
        self.assertEqual(config.general.log_level, "DEBUG")
        self.assertEqual(config.general.num_workers, 4)
        self.assertFalse(config.analysis.detect_redundant)
        self.assertTrue(config.analysis.compute_impact)
        self.assertEqual(config.output.format, "csv")
        # Unset fields should retain defaults
        self.assertEqual(config.general.cache_dir, "./cache")

    def test_merge_unknown_section_ignored(self) -> None:
        """Unknown sections in TOML data should be silently ignored."""
        from parallelines.config import _merge_config

        config = AppConfig()
        _merge_config(config, {"nonexistent_section": {"foo": "bar"}})
        # Defaults should remain untouched
        self.assertEqual(config.general.game, "")

    def test_merge_nondict_value_ignored(self) -> None:
        """Non-dict section values in TOML data should be silently skipped."""
        from parallelines.config import _merge_config

        config = AppConfig()
        # Section value is a string, not a dict — should be skipped
        _merge_config(config, {"general": "just a string"})
        self.assertEqual(config.general.game, "")

    def test_load_config_from_file(self) -> None:
        """Load a real TOML file and verify fields are populated."""
        toml_content = """
[general]
game = "tf2"
game_root = "/games/tf2"
log_level = "WARNING"
"""
        with NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False, encoding="utf-8"
        ) as f:
            f.write(toml_content)
            tmp_path = Path(f.name)

        try:
            config = load_config(tmp_path)
            self.assertEqual(config.general.game, "tf2")
            self.assertEqual(config.general.game_root, "/games/tf2")
            self.assertEqual(config.general.log_level, "WARNING")
        finally:
            tmp_path.unlink()


if __name__ == "__main__":
    unittest.main()
