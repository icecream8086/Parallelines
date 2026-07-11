"""Tests for parallelines.report.generators -- generate_report_from_store."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from parallelines.engine import FileRow, HashConflictRow, Relation, ResultStore
from parallelines.i18n import detect_language, set_language
from parallelines.report.generators import generate_report_from_store


class TestReportGenerators(unittest.TestCase):
    """Verify report generation for all supported formats."""

    def setUp(self) -> None:
        self.output_dir = Path(tempfile.mkdtemp())
        self.store = self._make_store()

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.output_dir, ignore_errors=True)

    @staticmethod
    def _make_store() -> ResultStore:
        """Create a simple ResultStore with a few rows."""
        store = ResultStore()
        store.files = Relation.from_rows(
            "files",
            [
                FileRow("a.txt", "base", "game", 100, "abc", 1024, True),
                FileRow("b.txt", "addon1", "addon", 50, "def", 2048, False),
            ],
        )
        store.hash_conflicts = Relation.from_rows(
            "hash_conflicts",
            [
                HashConflictRow("a.txt", "base", "addon", "abc", "def"),
            ],
        )
        return store

    def test_json_output(self) -> None:
        """Generate JSON report and verify its content."""
        out_path = generate_report_from_store(self.store, "json", self.output_dir)

        self.assertTrue(out_path.exists())
        self.assertEqual(out_path.suffix, ".json")

        with open(out_path, encoding="utf-8") as f:
            data = json.load(f)

        self.assertIn("files", data)
        self.assertIn("hash_conflicts", data)
        self.assertEqual(len(data["files"]), 2)
        self.assertEqual(len(data["hash_conflicts"]), 1)
        self.assertEqual(data["files"][0]["virtual_path"], "a.txt")
        self.assertEqual(data["files"][0]["source_name"], "base")

    def test_txt_output(self) -> None:
        """Generate text report and verify it contains expected sections."""
        out_path = generate_report_from_store(self.store, "text", self.output_dir)

        self.assertTrue(out_path.exists())
        self.assertEqual(out_path.suffix, ".txt")

        content = out_path.read_text(encoding="utf-8")
        self.assertIn("files", content)
        self.assertIn("hash_conflicts", content)
        self.assertIn("a.txt", content)
        self.assertIn("b.txt", content)

    def test_csv_output(self) -> None:
        """Generate CSV report and verify it contains expected rows."""
        import csv
        import io

        out_path = generate_report_from_store(self.store, "csv", self.output_dir)

        self.assertTrue(out_path.exists())
        self.assertEqual(out_path.suffix, ".csv")

        content = out_path.read_text(encoding="utf-8")
        self.assertIn("# files", content)
        self.assertIn("# hash_conflicts", content)
        self.assertIn("a.txt", content)
        self.assertIn("base", content)

        # Parse CSV to verify structure
        reader = csv.reader(io.StringIO(content))
        rows = [r for r in reader if r]  # skip blank lines
        # Should contain comment row, header row, data rows
        csv_rows = [r for r in rows if not r[0].startswith("#")]
        header = csv_rows[0]
        self.assertIn("virtual_path", header)
        self.assertIn("source_name", header)

    def test_html_output(self) -> None:
        """Generate HTML report and verify it contains expected tables."""
        prev_lang = detect_language()
        set_language("en")
        try:
            out_path = generate_report_from_store(self.store, "html", self.output_dir)
        finally:
            set_language(prev_lang)

        self.assertTrue(out_path.exists())
        self.assertEqual(out_path.suffix, ".html")

        content = out_path.read_text(encoding="utf-8")
        self.assertIn("<h1>Parallelines Analysis Report</h1>", content)
        self.assertIn("<h2>files</h2>", content)
        self.assertIn("<h2>hash_conflicts</h2>", content)
        self.assertIn("<table>", content)
        self.assertIn("a.txt", content)
        self.assertIn("</html>", content)

    def test_empty_store(self) -> None:
        """Generate JSON report from an empty store."""
        empty_store = ResultStore()
        out_path = generate_report_from_store(empty_store, "json", self.output_dir)

        self.assertTrue(out_path.exists())
        with open(out_path, encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data["files"], [])

    def test_invalid_format(self) -> None:
        """Unsupported format raises ValueError."""
        with self.assertRaises(ValueError):
            generate_report_from_store(self.store, "pdf", self.output_dir)


if __name__ == "__main__":
    unittest.main()
