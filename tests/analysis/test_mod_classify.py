"""Tests for parallelines.analysis.mod_classify — ModClassifier."""

from __future__ import annotations

import unittest

from parallelines.analysis.mod_classify import ModClassifier
from parallelines.engine import FileRow, Relation, ResultStore


class TestModClassifier(unittest.TestCase):
    """Verify ModClassifier classification logic."""

    def setUp(self) -> None:
        self.classifier = ModClassifier()

    def _make_store(self, file_rows: list[FileRow]) -> ResultStore:
        store = ResultStore()
        store.files = Relation.from_rows("files", file_rows)
        return store

    def test_map_type(self) -> None:
        """Files with .bsp extension are classified as map."""
        files = [
            FileRow(
                virtual_path="maps/c1m1_hotel.bsp",
                source_name="map_addon",
                source_type="addon",
                priority=50,
                file_hash="",
                file_size=1000,
                is_active=True,
            ),
            FileRow(
                virtual_path="materials/test.vtf",
                source_name="map_addon",
                source_type="addon",
                priority=50,
                file_hash="",
                file_size=100,
                is_active=True,
            ),
        ]
        store = self._make_store(files)
        self.classifier.analyze(None, None, store)
        self.assertIsNotNone(store.mod_types)
        self.assertEqual(len(store.mod_types), 1)
        self.assertEqual(store.mod_types.rows[0].mod_type, "map")
        self.assertEqual(store.mod_types.rows[0].source_name, "map_addon")

    def test_script_type(self) -> None:
        """Files with .nut extension are classified as script."""
        files = [
            FileRow(
                virtual_path="scripts/vscripts/test.nut",
                source_name="script_addon",
                source_type="addon",
                priority=50,
                file_hash="",
                file_size=500,
                is_active=True,
            ),
        ]
        store = self._make_store(files)
        self.classifier.analyze(None, None, store)
        self.assertIsNotNone(store.mod_types)
        self.assertEqual(len(store.mod_types), 1)
        self.assertEqual(store.mod_types.rows[0].mod_type, "script")

    def test_fragment_type(self) -> None:
        """Few files (< 10) are classified as fragment."""
        files = [
            FileRow(
                virtual_path=f"file_{i}.txt",
                source_name="frag_addon",
                source_type="addon",
                priority=50,
                file_hash="",
                file_size=10,
                is_active=True,
            )
            for i in range(5)
        ]
        store = self._make_store(files)
        self.classifier.analyze(None, None, store)
        self.assertIsNotNone(store.mod_types)
        self.assertEqual(len(store.mod_types), 1)
        self.assertEqual(store.mod_types.rows[0].mod_type, "fragment")

    def test_resource_pack(self) -> None:
        """Many files (> 10) with no special exts are resource_pack."""
        files = [
            FileRow(
                virtual_path=f"materials/tex_{i}.vtf",
                source_name="res_addon",
                source_type="addon",
                priority=50,
                file_hash="",
                file_size=100,
                is_active=True,
            )
            for i in range(15)
        ]
        store = self._make_store(files)
        self.classifier.analyze(None, None, store)
        self.assertIsNotNone(store.mod_types)
        self.assertEqual(len(store.mod_types), 1)
        self.assertEqual(store.mod_types.rows[0].mod_type, "resource_pack")

    def test_disabled_addon(self) -> None:
        """Addon with is_disabled_addon=True is classified as disabled."""
        files = [
            FileRow(
                virtual_path="some/file.txt",
                source_name="disabled_addon",
                source_type="addon",
                priority=50,
                file_hash="",
                file_size=10,
                is_active=True,
                is_disabled_addon=True,
            ),
        ]
        store = self._make_store(files)
        self.classifier.analyze(None, None, store)
        self.assertIsNotNone(store.mod_types)
        self.assertEqual(len(store.mod_types), 1)
        self.assertEqual(store.mod_types.rows[0].mod_type, "disabled")
        self.assertTrue(store.mod_types.rows[0].is_disabled)

    def test_multiple_sources(self) -> None:
        """Multiple source_names produce multiple ModTypeRow entries."""
        files = [
            FileRow(
                virtual_path="maps/map.bsp",
                source_name="addon_a",
                source_type="addon",
                priority=50,
                file_hash="",
                file_size=1000,
                is_active=True,
            ),
            FileRow(
                virtual_path="scripts/test.nut",
                source_name="addon_b",
                source_type="addon",
                priority=50,
                file_hash="",
                file_size=500,
                is_active=True,
            ),
        ]
        store = self._make_store(files)
        self.classifier.analyze(None, None, store)
        self.assertIsNotNone(store.mod_types)
        self.assertEqual(len(store.mod_types), 2)
        types = {r.source_name: r.mod_type for r in store.mod_types.rows}
        self.assertEqual(types, {"addon_a": "map", "addon_b": "script"})

    def test_replacement_type(self) -> None:
        """Addon with > 50% files overlapping base paths is classified as replacement."""
        base = {f"shared_{i}.vtf" for i in range(7)}
        classifier = ModClassifier(base_paths=base)
        files = [FileRow(f"shared_{i}.vtf", "rep_addon", "addon", 200, "", 100, True) for i in range(7)]
        files += [FileRow(f"unique_{i}.vtf", "rep_addon", "addon", 200, "", 100, True) for i in range(5)]
        store = self._make_store(files)
        classifier.analyze(None, None, store)
        self.assertIsNotNone(store.mod_types)
        self.assertEqual(store.mod_types.rows[0].mod_type, "replacement")

    def test_replacement_below_threshold(self) -> None:
        """Addon with < 50% files overlapping base paths is NOT replacement."""
        classifier = ModClassifier(base_paths={"shared_0.vtf"})
        files = [FileRow("shared_0.vtf", "res_addon", "addon", 200, "", 100, True)]
        files += [FileRow(f"unique_{i}.vtf", "res_addon", "addon", 200, "", 100, True) for i in range(11)]
        store = self._make_store(files)
        classifier.analyze(None, None, store)
        self.assertIsNotNone(store.mod_types)
        self.assertEqual(store.mod_types.rows[0].mod_type, "resource_pack")

    def test_none_store(self) -> None:
        """When store.files is None, the analyzer returns without error."""
        store = ResultStore()
        self.classifier.analyze(None, None, store)
        self.assertIsNone(store.mod_types)


if __name__ == "__main__":
    unittest.main()
