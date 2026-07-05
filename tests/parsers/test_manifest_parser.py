"""Tests for parallelines.parsers.manifest_parser — manifest file parsing."""

from __future__ import annotations

import unittest
from pathlib import Path

from parallelines.exceptions import ParseError
from parallelines.parsers.manifest_parser import is_manifest_path, parse_manifest

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


class TestManifestParser(unittest.TestCase):
    """Verify manifest parsing and manifest-path detection."""

    def test_parse_manifest(self) -> None:
        """Parse sample_manifest.txt and verify results."""
        manifest_path = FIXTURES / "sample_manifest.txt"
        entries = parse_manifest(manifest_path)
        self.assertIn("maps/c1m1_hotel.bsp", entries)
        self.assertIn("maps/c1m2_streets.bsp", entries)
        self.assertIn("scripts/example.nut", entries)
        self.assertEqual(len(entries), 3)

    def test_is_manifest_path_positive(self) -> None:
        """Paths containing 'manifest' and ending with .txt should be detected."""
        self.assertTrue(is_manifest_path("soundscapes_manifest.txt"))
        self.assertTrue(is_manifest_path("particles_manifest.txt"))
        self.assertTrue(is_manifest_path("maps/game_manifest.txt"))

    def test_is_manifest_path_negative(self) -> None:
        """Paths without 'manifest' or not ending in .txt should return False."""
        self.assertFalse(is_manifest_path("soundscapes.txt"))
        self.assertFalse(is_manifest_path("manifest.json"))
        self.assertFalse(is_manifest_path("readme.md"))

    def test_is_manifest_path_case_insensitive(self) -> None:
        """Detection should be case-insensitive."""
        self.assertTrue(is_manifest_path("SOUNDSCAPES_MANIFEST.TXT"))
        self.assertTrue(is_manifest_path("Particles_Manifest.txt"))

    def test_empty_lines_skipped(self) -> None:
        """Empty lines in manifest content should be filtered out."""
        manifest_content = (
            "maps/c1m1_hotel.bsp\n"
            "\n"
            "maps/c1m2_streets.bsp\n"
            "   \n"
            "scripts/example.nut\n"
        )
        path = FIXTURES / "_test_empty_lines_temp.txt"
        try:
            path.write_text(manifest_content, encoding="utf-8")
            entries = parse_manifest(path)
            self.assertEqual(len(entries), 3)
        finally:
            if path.exists():
                path.unlink()

    def test_comment_lines_skipped(self) -> None:
        """Lines starting with // or # should be filtered out."""
        manifest_content = (
            "// This is a comment\n"
            "maps/c1m1_hotel.bsp\n"
            "# another comment\n"
            "scripts/example.nut\n"
        )
        path = FIXTURES / "_test_comment_lines_temp.txt"
        try:
            path.write_text(manifest_content, encoding="utf-8")
            entries = parse_manifest(path)
            self.assertEqual(len(entries), 2)
        finally:
            if path.exists():
                path.unlink()

    def test_missing_file_raises(self) -> None:
        """Parsing a non-existent manifest file should raise ParseError."""
        with self.assertRaises(ParseError):
            parse_manifest(FIXTURES / "_nonexistent_manifest.txt")


if __name__ == "__main__":
    unittest.main()
