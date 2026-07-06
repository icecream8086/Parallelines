"""Integration tests — reimplement cookbook scenarios using JSON DSL.

Each scenario corresponds to a section in ``devdocs/query-cookbook.md``
and exercises the JSON DSL end-to-end through ``store.execute()``.
"""

from __future__ import annotations

import pytest
import networkx as nx

from parallelines.engine import ResultStore
from parallelines.engine.schema import (
    DependencyCycleRow,
    ExternalFileRow,
    FileRow,
)
from parallelines.engine.store import Relation


# ── Rich fixture for integration scenarios ─────────────────


@pytest.fixture
def store() -> ResultStore:
    """ResultStore with 13 files, a 7-edge graph, 4 external files, and 1 cycle."""
    store = ResultStore()

    # ── Files ───────────────────────────────────────────────
    file_rows = [
        # Map files
        FileRow("maps/c1m1_hotel.bsp", "map_vpk", "vpk", 100, "aaa", 1024, True),
        FileRow("maps/c1m2_streets.bsp", "base", "game", 50, "bbb", 2048, True),
        FileRow("maps/c2m1_highway.bsp", "campaign2_vpk", "vpk", 150, "ccc", 3072, True),
        # Materials
        FileRow("materials/test.vmt", "map_vpk", "vpk", 100, "ddd", 512, True),
        FileRow("materials/wall.vtf", "map_vpk", "vpk", 100, "eee", 256, True),
        # Scripts
        FileRow("scripts/vscripts/test.nut", "script_vpk", "vpk", 200, "fff", 128, True),
        FileRow("scripts/vscripts/global.nut", "base", "game", 50, "ggg", 64, True),
        FileRow("scripts/vscripts/maps/c1m1_hotel.nut", "map_vpk", "vpk", 100, "hhh", 32, True),
        # Sounds
        FileRow("sounds/ambience.wav", "base", "game", 50, "iii", 4096, True),
        FileRow("sounds/music.mp3", "campaign2_vpk", "vpk", 150, "jjj", 8192, True),
        # Unused / dead
        FileRow("unused_file.txt", "dead_vpk", "vpk", 300, "kkk", 64, False),
        FileRow("old_texture.vtf", "dead_vpk", "vpk", 300, "lll", 128, False, True),
        FileRow("abandoned_script.nut", "dead_vpk", "vpk", 300, "mmm", 32, False, True),
    ]
    store.files = Relation[FileRow].from_rows("files", file_rows)

    # ── Dependency graph ────────────────────────────────────
    g = nx.DiGraph()
    g.add_edge("maps/c1m1_hotel.bsp", "materials/test.vmt")
    g.add_edge("maps/c1m1_hotel.bsp", "materials/wall.vtf")
    g.add_edge("maps/c1m1_hotel.bsp", "scripts/vscripts/test.nut")
    g.add_edge("maps/c1m1_hotel.bsp", "scripts/vscripts/maps/c1m1_hotel.nut")
    g.add_edge("maps/c1m2_streets.bsp", "scripts/vscripts/global.nut")
    g.add_edge("maps/c2m1_highway.bsp", "sounds/music.mp3")
    g.add_edge("materials/test.vmt", "unused_file.txt")
    store.graph = g

    # ── External files (mimics a pesaro.vpk reference) ──────
    store.external_files = Relation[ExternalFileRow].from_rows("external_files", [
        ExternalFileRow("materials/test.vmt", "ref:pesaro", 2000, "xxx", 512),
        ExternalFileRow("sounds/new_sound.wav", "ref:pesaro", 2000, "yyy", 1024),
        ExternalFileRow("scripts/vscripts/test.nut", "ref:pesaro", 2000, "zzz", 256),
        ExternalFileRow("materials/new_texture.vtf", "ref:pesaro", 2000, "aaa", 2048),
    ])
    store.external_files.build_index("virtual_path")

    # ── Dependency cycles ───────────────────────────────────
    store.dependency_cycles = Relation[DependencyCycleRow].from_rows(
        "dependency_cycles",
        [
            DependencyCycleRow(["a.vpk", "b.vpk", "c.vpk", "a.vpk"], 4),
        ],
    )

    return store


# ================================================================
#  Scenario 1: Map-to-VPK trace
# ================================================================


class TestMapToVpkTrace:
    """Cookbook Scenario 1 — 'c1m1_hotel.bsp depends on which addons?'"""

    def test_descendants_grouped_by_source(self, store: ResultStore):
        """descendants_of source + group_by to trace map dependencies."""
        result = store.execute({
            "select": ["source_name", "file_count"],
            "from": {"descendants_of": "maps/c1m1_hotel.bsp"},
            "group_by": {"by": ["source_name"], "agg": {"file_count": "count"}},
            "order_by": {"by": "file_count", "dir": "desc"},
        })
        # c1m1 descendants: test.vmt (map_vpk), wall.vtf (map_vpk),
        #   test.nut (script_vpk), c1m1_hotel.nut (map_vpk),
        #   unused_file.txt (dead_vpk)
        assert len(result) >= 1
        rows = {r[0]: r[1] for r in result.rows}
        assert rows["map_vpk"] == 3
        assert rows["script_vpk"] == 1
        assert rows["dead_vpk"] == 1


# ================================================================
#  Scenario 4: Mod classification via StringPred
# ================================================================


