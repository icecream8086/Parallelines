"""Test S3 — query operators on Relation."""
from __future__ import annotations


import pytest

from parallelines.engine.schema import FileRow, HashConflictRow
from parallelines.engine.store import Relation


@pytest.fixture
def files() -> Relation[FileRow]:
    rows = [
        FileRow("a.txt", "base", "game", 100, "abc", 1024, True),
        FileRow("b.txt", "addon_x", "addon", 200, "def", 512, True, True, False),
        FileRow("c.txt", "addon_y", "addon", 300, "ghi", 256, True, False, True),
    ]
    return Relation.from_rows("files", rows)


class TestSelect:
    def test_select_filters(self, files: Relation[FileRow]) -> None:
        dead = files.select(lambda r: r.is_dead)
        assert len(dead) == 1
        assert dead.rows[0].virtual_path == "b.txt"

    def test_select_no_match(self, files: Relation[FileRow]) -> None:
        result = files.select(lambda r: r.virtual_path == "nonexistent.txt")
        assert len(result) == 0

    def test_select_all_match(self, files: Relation[FileRow]) -> None:
        result = files.select(lambda r: True)
        assert len(result) == 3

    def test_select_does_not_mutate_original(self, files: Relation[FileRow]) -> None:
        _ = files.select(lambda r: r.is_dead)
        assert not files.rows[0].is_dead
        assert files.rows[1].is_dead


class TestSelectBy:
    def test_select_by_found(self, files: Relation[FileRow]) -> None:
        result = files.select_by("virtual_path", "a.txt")
        assert len(result) == 1
        assert result.rows[0].source_name == "base"

    def test_select_by_not_found(self, files: Relation[FileRow]) -> None:
        result = files.select_by("source_name", "nonexistent")
        assert len(result) == 0

    def test_select_by_on_tuple_relation(self) -> None:
        r = Relation("t", ("a", "b"), [(1, "x"), (2, "y")])
        result = r.select_by("a", 2)
        assert len(result) == 1
        assert result.rows[0] == (2, "y")


class TestProject:
    def test_project_single_column(self, files: Relation[FileRow]) -> None:
        names = files.project("source_name")
        assert len(names) == 3
        assert all(isinstance(r, tuple) for r in names.rows)

    def test_project_removes_duplicates(self, files: Relation[FileRow]) -> None:
        types = files.project("source_type")
        assert len(types) == 2  # game, addon (addon_x and addon_y collapse)

    def test_project_unknown_column_raises(self, files: Relation[FileRow]) -> None:
        with pytest.raises(KeyError):
            files.project("nonexistent")

    def test_project_columns_match(self, files: Relation[FileRow]) -> None:
        names = files.project("source_name")
        assert names.columns == ("source_name",)
        first = names.rows[0]
        assert isinstance(first, tuple)
        assert first[0] == "base"

    def test_project_on_tuple_relation(self, files: Relation[FileRow]) -> None:
        names = files.project("source_name")
        types = names.project("source_name")  # already tuples
        assert len(types) == 3
        assert types.columns == ("source_name",)


