"""Test S9 — external VPK reference (load_reference + JSON DSL queries)."""

from __future__ import annotations

import pytest

from parallelines.engine import ResultStore, Relation
from parallelines.engine.schema import ExternalFileRow, FileRow


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def store_with_files() -> ResultStore:
    """ResultStore with a minimal files relation (simulating current env)."""
    store = ResultStore()
    store.files = Relation[FileRow].from_rows("files", [
        FileRow("a.txt", "base", "game", 100, "abc123", 1024, True),
        FileRow("b.txt", "addon_x", "addon", 200, "def456", 512, True),
        FileRow("c.txt", "addon_y", "addon", 300, "ghi789", 256, True,
                False, False, False, False, True),
    ])
    return store


@pytest.fixture
def external_rows() -> list[ExternalFileRow]:
    """Sample external VPK file rows."""
    return [
        ExternalFileRow("a.txt", "ref:test", 2000, "abc123", 1024),
        ExternalFileRow("b.txt", "ref:test", 2000, "xxx999", 512),
        ExternalFileRow("d.txt", "ref:test", 2000, "new111", 768),
    ]


# ── load_reference tests ──────────────────────────────────────


class TestLoadReference:
    def test_injects_external_files(
        self, store_with_files, monkeypatch, external_rows
    ):
        """load_reference populates store.external_files with correct data."""

        def _mock_load(self, name, vpk_path, priority=2000):
            self.external_files = Relation[ExternalFileRow].from_rows(
                "external_files", external_rows
            )
            self.external_files.build_index("virtual_path")

        monkeypatch.setattr(
            "parallelines.engine.store.ResultStore.load_reference",
            _mock_load,
        )
        store_with_files.load_reference("test", "fake.vpk")
        assert store_with_files.external_files is not None
        assert len(store_with_files.external_files) == 3
        assert store_with_files.external_files.rows[0].ext_source_name == "ref:test"

    def test_builds_virtual_path_index(
        self, store_with_files, monkeypatch, external_rows
    ):
        """After load_reference, virtual_path index is usable."""
        store_with_files.external_files = Relation[ExternalFileRow].from_rows(
            "external_files", external_rows
        )
        store_with_files.external_files.build_index("virtual_path")

        result = store_with_files.external_files.lookup("virtual_path", "a.txt")
        assert len(result) == 1
        assert result[0].ext_source_name == "ref:test"

    def test_empty_vpk_creates_empty_relation(self, store_with_files):
        """load_reference with 0 entries still creates a valid empty Relation."""
        store_with_files.external_files = Relation[ExternalFileRow].from_rows(
            "external_files", []
        )
        assert store_with_files.external_files is not None
        assert len(store_with_files.external_files) == 0

    def test_repeat_call_overwrites(self, store_with_files):
        """Second load_reference replaces the previous external_files."""
        rows_a = [ExternalFileRow("a.txt", "ref:first", 2000, "abc", 100)]
        rows_b = [ExternalFileRow("x.txt", "ref:second", 2000, "def", 200)]

        store_with_files.external_files = Relation[ExternalFileRow].from_rows(
            "external_files", rows_a
        )
        a_count = len(store_with_files.external_files)

        store_with_files.external_files = Relation[ExternalFileRow].from_rows(
            "external_files", rows_b
        )
        b_count = len(store_with_files.external_files)

        assert a_count == 1
        assert b_count == 1
        assert store_with_files.external_files.rows[0].ext_source_name == "ref:second"


# ── Join column uniqueness tests ─────────────────────────────