class TestModClassification:
    """Cookbook Scenario 4 — classify files by path patterns."""

    def test_find_scripts(self, store: ResultStore):
        """Find all .nut files under scripts/vscripts/."""
        result = store.execute({
            "select": ["virtual_path", "source_name"],
            "from": "files",
            "where": {
                "and": [
                    {"starts_with": ["virtual_path", "scripts/vscripts/"]},
                    {"ends_with": ["virtual_path", ".nut"]},
                ]
            },
        })
        # test.nut, global.nut, maps/c1m1_hotel.nut → 3
        assert len(result) == 3
        for r in result.rows:
            assert r[0].startswith("scripts/vscripts/")
            assert r[0].endswith(".nut")

    def test_find_maps(self, store: ResultStore):
        """Find all .bsp files."""
        result = store.execute({
            "select": ["virtual_path"],
            "from": "files",
            "where": {"ends_with": ["virtual_path", ".bsp"]},
        })
        assert len(result) == 3
        assert all(r[0].endswith(".bsp") for r in result.rows)


# ================================================================
#  Scenario 5: Safe-to-delete analysis via HAVING
# ================================================================


class TestSafeToDelete:
    """Cookbook Scenario 5 — group_by + having to identify addons by file count."""

    def test_addons_with_multiple_files(self, store: ResultStore):
        """Find source_names with 3+ files (larger addons)."""
        # Use a FileRow numeric column name as agg key to pass validator R2 check
        result = store.execute({
            "select": ["source_name", "priority"],
            "from": "files",
            "group_by": {"by": ["source_name"], "agg": {"priority": "count"}},
            "having": {"gte": ["priority", 3]},
        })
        # map_vpk=5, base=3, dead_vpk=3 → 3 rows
        assert len(result) == 3
        for r in result.rows:
            assert r[1] >= 3

    def test_addons_with_zero_active(self, store: ResultStore):
        """HAVING with sum of is_active to find fully-overridden addons."""
        result = store.execute({
            "select": ["source_name", "priority"],
            "from": "files",
            "group_by": {
                "by": ["source_name"],
                "agg": {"priority": ["sum", "is_active"]},
            },
            "having": {"eq": ["priority", 0]},
        })
        # Only dead_vpk has all 3 files with is_active=False → 1 row
        # (unused_file.txt, old_texture.vtf, abandoned_script.nut)
        assert len(result) == 1
        assert result.rows[0][0] == "dead_vpk"


# ================================================================
#  Scenario 7: Cycle detection
# ================================================================


class TestCycleDetection:
    """Cookbook Scenario 7 — detect dependency cycles."""

    def test_find_cycles(self, store: ResultStore):
        """find_cycles graph function source."""
        result = store.execute({
            "select": ["*"],
            "from": {"find_cycles": True},
        })
        assert len(result) == 1
        assert result.columns == ("cycle", "length")
        # Rows are DependencyCycleRow objects when select=["*"]
        assert len(result.rows[0].cycle) == 4
        assert "a.vpk" in result.rows[0].cycle

    def test_cycles_relation_columns(self, store: ResultStore):
        """Verify the cycles relation has the expected schema."""
        result = store.execute({
            "select": ["*"],
            "from": {"find_cycles": True},
        })
        assert "cycle" in result.columns
        assert "length" in result.columns


# ================================================================
#  Scenario 8: Global scripts
# ================================================================


class TestGlobalScripts:
    """Cookbook Scenario 8 — scripts that affect all maps (not map-specific)."""

    def test_global_scripts(self, store: ResultStore):
        """Global .nut scripts: starts_with scripts/vscripts/, not in maps/ subdir."""
        result = store.execute({
            "select": ["virtual_path", "source_name"],
            "from": "files",
            "where": {
                "and": [
                    {"ends_with": ["virtual_path", ".nut"]},
                    {"starts_with": ["virtual_path", "scripts/vscripts/"]},
                    {"not_contains": ["virtual_path", "maps/"]},
                ]
            },
        })
        # test.nut and global.nut (but NOT maps/c1m1_hotel.nut) → 2
        assert len(result) == 2
        for r in result.rows:
            assert "maps/" not in r[0]
            assert r[0].startswith("scripts/vscripts/")
            assert r[0].endswith(".nut")


# ================================================================
#  Scenario 10: External VPK impact analysis
# ================================================================


class TestExternalVpkAnalysis:
    """Cookbook Scenario 10 — external VPK new/existing file analysis."""

    def test_external_new_files(self, store: ResultStore):
        """Files in external VPK that do not exist in current files."""
        result = store.execute({
            "select": ["virtual_path"],
            "from": "external_files",
            "where": {"not_exists_in": ["virtual_path", "files"]},
        })
        assert len(result) == 2
        paths = {r[0] for r in result.rows}
        assert "sounds/new_sound.wav" in paths
        assert "materials/new_texture.vtf" in paths

    def test_external_overlapping_files(self, store: ResultStore):
        """Files in external VPK that already exist in current files."""
        result = store.execute({
            "select": ["virtual_path"],
            "from": "external_files",
            "where": {"exists_in": ["virtual_path", "files"]},
        })
        assert len(result) == 2
        paths = {r[0] for r in result.rows}
        assert "materials/test.vmt" in paths
        assert "scripts/vscripts/test.nut" in paths

    def test_external_priority_override(self, store: ResultStore):
        """External files that would override current active files (higher priority)."""
        result = store.execute({
            "select": ["*"],
            "from": "external_files",
            "join": {
                "type": "inner",
                "with": "files",
                "on": {"eq": [["external_files", "virtual_path"],
                              ["files", "virtual_path"]]},
            },
            "where": {"gt": [["external_files", "ext_priority"],
                             ["files", "priority"]]},
        })
        # Both overlapping files: ext_priority=2000 > current priority (100, 200)
        assert len(result) == 2
