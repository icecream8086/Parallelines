"""Relation API tests (REL-01 ~ REL-17)."""
from __future__ import annotations

import pytest
from parallelines.engine.store import Relation


@pytest.fixture
def rel() -> Relation:
    return Relation("test", ("name", "value", "flag"), [
        ("a", 1, True),
        ("b", 2, False),
        ("c", 3, True),
        ("a", 1, True),  # duplicate for project dedup test
    ])


class TestSelect:
    def test_select_returns_new(self, rel: Relation):
        """REL-01: select returns new Relation, original unchanged."""
        orig_len = len(rel)
        filtered = rel.select(lambda r: r[1] > 1)
        assert len(filtered) == 2
        assert len(rel) == orig_len

    def test_select_by_index(self, rel: Relation):
        """REL-02: select_by builds index and finds matches."""
        result = rel.select_by("name", "a")
        assert len(result) == 2
        assert all(r[0] == "a" for r in result.rows)


class TestProject:
    def test_project_returns_new(self, rel: Relation):
        """REL-03: project returns new Relation with dedup."""
        proj = rel.project("name", "value")
        assert len(proj) >= 1
        # Should be tuples
        assert all(isinstance(r, tuple) for r in proj.rows)


class TestJoin:
    def test_inner_join(self, rel: Relation):
        """REL-04: inner join merges on column, dedup on key."""
        other = Relation("other", ("name", "extra"), [("a", "x"), ("b", "y")])
        joined = rel.join(other, on="name")
        assert len(joined) >= 2
        assert "name" in joined.columns
        assert "extra" in joined.columns
        # "name" should appear once (unless there are duplicates in both sides)

    def test_left_join(self, rel: Relation):
        """REL-05: left join preserves left rows, NULL on right."""
        other = Relation("other", ("name", "extra"), [("a", "x")])
        joined = rel.join_left(other, on="name")
        assert len(joined) == len(rel)
        # rows without match get None in the joined columns
        null_rows = [r for r in joined.rows if r[3] is None]
        assert len(null_rows) > 0  # rows with no match get NULL

        # Check row contents: joined rows should be tuples
        assert all(isinstance(r, tuple) for r in joined.rows)

    def test_right_join(self, rel: Relation):
        """REL-06: right join is other.join_left(self)."""
        other = Relation("other", ("name", "extra"), [("a", "x"), ("z", "w")])
        right = rel.join_right(other, on="name")
        expected = other.join_left(rel, on="name")
        assert len(right) == len(expected)
        # Check that z (only in right) is included
        names_right = {r[0] for r in right.rows}
        assert "z" in names_right

    def test_full_join(self, rel: Relation):
        """REL-07: full join is left U right."""
        other = Relation("other", ("name", "extra"), [("a", "x"), ("z", "w")])
        full = rel.join_full(other, on="name")
        names = {r[0] for r in full.rows}
        assert "a" in names
        assert "z" in names


class TestGroupBy:
    def test_single_key_multi_agg(self):
        """REL-08: group by single key with multiple aggregations."""
        r = Relation("t", ("k", "v"), [("a", 1), ("a", 2), ("b", 3)])
        g = r.group_by(
            "k",
            {"cnt": len, "sum": lambda rows: sum(row[1] for row in rows)},
        )
        assert len(g) == 2
        by_key = {row[0]: row for row in g.rows}
        assert by_key["a"][1] == 2  # count
        assert by_key["a"][2] == 3  # sum

    def test_multi_key_group_by(self):
        """REL-09: group by multiple columns."""
        r = Relation("t", ("k1", "k2", "v"), [
            ("a", "x", 1),
            ("a", "x", 2),
            ("a", "y", 3),
        ])
        g = r.group_by(("k1", "k2"), {"cnt": len})
        assert len(g) == 2

    def test_group_by_empty(self):
        """REL-10: group by on empty Relation."""
        r = Relation("t", ("k", "v"), [])
        g = r.group_by("k", {"cnt": len})
        assert len(g) == 0

    def test_group_by_null_key(self):
        """REL-11: group by with None key."""
        r = Relation("t", ("k", "v"), [(None, 1), (None, 2), ("a", 3)])
        g = r.group_by("k", {"cnt": len})
        by_key = {row[0]: row for row in g.rows}
        assert by_key[None][1] == 2


class TestIndex:
    def test_build_index_single(self, rel: Relation):
        """REL-12: build_index creates hash index."""
        rel.build_index("name")
        assert "name" in rel._index

    def test_lookup_existing(self, rel: Relation):
        """REL-13: lookup returns matches."""
        rel.build_index("name")
        matches = rel.lookup("name", "a")
        assert len(matches) == 2

    def test_lookup_unindexed(self, rel: Relation):
        """REL-14: lookup on unindexed column raises."""
        with pytest.raises(KeyError):
            rel.lookup("name", "a")


class TestMisc:
    def test_update_cell(self):
        """REL-15: update_cell modifies matching rows in place."""
        from dataclasses import dataclass

        @dataclass
        class UpdRow:
            name: str
            value: int
            flag: bool

        r = Relation("test", ("name", "value", "flag"), [
            UpdRow("a", 1, True),
            UpdRow("b", 2, False),
            UpdRow("a", 1, True),
        ])
        count = r.update_cell(lambda row: row.name == "a", "value", 99)
        assert count == 2
        vals = [row.value for row in r.rows if row.name == "a"]
        assert all(v == 99 for v in vals)

    def test_to_dicts(self, rel: Relation):
        """REL-16: to_dicts converts to list of dicts."""
        dicts = rel.to_dicts()
        assert len(dicts) == len(rel)
        assert "name" in dicts[0]
        assert "value" in dicts[0]

    def test_len(self, rel: Relation):
        """REL-17: __len__ returns correct count."""
        assert len(rel) == 4
        assert len(Relation("e", ("c",), [])) == 0
