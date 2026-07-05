"""Test S7b — outer join operators on Relation (join_left, join_right, join_full)."""

from __future__ import annotations

import pytest

from parallelines.engine.schema import FileRow, HashConflictRow
from parallelines.engine.store import Relation


class TestJoinLeft:
    """join_left — all self rows preserved, unmatched padded with None."""

    def test_join_left_matches(self) -> None:
        """2 files, 1 has conflict -> 2 rows, 1 with None values."""
        files = Relation.from_rows(
            "files",
            [
                FileRow("a.txt", "base", "game", 100, "abc", 1024, True),
                FileRow("b.txt", "addon_x", "addon", 200, "def", 512, True),
            ],
        )
        conflicts = Relation.from_rows(
            "conflicts",
            [HashConflictRow("b.txt", "addon_x", "base", "def", "abc")],
        )
        joined = files.join_left(conflicts, on="virtual_path")
        assert len(joined) == 2
        # a.txt: unmatched, conflict cols are None
        assert joined.rows[0][0] == "a.txt"
        for val in joined.rows[0][-4:]:
            assert val is None
        # b.txt: matched
        assert joined.rows[1][0] == "b.txt"
        assert joined.rows[1][-4:] == ("addon_x", "base", "def", "abc")

    def test_join_left_no_match(self) -> None:
        """No matching keys -> all left rows preserved with None padding."""
        files = Relation.from_rows(
            "files",
            [
                FileRow("a.txt", "base", "game", 100, "abc", 1024, True),
                FileRow("b.txt", "addon_x", "addon", 200, "def", 512, True),
            ],
        )
        conflicts = Relation.from_rows(
            "conflicts",
            [HashConflictRow("z.txt", "addon_x", "base", "def", "abc")],
        )
        joined = files.join_left(conflicts, on="virtual_path")
        assert len(joined) == 2
        for row in joined.rows:
            for val in row[-4:]:
                assert val is None

    def test_join_left_tuple_relation(self) -> None:
        """Left join with tuple-based relations."""
        a = Relation("a", ("id", "val"), [(1, "x"), (2, "y"), (3, "z")])
        b = Relation("b", ("id", "desc"), [(1, "one"), (3, "three")])
        joined = a.join_left(b, on="id")
        assert len(joined) == 3
        rows_by_id = {r[0]: r for r in joined.rows}
        assert rows_by_id[1] == (1, "x", "one")
        assert rows_by_id[2] == (2, "y", None)
        assert rows_by_id[3] == (3, "z", "three")

    def test_join_left_all_match(self) -> None:
        """Every row matches -> behaves like inner join."""
        a = Relation("a", ("id", "val"), [(1, "x"), (2, "y")])
        b = Relation("b", ("id", "desc"), [(1, "one"), (2, "two")])
        joined = a.join_left(b, on="id")
        assert len(joined) == 2
        assert joined.rows[0] == (1, "x", "one")
        assert joined.rows[1] == (2, "y", "two")

    def test_join_left_empty_self(self) -> None:
        """Empty left relation -> empty result."""
        a = Relation("a", ("id", "val"), [])
        b = Relation("b", ("id", "desc"), [(1, "one")])
        joined = a.join_left(b, on="id")
        assert len(joined) == 0

    def test_join_left_empty_other(self) -> None:
        """Empty right relation -> all self rows with None."""
        a = Relation("a", ("id", "val"), [(1, "x"), (2, "y")])
        b = Relation("b", ("id", "desc"), [])
        joined = a.join_left(b, on="id")
        assert len(joined) == 2
        for row in joined.rows:
            assert row[-1] is None

    def test_join_left_missing_column_raises(self) -> None:
        """Missing join column raises ValueError."""
        a = Relation("a", ("id", "val"), [])
        b = Relation("b", ("x", "desc"), [])
        with pytest.raises(ValueError, match="not found"):
            a.join_left(b, on="id")

    def test_join_left_keeps_column_structure(self) -> None:
        """Result columns = self.columns + other.columns_without_on."""
        a = Relation("a", ("id", "val"), [(1, "x")])
        b = Relation("b", ("id", "extra"), [(1, "e")])
        joined = a.join_left(b, on="id")
        assert joined.columns == ("id", "val", "extra")
        assert joined.columns.count("id") == 1  # no duplicate


