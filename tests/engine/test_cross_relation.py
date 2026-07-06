"""Cross-relation integration tests (CRS-01 ~ CRS-09)."""
from __future__ import annotations

import pytest

from parallelines.engine import ResultStore
from parallelines.engine.schema import ExternalFileRow, FileRow
from parallelines.engine.store import Relation
from parallelines.engine.query_validator import QueryValidationError


@pytest.fixture
def store() -> ResultStore:
    store = ResultStore()
    store.files = Relation[FileRow].from_rows("files", [
        FileRow("a.txt", "base", "game", 100, "abc", 1024, True),
        FileRow("b.txt", "addon", "addon", 200, "def", 512, True),
    ])
    store.external_files = Relation[ExternalFileRow].from_rows("external_files", [
        ExternalFileRow("a.txt", "ref:ext", 2000, "abc", 1024),
        ExternalFileRow("c.txt", "ref:ext", 2000, "new", 768),
    ])
    store.external_files.build_index("virtual_path")
    return store


class TestExistsIn:
    def test_value_exists(self, store: ResultStore):
        """CRS-01: exists_in — value found in target relation."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"exists_in": ["virtual_path", "external_files"]},
        })
        assert len(r) == 1  # a.txt exists in external_files

    def test_value_not_exists(self, store: ResultStore):
        """CRS-02: exists_in — value NOT in target (b.txt is not in external_files)."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"and": [
                {"eq": ["source_name", "addon"]},
                {"exists_in": ["virtual_path", "external_files"]},
            ]},
        })
        assert len(r) == 0  # b.txt not in external_files

    def test_not_exists_in_true(self, store: ResultStore):
        """CRS-03: not_exists_in — value not in target."""
        r = store.execute({
            "select": ["*"], "from": "external_files",
            "where": {"not_exists_in": ["virtual_path", "files"]},
        })
        assert len(r) == 1
        assert r.rows[0].virtual_path == "c.txt"

    def test_not_exists_in_false(self, store: ResultStore):
        """CRS-04: not_exists_in — value IS in target (a.txt is in files)."""
        r = store.execute({
            "select": ["*"], "from": "external_files",
            "where": {"and": [
                {"eq": ["virtual_path", "a.txt"]},
                {"not_exists_in": ["virtual_path", "files"]},
            ]},
        })
        assert len(r) == 0  # a.txt IS in files, so not_exists_in returns False

    def test_auto_builds_index(self, store: ResultStore):
        """CRS-05: exists_in auto-builds index on target."""
        # Start fresh without index
        s = store
        r = s.execute({
            "select": ["*"], "from": "files",
            "where": {"exists_in": ["virtual_path", "external_files"]},
        })
        assert len(r) == 1

    def test_nonexistent_target(self, store: ResultStore):
        """CRS-06: exists_in on nonexistent target is rejected by validator."""
        with pytest.raises(QueryValidationError):
            store.execute({
                "select": ["*"], "from": "files",
                "where": {"exists_in": ["virtual_path", "nonexistent_rel"]},
            })


class TestCrossColumnCompare:
    def test_gt_between_columns(self, store: ResultStore):
        """CRS-07: cross-column gt comparison."""
        r = store.execute({
            "select": [["external_files", "virtual_path"]],
            "from": "external_files",
            "join": {
                "type": "inner",
                "with": "files",
                "on": {"eq": [["external_files", "virtual_path"], ["files", "virtual_path"]]},
            },
            "where": {"gt": [["external_files", "ext_priority"], ["files", "priority"]]},
        })
        assert len(r) == 1  # ext_priority 2000 > priority 100

    def test_eq_between_columns(self, store: ResultStore):
        """CRS-08: cross-column eq comparison."""
        r = store.execute({
            "select": [["external_files", "virtual_path"]],
            "from": "files",
            "join": {
                "type": "inner",
                "with": "external_files",
                "on": {"eq": [["files", "virtual_path"], ["external_files", "virtual_path"]]},
            },
            "where": {"neq": [["files", "file_hash"], ["external_files", "ext_file_hash"]]},
        })
        assert len(r) == 0  # a.txt has same hash in both

    def test_qualified_column_refs(self, store: ResultStore):
        """CRS-09: qualified column refs with relation prefix."""
        r = store.execute({
            "select": [["external_files", "virtual_path"]],
            "from": "external_files",
            "join": {
                "type": "inner",
                "with": "files",
                "on": {"eq": [["external_files", "virtual_path"], ["files", "virtual_path"]]},
            },
        })
        assert len(r) == 1