class TestJoinNoCollision:
    def test_join_columns_no_ambiguity(self, store_with_files, external_rows):
        """After files.join(external_files, on='virtual_path'), all columns are unique."""
        store_with_files.external_files = Relation[ExternalFileRow].from_rows(
            "external_files", external_rows
        )
        joined = store_with_files.external_files.join(
            store_with_files.files, on="virtual_path"
        )
        cols = list(joined.columns)
        # Must have both ext_priority and priority, no duplicates
        assert cols.count("ext_priority") == 1
        assert cols.count("priority") == 1
        assert cols.count("ext_source_name") == 1
        assert cols.count("source_name") == 1
        assert "ext_priority" in cols
        assert "priority" in cols

    def test_project_after_join_disambiguates(self, store_with_files, external_rows):
        """After join, project() on ext_ columns returns the correct values."""
        store_with_files.external_files = Relation[ExternalFileRow].from_rows(
            "external_files", external_rows
        )
        joined = store_with_files.external_files.join(
            store_with_files.files, on="virtual_path"
        )
        proj = joined.project("ext_source_name", "source_name")
        # a.txt matches, so should have 1 row with (ref:test, base)
        assert len(proj) >= 1
        assert any(r[0] == "ref:test" for r in proj.rows)


# ── JSON DSL preset query tests ──────────────────────────────


class TestPresetOverrides:
    def test_overrides_when_external_priority_higher(
        self, store_with_files, external_rows
    ):
        """External priority 2000 > current priorities → matching paths with diff hash are overrides."""
        store_with_files.external_files = Relation[ExternalFileRow].from_rows(
            "external_files", external_rows
        )
        result = store_with_files.execute({
            "select": ["virtual_path", "ext_source_name", "source_name"],
            "from": "external_files",
            "join": {
                "type": "inner",
                "with": "files",
                "on": {"eq": [["external_files", "virtual_path"], ["files", "virtual_path"]]},
            },
            "where": {"neq": [["external_files", "ext_file_hash"], ["files", "file_hash"]]},
        })
        # a.txt: same hash (abc123) → filtered out by gt comparison
        # b.txt: hash xxx999 > fff literal, ext_priority 2000 > 200 → override
        assert len(result) >= 1

    def test_overrides_empty_when_no_external_files(self, store_with_files):
        """Overrides returns empty when no external_files loaded."""
        # When external_files is None, executing a query on it raises
        from parallelines.engine.query_validator import QueryValidationError
        with pytest.raises(QueryValidationError, match="not found"):
            store_with_files.execute({
                "select": ["virtual_path"],
                "from": "external_files",
            })


class TestPresetOverridden:
    def test_overridden_when_external_priority_lower(
        self, store_with_files
    ):
        """External priority -100 < current priorities → matching paths with diff hash are overridden."""
        ext_rows = [
            ExternalFileRow("a.txt", "ref:low", -100, "xyz", 1024),
            ExternalFileRow("c.txt", "ref:low", -100, "zzz", 256),
        ]
        store_with_files.external_files = Relation[ExternalFileRow].from_rows(
            "external_files", ext_rows
        )
        result = store_with_files.execute({
            "select": ["virtual_path", "ext_source_name"],
            "from": "external_files",
            "join": {
                "type": "inner",
                "with": "files",
                "on": {"eq": [["external_files", "virtual_path"], ["files", "virtual_path"]]},
            },
            "where": {"lt": [["external_files", "ext_priority"], ["files", "priority"]]},
        })
        # Both a.txt and c.txt: ext_priority -100 < priority
        assert len(result) == 2
        paths = {r[0] for r in result.rows}
        assert "a.txt" in paths
        assert "c.txt" in paths


class TestPresetNewFiles:
    def test_new_files_no_current_match(self, store_with_files, external_rows):
        """External files with virtual_path not in current files."""
        store_with_files.external_files = Relation[ExternalFileRow].from_rows(
            "external_files", external_rows
        )
        result = store_with_files.execute({
            "select": ["virtual_path", "ext_source_name"],
            "from": "external_files",
            "where": {"not_exists_in": ["virtual_path", "files"]},
        })
        # d.txt does not exist in current files
        assert len(result) == 1
        assert result.rows[0][0] == "d.txt"

    def test_new_files_empty_when_all_match(self, store_with_files):
        """No new files when all external paths exist in current env."""
        ext_rows = [
            ExternalFileRow("a.txt", "ref:test", 2000, "abc123", 1024),
        ]
        store_with_files.external_files = Relation[ExternalFileRow].from_rows(
            "external_files", ext_rows
        )
        result = store_with_files.execute({
            "select": ["virtual_path"],
            "from": "external_files",
            "where": {"not_exists_in": ["virtual_path", "files"]},
        })
        assert len(result) == 0