class TestJoinRight:
    """join_right — equivalent to other.join_left(self, on)."""

    def test_join_right_preserves_right(self) -> None:
        """All rows from right (other) are preserved."""
        files = Relation.from_rows(
            "files",
            [FileRow("a.txt", "base", "game", 100, "abc", 1024, True)],
        )
        conflicts = Relation.from_rows(
            "conflicts",
            [
                HashConflictRow("a.txt", "addon_x", "base", "def", "abc"),
                HashConflictRow("b.txt", "addon_z", "base", "ghi", "abc"),
            ],
        )
        joined = files.join_right(conflicts, on="virtual_path")
        # join_right = conflicts.join_left(files)
        # All conflict rows preserved (2), columns = conflicts.cols + files.cols_without_on
        assert len(joined) == 2
        # a.txt: matched
        assert joined.rows[0][0] == "a.txt"
        # b.txt: unmatched -> file cols are None
        assert joined.rows[1][0] == "b.txt"
        file_col_start = len(conflicts.columns)
        for val in joined.rows[1][file_col_start:]:
            assert val is None

    def test_join_right_empty_right(self) -> None:
        """Empty right relation -> empty result."""
        a = Relation("a", ("id", "val"), [(1, "x")])
        b = Relation("b", ("id", "desc"), [])
        joined = a.join_right(b, on="id")
        assert len(joined) == 0

    def test_join_right_tuple(self) -> None:
        """Right join with tuple relations."""
        a = Relation("a", ("id", "val"), [(1, "x"), (2, "y")])
        b = Relation("b", ("id", "desc"), [(1, "one"), (3, "three")])
        # a.join_right(b) = b.join_left(a)
        # Result columns: b.cols + a.cols_without_on = (id, desc, val)
        joined = a.join_right(b, on="id")
        assert len(joined) == 2
        rows_by_id = {r[0]: r for r in joined.rows}
        assert rows_by_id[1] == (1, "one", "x")
        assert rows_by_id[3] == (3, "three", None)


class TestJoinFull:
    """join_full — union of both sides, deduplicated."""

    def test_join_full_with_and_without_matches(self) -> None:
        """Mix of matched and unmatched rows from both sides."""
        a = Relation("a", ("id", "val"), [(1, "A"), (2, "B")])
        b = Relation("b", ("id", "desc"), [(1, "X"), (3, "Z")])
        joined = a.join_full(b, on="id")
        assert len(joined) == 3
        rows_by_id = {r[0]: r for r in joined.rows}
        assert rows_by_id[1] == (1, "A", "X")
        assert rows_by_id[2] == (2, "B", None)
        assert rows_by_id[3] == (3, None, "Z")

    def test_join_full_all_match(self) -> None:
        """All rows match -> behaves like inner join."""
        a = Relation("a", ("id", "val"), [(1, "A"), (2, "B")])
        b = Relation("b", ("id", "desc"), [(1, "X"), (2, "Y")])
        joined = a.join_full(b, on="id")
        assert len(joined) == 2
        rows_by_id = {r[0]: r for r in joined.rows}
        assert rows_by_id[1] == (1, "A", "X")
        assert rows_by_id[2] == (2, "B", "Y")

    def test_join_full_no_match(self) -> None:
        """No matches -> union of both sides, padded with None."""
        a = Relation("a", ("id", "val"), [(1, "A"), (2, "B")])
        b = Relation("b", ("id", "desc"), [(3, "X"), (4, "Y")])
        joined = a.join_full(b, on="id")
        assert len(joined) == 4
        rows_by_id = {r[0]: r for r in joined.rows}
        assert rows_by_id[1] == (1, "A", None)
        assert rows_by_id[2] == (2, "B", None)
        assert rows_by_id[3] == (3, None, "X")
        assert rows_by_id[4] == (4, None, "Y")

    def test_join_full_empty_self(self) -> None:
        """Empty self -> all other rows with None for self cols."""
        a = Relation("a", ("id", "val"), [])
        b = Relation("b", ("id", "desc"), [(1, "X"), (2, "Y")])
        joined = a.join_full(b, on="id")
        assert len(joined) == 2
        rows_by_id = {r[0]: r for r in joined.rows}
        assert rows_by_id[1] == (1, None, "X")
        assert rows_by_id[2] == (2, None, "Y")

    def test_join_full_empty_other(self) -> None:
        """Empty other -> all self rows with None for other cols."""
        a = Relation("a", ("id", "val"), [(1, "A"), (2, "B")])
        b = Relation("b", ("id", "desc"), [])
        joined = a.join_full(b, on="id")
        assert len(joined) == 2
        rows_by_id = {r[0]: r for r in joined.rows}
        assert rows_by_id[1] == (1, "A", None)
        assert rows_by_id[2] == (2, "B", None)

    def test_join_full_missing_column_raises(self) -> None:
        """Missing join column raises ValueError."""
        a = Relation("a", ("id", "val"), [])
        b = Relation("b", ("x", "desc"), [])
        with pytest.raises(ValueError, match="not found"):
            a.join_full(b, on="id")

    def test_join_full_dataclass_and_tuple(self) -> None:
        """Full join between dataclass and tuple relations."""
        files = Relation.from_rows(
            "files",
            [
                FileRow("a.txt", "base", "game", 100, "abc", 1024, True),
                FileRow("b.txt", "addon_x", "addon", 200, "def", 512, True),
            ],
        )
        ratings = Relation(
            "ratings", ("virtual_path", "score"), [("a.txt", 5), ("c.txt", 3)]
        )
        joined = files.join_full(ratings, on="virtual_path")
        assert len(joined) == 3
        rows_by_path = {r[0]: r for r in joined.rows}
        assert rows_by_path["a.txt"][-1] == 5  # matched, score = 5
        assert rows_by_path["b.txt"][-1] is None  # unmatched file, score = None
        # c.txt: unmatched rating row
        c_row = rows_by_path["c.txt"]
        assert c_row[-1] == 3  # score = 3
        # The self columns (file fields) should be mostly None for unmatched other
        assert c_row[1] is None  # source_name