class TestJoin:
    def test_join_matches(self, files: Relation[FileRow]) -> None:
        conflicts = Relation.from_rows(
            "conflicts",
            [HashConflictRow("b.txt", "addon_x", "base", "def", "abc")],
        )
        joined = files.join(conflicts, on="virtual_path")
        assert len(joined) == 1
        # joined row contains all FileRow fields + HashConflictRow fields minus 'virtual_path'
        assert joined.columns == files.columns + (
            "winner_source",
            "loser_source",
            "winner_hash",
            "loser_hash",
            "severity",
        )
        assert len(joined.rows[0]) == len(joined.columns)
        # verify virtual_path appears only once
        assert joined.rows[0][0] == "b.txt"

    def test_join_dataclass_with_tuple(self, files: Relation[FileRow]) -> None:
        """dataclass side ⋈ tuple side — mixed type paths."""
        other = Relation("ratings", ("virtual_path", "score"), [("a.txt", 5), ("c.txt", 3)])
        joined = files.join(other, on="virtual_path")
        assert len(joined) == 2
        assert joined.rows[0][-1] == 5  # score appended
        assert joined.rows[1][-1] == 3

    def test_join_no_match(self, files: Relation[FileRow]) -> None:
        conflicts = Relation.from_rows(
            "conflicts",
            [HashConflictRow("z.txt", "addon_x", "base", "def", "abc")],
        )
        joined = files.join(conflicts, on="virtual_path")
        assert len(joined) == 0

    def test_join_missing_column_raises(self, files: Relation[FileRow]) -> None:
        other = Relation.from_rows("other", [])
        with pytest.raises(ValueError, match="not found"):
            files.join(other, on="nonexistent")

    def test_join_both_tuple_relations(self) -> None:
        a = Relation("a", ("id", "val"), [(1, "x"), (2, "y")])
        b = Relation("b", ("id", "desc"), [(1, "one"), (2, "two")])
        joined = a.join(b, on="id")
        assert len(joined) == 2
        assert joined.rows[0] == (1, "x", "one")
        assert joined.rows[1] == (2, "y", "two")

    def test_join_maintains_columns(self, files: Relation[FileRow]) -> None:
        conflicts = Relation.from_rows(
            "conflicts",
            [HashConflictRow("a.txt", "base", "addon_z", "abc", "xxx")],
        )
        joined = files.join(conflicts, on="virtual_path")
        assert "virtual_path" in joined.columns
        assert joined.columns.count("virtual_path") == 1  # no duplicate


class TestGroupBy:
    def test_group_by_single_key(self, files: Relation[FileRow]) -> None:
        result = files.group_by("source_type", {"count": len})
        assert result.columns == ("source_type", "count")
        rows = {r[0]: r[1] for r in result.rows}
        assert rows["game"] == 1
        assert rows["addon"] == 2

    def test_group_by_multiple_aggs(self, files: Relation[FileRow]) -> None:
        result = files.group_by("source_type", {"count": len, "total_size": lambda rs: sum(r.file_size for r in rs)})
        assert result.columns == ("source_type", "count", "total_size")
        rows = {r[0]: (r[1], r[2]) for r in result.rows}
        assert rows["game"] == (1, 1024)
        assert rows["addon"] == (2, 768)

    def test_group_by_unknown_key_raises(self, files: Relation[FileRow]) -> None:
        with pytest.raises(KeyError):
            files.group_by("nonexistent", {"count": len})

    def test_group_by_on_tuple_relation(self, files: Relation[FileRow]) -> None:
        names = files.project("source_type")
        result = names.group_by("source_type", {"count": len})
        rows = {r[0]: r[1] for r in result.rows}
        assert rows["game"] == 1
        assert rows["addon"] == 1  # project dedup'd to one per type


class TestToDicts:
    def test_to_dicts_dataclass_rows(self, files: Relation[FileRow]) -> None:
        dicts = files.to_dicts()
        assert len(dicts) == 3
        assert dicts[0]["virtual_path"] == "a.txt"
        assert dicts[0]["source_name"] == "base"
        assert dicts[0]["is_dead"] is False

    def test_to_dicts_tuple_rows(self) -> None:
        r = Relation("t", ("a", "b"), [(1, "x"), (2, "y")])
        dicts = r.to_dicts()
        assert dicts[0] == {"a": 1, "b": "x"}
        assert dicts[1] == {"a": 2, "b": "y"}


class TestToDataFrame:
    def test_to_dataframe(self, files: Relation[FileRow]) -> None:
        df = files.to_dataframe()
        assert list(df.columns) == list(files.columns)
        assert len(df) == 3
        assert df.iloc[0]["virtual_path"] == "a.txt"

    def test_to_dataframe_empty(self) -> None:
        r = Relation("empty", ("a",), [])
        df = r.to_dataframe()
        assert len(df) == 0


class TestToRows:
    def test_to_rows(self, files: Relation[FileRow]) -> None:
        rows = files.to_rows()
        assert len(rows) == 3
        assert rows[0].virtual_path == "a.txt"
        assert isinstance(rows[0], FileRow)
