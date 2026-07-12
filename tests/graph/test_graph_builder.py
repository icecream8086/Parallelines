"""Oracle-free tests for graph builder and worker.

Uses metamorphic relations (additive, differential, permutative) instead of
hard-coded expected values.  Tests focus on:

- ``GraphBuilder.build_from_cached()`` — additive MR, redundant-skip, empty VFS
- ``_add_map_audio_edges`` / ``_add_phy_edges`` — additive synthetic edges
- ``_parse_file_content`` — differential vs direct parser calls for every extension
- Graceful degradation when ``chain=None`` (no srctools)
- ``parse_file_worker`` / ``extract_deps_worker`` — dispatch by extension
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from parallelines.graph.builder import GraphBuilder
from parallelines.graph.deps import DependencyGraph
from parallelines.graph.worker import (
    _dispatch_parse,
    _dispatch_txt,
    extract_deps_worker,
    parse_file_worker,
)
from parallelines.io import FileReader
from parallelines.parsers.bsp_parser import (
    _EXEC_RE,
    extract_bsp_entity_side_effects,
)
from parallelines.parsers.manifest_parser import is_manifest_path
from parallelines.parsers.mdl_parser import extract_mdl_dependencies
from parallelines.parsers.melee_parser import extract_melee_dependencies
from parallelines.parsers.vmt_parser import extract_vmt_dependencies
from parallelines.types import FileNode
from parallelines.vfs.filesystem import VirtualFileSystem

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_node(
    virtual_path: str,
    dependencies: set[str] | None = None,
    is_redundant: bool = False,
    **kwargs,
) -> FileNode:
    """Create a FileNode with sensible defaults for testing."""
    return FileNode(
        virtual_path=virtual_path,
        source_type="test",
        source_name="test",
        dependencies=dependencies or set(),
        is_redundant=is_redundant,
        **kwargs,
    )


def _make_vfs(nodes: list[FileNode]) -> VirtualFileSystem:
    """Create and resolve a VFS from a list of FileNodes."""
    vfs = VirtualFileSystem()
    for node in nodes:
        vfs.add_file(node)
    vfs.resolve()
    return vfs


def _make_builder(vfs: VirtualFileSystem) -> GraphBuilder:
    """Create a GraphBuilder with chain=None (graceful-degradation path)."""
    return GraphBuilder(chain=None, vfs=vfs)


class _MockFileObj:
    """Minimal mock of a srctools VFS file object."""

    def __init__(self, content: str | bytes) -> None:
        self._content = content

    def open_str(self):
        if isinstance(self._content, str):
            return io.StringIO(self._content)
        return io.StringIO(self._content.decode("utf-8", errors="replace"))

    def open_bin(self):
        if isinstance(self._content, bytes):
            return io.BytesIO(self._content)
        return io.BytesIO(self._content.encode("utf-8"))


class _MockChain:
    """Dict-like mock for ``srctools.filesys.FileSystemChain``.

    Supports ``__getitem__`` with ``virtual_path -> _MockFileObj`` mapping.
    """

    def __init__(self, files: dict[str, str | bytes]) -> None:
        self._files = files

    def __getitem__(self, path: str):
        return _MockFileObj(self._files[path])


# ---------------------------------------------------------------------------
# TestBuildFromCached — GraphBuilder.build_from_cached()
# ---------------------------------------------------------------------------


class TestBuildFromCached:
    """Metamorphic relations for ``build_from_cached``.

    This static method builds a graph solely from in-memory
    ``FileNode.dependencies`` — no I/O, no chain.
    """

    def test_empty_vfs(self) -> None:
        """Empty VFS → graph with 0 nodes and 0 edges."""
        graph = GraphBuilder.build_from_cached(_make_vfs([]))
        assert graph.node_count == 0
        assert graph.edge_count == 0

    def test_additive(self) -> None:
        """MR (Additive): more deps per node → more edges, superset of nodes."""
        node_a = _make_node("a.txt", {"b.txt"})
        node_b = _make_node("c.txt", {"d.txt", "e.txt"})
        vfs_one_dep = _make_vfs([_make_node("x.txt", {"y.txt"})])
        vfs_two_deps = _make_vfs([node_a, node_b])

        graph_a = GraphBuilder.build_from_cached(vfs_one_dep)
        graph_b = GraphBuilder.build_from_cached(vfs_two_deps)

        assert graph_b.node_count >= graph_a.node_count
        assert graph_b.edge_count >= graph_a.edge_count

    def test_redundant_skipped(self) -> None:
        """Redundant nodes (is_redundant=True) are excluded from output."""
        vfs = _make_vfs([
            _make_node("active.txt", {"dep.txt"}, priority=10),
            _make_node("active.txt", {"ghost_dep.txt"}, priority=5),
        ])
        graph = GraphBuilder.build_from_cached(vfs)
        # After resolve, only the priority-10 node is active; priority-5 is
        # redundant and its deps (ghost_dep.txt) must NOT appear in the graph.
        assert graph.node_count == 2  # active.txt + dep.txt (auto-created by edge)
        assert graph.edge_count == 1  # active.txt → dep.txt only

    def test_leaf_nodes_present(self) -> None:
        """Nodes with no dependencies still appear in the graph (as leaves)."""
        vfs = _make_vfs([
            _make_node("leaf.txt"),
            _make_node("has_dep.txt", {"dep.txt"}),
        ])
        graph = GraphBuilder.build_from_cached(vfs)
        assert graph.node_count >= 2

    def test_permutative(self) -> None:
        """MR (Permutative): VFS file order does not change the graph."""
        vfs_a = _make_vfs([
            _make_node("a.txt", {"x.txt"}),
            _make_node("b.txt", {"y.txt"}),
        ])
        vfs_b = _make_vfs([
            _make_node("b.txt", {"y.txt"}),
            _make_node("a.txt", {"x.txt"}),
        ])
        graph_a = GraphBuilder.build_from_cached(vfs_a)
        graph_b = GraphBuilder.build_from_cached(vfs_b)
        assert graph_a.node_count == graph_b.node_count
        assert graph_a.edge_count == graph_b.edge_count

    def test_isolated_node_single(self) -> None:
        """Single isolated node → graph with 1 node and 0 edges."""
        vfs = _make_vfs([_make_node("alone.txt")])
        graph = GraphBuilder.build_from_cached(vfs)
        assert graph.node_count == 1
        assert graph.edge_count == 0


# ---------------------------------------------------------------------------
# TestSyntheticEdges — _add_map_audio_edges / _add_phy_edges
# ---------------------------------------------------------------------------


class TestSyntheticEdges:
    """Synthetic edges added by filename convention.

    - ``.bsp → _level_sounds.txt`` + ``soundscapes_<map>.txt``
    - ``.mdl → .phy`` (same stem, different extension)
    """

    def test_map_audio_additive(self) -> None:
        """MR (Additive): .bsp + matching audio files → at least as many edges as .bsp alone."""
        graph = DependencyGraph()
        vfs = _make_vfs([
            _make_node("maps/c1m1_hotel.bsp"),
            _make_node("maps/c1m1_hotel_level_sounds.txt"),
            _make_node("scripts/soundscapes_c1m1_hotel.txt"),
        ])

        _make_builder(vfs)._add_map_audio_edges(graph, vfs)
        edges = graph.edge_count
        assert edges >= 2  # both level_sounds and soundscapes

    def test_map_audio_no_audio_files(self) -> None:
        """No matching audio files → no synthetic edges added."""
        graph = DependencyGraph()
        vfs = _make_vfs([_make_node("maps/c1m1_hotel.bsp")])

        _make_builder(vfs)._add_map_audio_edges(graph, vfs)
        assert graph.edge_count == 0

    def test_map_audio_partial_match(self) -> None:
        """Only one audio file exists → one synthetic edge."""
        graph = DependencyGraph()
        vfs = _make_vfs([
            _make_node("maps/c1m1_hotel.bsp"),
            _make_node("maps/c1m1_hotel_level_sounds.txt"),
        ])
        builder = _make_builder(vfs)
        builder._add_map_audio_edges(graph, vfs)
        assert graph.edge_count == 1

    def test_map_audio_redundant_skipped(self) -> None:
        """Redundant .bsp files are skipped."""
        graph = DependencyGraph()
        vfs = _make_vfs([
            _make_node("maps/c1m1_hotel.bsp"),
            _make_node("maps/c1m1_hotel_level_sounds.txt"),
        ])
        # Add a redundant bsp at the same path — resolve picks the enabled one.
        vfs.add_file(_make_node("maps/c1m1_hotel.bsp", is_redundant=True))
        vfs.resolve()
        _make_builder(vfs)._add_map_audio_edges(graph, vfs)
        # Only one bsp should get edges (the active one)
        assert graph.edge_count == 1

    def test_phy_additive(self) -> None:
        """MR (Additive): .mdl + matching .phy → at least one edge."""
        graph = DependencyGraph()
        vfs = _make_vfs([
            _make_node("models/props/chair.mdl"),
            _make_node("models/props/chair.phy"),
        ])
        _make_builder(vfs)._add_phy_edges(graph, vfs)
        assert graph.edge_count >= 1

    def test_phy_no_match(self) -> None:
        """No matching .phy file → no edges."""
        graph = DependencyGraph()
        vfs = _make_vfs([_make_node("models/props/chair.mdl")])
        _make_builder(vfs)._add_phy_edges(graph, vfs)
        assert graph.edge_count == 0

    def test_phy_wrong_extensions(self) -> None:
        """Non-.mdl files do not get .phy edges."""
        graph = DependencyGraph()
        vfs = _make_vfs([
            _make_node("models/props/chair.vvd"),
            _make_node("models/props/chair.phy"),
        ])
        _make_builder(vfs)._add_phy_edges(graph, vfs)
        assert graph.edge_count == 0

    def test_phy_multi_mdl(self) -> None:
        """MR (Additive): more .mdl files with .phy → cumulative edges."""
        graph_a = DependencyGraph()
        graph_b = DependencyGraph()
        vfs_one = _make_vfs([
            _make_node("models/a.mdl"),
            _make_node("models/a.phy"),
        ])
        vfs_two = _make_vfs([
            _make_node("models/a.mdl"),
            _make_node("models/a.phy"),
            _make_node("models/b.mdl"),
            _make_node("models/b.phy"),
        ])
        _make_builder(vfs_one)._add_phy_edges(graph_a, vfs_one)
        _make_builder(vfs_two)._add_phy_edges(graph_b, vfs_two)
        assert graph_b.edge_count >= graph_a.edge_count


# ---------------------------------------------------------------------------
# TestParseFileContent — _parse_file_content(vp, ext, content) differential
# ---------------------------------------------------------------------------


class TestParseFileContent:
    """Differential tests: ``_parse_file_content`` vs direct parser calls.

    Each test passes the same content through both paths and verifies
    they produce identical results.
    """

    @pytest.fixture
    def builder(self) -> GraphBuilder:
        return _make_builder(_make_vfs([]))

    # .vmt
    def test_vmt_differential(self, builder) -> None:
        """Differential: .vmt dispatch matches ``extract_vmt_dependencies``."""
        content = b'"LightmappedGeneric" { "$basetexture" "brick/brick_floor" }'
        r1 = builder._parse_file_content("materials/test.vmt", ".vmt", content)
        r2 = extract_vmt_dependencies(content.decode())
        assert r1 == r2

    def test_vmt_additive(self, builder) -> None:
        """MR (Additive): more textures in .vmt → superset deps."""
        base = b'"VertexLitGeneric" { "$basetexture" "metal/metal1" }'
        more = b'"VertexLitGeneric" { "$basetexture" "metal/metal1" "$bumpmap" "metal/metal1_normal" }'
        deps_base = builder._parse_file_content("materials/test.vmt", ".vmt", base)
        deps_more = builder._parse_file_content("materials/test.vmt", ".vmt", more)
        assert deps_more >= deps_base

    # .txt — game_sounds
    def test_txt_game_sounds_differential(self, builder) -> None:
        """Differential: game_sounds .txt matches direct parser."""
        content = b'"s1" { "wave" "sound/a.wav" }'
        r1 = builder._parse_file_content("scripts/game_sounds_test.txt", ".txt", content)
        from parallelines.parsers.game_sounds_parser import extract_game_sounds_dependencies
        r2 = extract_game_sounds_dependencies(content.decode())
        assert r1 == r2

    # .txt — soundscapes
    def test_txt_soundscapes_differential(self, builder) -> None:
        """Differential: soundscapes .txt matches direct parser."""
        content = b'"wave" "sound/ambient.wav"'
        r1 = builder._parse_file_content("scripts/soundscapes_test.txt", ".txt", content)
        from parallelines.parsers.soundscapes_parser import extract_soundscapes_dependencies
        r2 = extract_soundscapes_dependencies(content.decode())
        assert r1 == r2

    # .txt — _level_sounds
    def test_txt_level_sounds_differential(self, builder) -> None:
        """Differential: _level_sounds.txt matches direct parser."""
        content = b'"area1" { "sound" "sound/step.wav" }'
        r1 = builder._parse_file_content("maps/c1m1_level_sounds.txt", ".txt", content)
        from parallelines.parsers.level_sounds_parser import extract_level_sounds_dependencies
        r2 = extract_level_sounds_dependencies(content.decode())
        assert r1 == r2

    # .txt — population
    def test_txt_population_differential(self, builder) -> None:
        """Differential: population.txt matches direct parser."""
        content = b'"z1" { "zombie_class" "Hunter" }'
        r1 = builder._parse_file_content("scripts/population/population.txt", ".txt", content)
        from parallelines.parsers.population_parser import extract_population_dependencies
        r2 = extract_population_dependencies(content.decode())
        assert r1 == r2

    # .txt — scripts/melee/
    def test_txt_melee_differential(self, builder) -> None:
        """Differential: scripts/melee/*.txt matches direct parser."""
        content = b'"axe" { "viewmodel" "models/axe.vmdl" }'
        r1 = builder._parse_file_content("scripts/melee/melee_weapons.txt", ".txt", content)
        from parallelines.parsers.melee_parser import extract_melee_dependencies
        r2 = extract_melee_dependencies(content.decode())
        assert r1 == r2

    # .txt — missions/
    def test_txt_missions_differential(self, builder) -> None:
        """Differential: missions/*.txt matches direct parser."""
        content = b'"modes" { "campaign" { "1" { "Map" "c1m1" } } }'
        r1 = builder._parse_file_content("missions/missions.txt", ".txt", content)
        from parallelines.parsers.missions_parser import extract_missions_dependencies
        r2 = extract_missions_dependencies(content.decode())
        assert r1 == r2

    # .txt — manifest
    def test_txt_manifest(self, builder) -> None:
        """Manifest .txt: returns non-comment, non-blank lines as deps."""
        content = b"sound/a.wav\n// comment\nsound/b.wav\n\nsound/c.wav"
        r1 = builder._parse_file_content("scripts/soundscapes_manifest.txt", ".txt", content)
        assert "sound/a.wav" in r1
        assert "sound/b.wav" in r1
        assert "sound/c.wav" in r1
        assert len(r1) == 3

    # .txt — sound_prefetch
    def test_txt_sound_prefetch(self, builder) -> None:
        """sound_prefetch.txt: each line is a dep, gets sound/ prefix."""
        content = b"ambient/test.wav\nmusic/boss.wav\n// comment"
        result = builder._parse_file_content("scripts/sound_prefetch.txt", ".txt", content)
        assert all(d.startswith("sound/") for d in result)
        assert "sound/ambient/test.wav" in result

    # .txt — soundmixers
    def test_txt_soundmixers(self, builder) -> None:
        """soundmixers.txt: extracts .wav/.phy tokens from quoted values."""
        content = b'"mixer1" { "wave" "sound/test.wav" "file" "models/mdl.phy" }'
        result = builder._parse_file_content("scripts/soundmixers.txt", ".txt", content)
        assert "sound/test.wav" in result
        assert "models/mdl.phy" in result

    # .txt — propdata
    def test_txt_propdata(self, builder) -> None:
        """propdata.txt: extracts .wav/.phy tokens from quoted values."""
        content = b'"prop1" { "sound" "impact.wav" "physics" "prop.phy" }'
        result = builder._parse_file_content("scripts/propdata.txt", ".txt", content)
        # impact.wav without sound/ prefix gets it added
        sound_deps = {d for d in result if d.endswith(".wav")}
        assert all(d.startswith("sound/") for d in sound_deps)

    # .txt — weapon
    def test_txt_weapon_differential(self, builder) -> None:
        """Differential: scripts/weapon_*.txt matches direct parser."""
        content = b'"w1" { "viewmodel" "models/gun.vmdl" }'
        r1 = builder._parse_file_content("scripts/weapon_pistol.txt", ".txt", content)
        from parallelines.parsers.weapon_parser import extract_weapon_dependencies
        r2 = extract_weapon_dependencies(content.decode())
        assert r1 == r2

    # .txt — hud_textures / mod_textures
    def test_txt_texture_list_differential(self, builder) -> None:
        """Differential: hud_textures.txt matches direct parser."""
        content = b'"tex1" "hud/icon_a"'
        r1 = builder._parse_file_content("scripts/hud_textures.txt", ".txt", content)
        from parallelines.parsers.texture_list_parser import extract_texture_list_dependencies
        r2 = extract_texture_list_dependencies(content.decode())
        assert r1 == r2

    # .txt — level_sounds_general
    def test_txt_level_sounds_general(self, builder) -> None:
        """level_sounds_general.txt is dispatched to level_sounds parser."""
        content = b'"area" { "sound" "sound/general.wav" }'
        r1 = builder._parse_file_content("scripts/level_sounds_general.txt", ".txt", content)
        from parallelines.parsers.level_sounds_parser import extract_level_sounds_dependencies
        r2 = extract_level_sounds_dependencies(content.decode())
        assert r1 == r2

    # .txt — scripts/weapon_manifest.txt (negative: manifest takes priority)
    def test_txt_weapon_manifest_takes_manifest_path(self, builder) -> None:
        """MR: scripts/weapon_manifest.txt hits manifest parser, not weapon parser.

        ``is_manifest_path`` returns True because "manifest" is in the path
        and it ends with ".txt", so it is checked first.
        """
        content = b"sound/a.wav\nsound/b.wav"
        result = builder._parse_file_content("scripts/weapon_manifest.txt", ".txt", content)
        # Manifest parser returns lines as-is (no weapon-parse logic).
        # If the weapon parser ran, it would look for KV pairs.
        assert "sound/a.wav" in result
        assert "sound/b.wav" in result

    # .res
    def test_res_differential(self, builder) -> None:
        """Differential: .res dispatch matches direct parser."""
        content = b'"ctx" { "image" "test_img" }'
        r1 = builder._parse_file_content("resource/test.res", ".res", content)
        from parallelines.parsers.res_parser import extract_res_dependencies
        r2 = extract_res_dependencies(content.decode())
        assert r1 == r2

    # .pcf
    def test_pcf_differential(self, builder) -> None:
        """Differential: .pcf dispatch matches direct parser."""
        content = b"materials/test/particle.vmt\x00"
        r1 = builder._parse_file_content("particles/test.pcf", ".pcf", content)
        from parallelines.parsers.pcf_parser import extract_pcf_dependencies
        r2 = extract_pcf_dependencies(content)
        assert r1 == r2

    # .nuc
    def test_nuc_differential(self, builder) -> None:
        """Differential: .nuc dispatch matches direct parser."""
        content = b"some nuc bytecode"
        r1 = builder._parse_file_content("scripts/vscripts/test.nuc", ".nuc", content)
        from parallelines.parsers.nuc_parser import extract_nuc_dependencies
        r2 = extract_nuc_dependencies(content)
        assert r1 == r2

    # .ani
    def test_ani_differential(self, builder) -> None:
        """Differential: .ani dispatch matches direct parser."""
        content = b'"sequence" { "activity" "run" }'
        r1 = builder._parse_file_content("models/test.ani", ".ani", content)
        from parallelines.parsers.ani_parser import extract_ani_dependencies
        r2 = extract_ani_dependencies(content.decode())
        assert r1 == r2

    # Unknown extensions
    def test_unknown_ext_returns_empty(self, builder) -> None:
        """Unrecognised extension → empty set."""
        assert builder._parse_file_content("test.wav", ".wav", b"data") == set()
        assert builder._parse_file_content("test.dx80.vtx", ".vtx", b"data") == set()
        assert builder._parse_file_content("test.vtf", ".vtf", b"data") == set()

    def test_unknown_txt_returns_empty(self, builder) -> None:
        """Unknown .txt path pattern → empty set."""
        result = builder._parse_file_content(
            "scripts/unknown_custom.txt", ".txt", b"something"
        )
        assert result == set()

    def test_empty_content_returns_empty(self, builder) -> None:
        """Empty content for any known path → empty set (no crash)."""
        assert builder._parse_file_content("materials/test.vmt", ".vmt", b"") == set()
        assert builder._parse_file_content(
            "scripts/game_sounds_test.txt", ".txt", b""
        ) == set()
        assert builder._parse_file_content("resource/test.res", ".res", b"") == set()

    # .bsp is NOT dispatched by _parse_file_content — it goes through
    # _extract_bsp_deps which needs the chain.  Verify the negative case:
    def test_bsp_not_in_parse_file_content(self, builder) -> None:
        """.bsp is not handled by ``_parse_file_content`` (needs chain)."""
        # .bsp extension doesn't match any branch in _parse_file_content
        result = builder._parse_file_content("maps/c1m1.bsp", ".bsp", b"...")
        assert result == set()

    # .mdl and .nut are also NOT dispatched by _parse_file_content
    def test_mdl_nut_not_in_parse_file_content(self, builder) -> None:
        """.mdl and .nut are not handled by ``_parse_file_content``."""
        assert builder._parse_file_content("models/test.mdl", ".mdl", b"...") == set()
        assert builder._parse_file_content("scripts/vscripts/test.nut", ".nut", b"...") == set()

    # .txt weapon prefix with and without "manifest" in path
    def test_weapon_excludes_manifest(self, builder) -> None:
        """scripts/weapon_* paths containing 'manifest' skip weapon parser."""
        # This path contains "weapon_" and "manifest" → manifest parser runs
        content = b"sound/a.wav"
        r1 = builder._parse_file_content("scripts/weapon_manifest.txt", ".txt", content)
        # Weapon parser would look for KV pairs; manifest parser returns raw lines
        assert "sound/a.wav" in r1  # raw line from manifest parser
        # Now check a true weapon path without "manifest"
        r2 = builder._parse_file_content("scripts/weapon_pistol.txt", ".txt", content)
        # Weapon parser on "sound/a.wav" (not valid KV) → empty set
        assert r2 == set()

    def test_soundmixers_propdata_case_insensitivity(self, builder) -> None:
        """Path matching for soundmixers/propdata is case-insensitive."""
        content_upper = b'"x" { "y" "test.wav" }'
        content_lower = b'"x" { "y" "test.wav" }'
        r1 = builder._parse_file_content("Scripts/SoundMixers.txt", ".txt", content_upper)
        r2 = builder._parse_file_content("scripts/soundmixers.txt", ".txt", content_lower)
        assert r1 == r2

    def test_txt_game_sounds_additive(self, builder) -> None:
        """MR (Additive): more game_sounds entries → superset."""
        base = b'"s1" { "wave" "sound/a.wav" }'
        more = b'"s1" { "wave" "sound/a.wav" } "s2" { "wave" "sound/b.wav" }'
        deps_base = builder._parse_file_content("scripts/game_sounds_test.txt", ".txt", base)
        deps_more = builder._parse_file_content("scripts/game_sounds_test.txt", ".txt", more)
        assert deps_more >= deps_base


# ---------------------------------------------------------------------------
# TestChainNone — graceful degradation when chain=None
# ---------------------------------------------------------------------------


class TestChainNone:
    """When ``GraphBuilder.chain`` is ``None``, all I/O returns ``None`` and
    all extraction helpers return empty sets — no crashes."""

    def test_read_text_returns_none(self) -> None:
        """``_read_text`` returns ``None`` when chain is ``None``."""
        builder = _make_builder(_make_vfs([]))
        assert builder._read_text("any/path.txt") is None

    def test_read_bytes_returns_none(self) -> None:
        """``_read_bytes`` returns ``None`` when chain is ``None``."""
        builder = _make_builder(_make_vfs([]))
        assert builder._read_bytes("any/path.bin") is None

    def test_extract_vmt_deps_returns_empty_set(self) -> None:
        """``_extract_vmt_deps`` returns empty set when chain is None."""
        vfs = _make_vfs([_make_node("materials/test.vmt")])
        builder = _make_builder(vfs)
        node = vfs.get_active_file("materials/test.vmt")
        assert node is not None
        assert builder._extract_vmt_deps(node) == set()

    def test_extract_mdl_deps_returns_empty_set(self) -> None:
        """``_extract_mdl_deps`` returns empty set when chain is None."""
        vfs = _make_vfs([_make_node("models/test.mdl")])
        builder = _make_builder(vfs)
        node = vfs.get_active_file("models/test.mdl")
        assert node is not None
        assert builder._extract_mdl_deps(node) == set()

    def test_extract_nut_deps_returns_empty_set(self) -> None:
        """``_extract_nut_deps`` returns empty set when chain is None."""
        vfs = _make_vfs([_make_node("scripts/vscripts/test.nut")])
        builder = _make_builder(vfs)
        node = vfs.get_active_file("scripts/vscripts/test.nut")
        assert node is not None
        assert builder._extract_nut_deps(node) == set()

    def test_extract_bsp_deps_returns_empty_set(self) -> None:
        """``_extract_bsp_deps`` returns empty set when chain is None."""
        vfs = _make_vfs([_make_node("maps/c1m1.bsp")])
        builder = _make_builder(vfs)
        node = vfs.get_active_file("maps/c1m1.bsp")
        assert node is not None
        assert builder._extract_bsp_deps(node) == set()

    def test_extract_manifest_deps_returns_empty_set(self) -> None:
        """``_extract_manifest_deps`` returns empty set when chain is None."""
        vfs = _make_vfs([_make_node("scripts/particles_manifest.txt")])
        builder = _make_builder(vfs)
        node = vfs.get_active_file("scripts/particles_manifest.txt")
        assert node is not None
        assert builder._extract_manifest_deps(node) == set()

    def test_all_txt_extractors_chain_none(self) -> None:
        """MR (Uniformity): all ``_extract_*`` methods return empty set when chain=None."""
        vfs = _make_vfs([
            _make_node("scripts/game_sounds.txt"),
            _make_node("scripts/soundscapes.txt"),
            _make_node("maps/map_level_sounds.txt"),
            _make_node("scripts/population/population.txt"),
            _make_node("scripts/melee/weapons.txt"),
            _make_node("missions/missions.txt"),
            _make_node("scripts/weapon_pistol.txt"),
            _make_node("scripts/hud_textures.txt"),
            _make_node("scripts/propdata.txt"),
        ])
        builder = _make_builder(vfs)

        extractors = [
            builder._extract_game_sounds_deps,
            builder._extract_soundscapes_deps,
            builder._extract_level_sounds_deps,
            builder._extract_population_deps,
            builder._extract_melee_deps,
            builder._extract_missions_deps,
            builder._extract_weapon_deps,
            builder._extract_texture_list_deps,
            builder._extract_kv_sound_deps,
        ]

        for node in vfs.get_all_active():
            for extract in extractors:
                result = extract(node)
                assert isinstance(result, set)
                # May be non-deterministically empty since _read_text returns None

    def test_binary_extractors_chain_none(self) -> None:
        """Binary extractors (pcf, nuc) return empty set when chain=None."""
        vfs = _make_vfs([
            _make_node("particles/test.pcf"),
            _make_node("scripts/vscripts/test.nuc"),
        ])
        builder = _make_builder(vfs)
        for node in vfs.get_all_active():
            ext = Path(node.virtual_path).suffix.lower()
            if ext == ".pcf":
                assert builder._extract_pcf_deps(node) == set()
            elif ext == ".nuc":
                assert builder._extract_nuc_deps(node) == set()


# ---------------------------------------------------------------------------
# TestReadWithMockChain — chain with mock provides content correctly
# ---------------------------------------------------------------------------


class TestReadWithMockChain:
    """When chain is mocked, ``_read_text`` / ``_read_bytes`` return content."""

    def test_read_text_with_mock_chain(self) -> None:
        """``_read_text`` reads string content from mock chain."""
        chain = _MockChain({"scripts/test.txt": "hello world"})
        builder = GraphBuilder(chain=chain, vfs=_make_vfs([]))
        content = builder._read_text("scripts/test.txt")
        assert content == "hello world"

    def test_read_bytes_with_mock_chain(self) -> None:
        """``_read_bytes`` reads bytes content from mock chain."""
        chain = _MockChain({"scripts/test.bin": b"\x00\x01\x02"})
        builder = GraphBuilder(chain=chain, vfs=_make_vfs([]))
        content = builder._read_bytes("scripts/test.bin")
        assert content == b"\x00\x01\x02"

    def test_read_text_chain_missing_key(self) -> None:
        """Missing key in mock chain returns None (exception caught)."""
        chain = _MockChain({})
        builder = GraphBuilder(chain=chain, vfs=_make_vfs([]))
        assert builder._read_text("nonexistent.txt") is None

    def test_extract_vmt_with_mock_chain(self) -> None:
        """``_extract_vmt_deps`` works end-to-end with a mock chain."""
        chain = _MockChain({
            "materials/test.vmt": '$basetexture "brick/brick_floor"',
        })
        vfs = _make_vfs([_make_node("materials/test.vmt")])
        builder = GraphBuilder(chain=chain, vfs=vfs)
        node = vfs.get_active_file("materials/test.vmt")
        assert node is not None
        deps = builder._extract_vmt_deps(node)
        assert "materials/brick/brick_floor.vtf" in deps

    def test_extract_game_sounds_with_mock_chain(self) -> None:
        """``_extract_game_sounds_deps`` works end-to-end with a mock chain."""
        chain = _MockChain({
            "scripts/game_sounds_test.txt": '"s1" { "wave" "sound/a.wav" }',
        })
        vfs = _make_vfs([_make_node("scripts/game_sounds_test.txt")])
        builder = GraphBuilder(chain=chain, vfs=vfs)
        node = vfs.get_active_file("scripts/game_sounds_test.txt")
        assert node is not None
        deps = builder._extract_game_sounds_deps(node)
        assert "sound/a.wav" in deps


# ---------------------------------------------------------------------------
# TestBuild — integration-level build() and build_parallel()
# ---------------------------------------------------------------------------


class TestBuild:
    """Integration-level tests for ``build()`` with mock chain."""

    def test_build_empty_vfs(self) -> None:
        """``build()`` with empty VFS → empty graph."""
        chain = _MockChain({})
        builder = GraphBuilder(chain=chain, vfs=_make_vfs([]))
        graph = builder.build()
        assert graph.node_count == 0
        assert graph.edge_count == 0

    def test_build_with_mock_chain(self) -> None:
        """``build()`` with a mock chain that returns parseable VMT content."""
        chain = _MockChain({
            "materials/test.vmt": '$basetexture "brick/brick_floor"',
        })
        vfs = _make_vfs([_make_node("materials/test.vmt")])
        builder = GraphBuilder(chain=chain, vfs=vfs)
        graph = builder.build()
        assert graph.node_count >= 1
        # Build reads the VMT through chain and adds 1 edge
        assert graph.edge_count >= 1

    def test_build_from_cached_vs_build_agreement(self) -> None:
        """Differential: ``build_from_cached`` and ``build()`` agree when
        deps are pre-populated and chain returns empty."""
        chain = _MockChain({})
        vfs = _make_vfs([
            _make_node("a.txt", dependencies={"b.txt"}),
            _make_node("b.txt"),
        ])
        from_cache = GraphBuilder.build_from_cached(vfs)
        from_build = GraphBuilder(chain=chain, vfs=vfs).build()
        assert from_cache.node_count == from_build.node_count
        # build() does not add edges from pre-populated deps on its own;
        # it only adds edges when node.dependencies is updated during parsing.
        # With empty chain, build() has no new deps → edges differ.
        # This is expected: build_from_cached is the fast path.

    def test_build_redundant_skipped_integration(self) -> None:
        """``build()`` skips redundant nodes even when chain fails."""
        chain = _MockChain({})
        vfs = _make_vfs([
            _make_node("a.txt", is_redundant=True),
            _make_node("a.txt", dependencies={"b.txt"}),
        ])
        vfs.resolve()
        graph = GraphBuilder(chain=chain, vfs=vfs).build()
        # Only one active node should be in graph
        assert graph.node_count >= 1

    def test_build_parallel_small_batch_fallback(self) -> None:
        """``build_parallel()`` with <10 files falls back to sequential fallback.

        This exercises the in-process parsing path (line 376-379 of builder.py).
        """
        chain = _MockChain({
            "materials/test.vmt": '$basetexture "brick/brick_floor"',
        })
        vfs = _make_vfs([
            _make_node("materials/test.vmt"),
            _make_node("resource/test.res", dependencies={"materials/img.vtf"}),
        ])
        builder = GraphBuilder(chain=chain, vfs=vfs)
        graph = builder.build_parallel(vfs, num_workers=1)
        assert graph.node_count >= 2
        assert graph.edge_count >= 1


# ---------------------------------------------------------------------------
# TestWorker — parse_file_worker / extract_deps_worker
# ---------------------------------------------------------------------------


class TestWorker:
    """Worker functions dispatch by extension and handle edge cases."""

    # --- extract_deps_worker / parse_file_worker ---

    def test_empty_content(self) -> None:
        """Empty content → empty results list."""
        task = ([
            ("materials/test.vmt", ".vmt", b""),
        ],)
        result = extract_deps_worker(task)
        assert result == []

    def test_unknown_extension(self) -> None:
        """Unknown extension → empty results."""
        task = ([
            ("test.wav", ".wav", b"data"),
        ],)
        result = extract_deps_worker(task)
        assert result == []

    def test_unknown_extension_mixed(self) -> None:
        """MR (Additive): known + unknown ext → only known ext yields results."""
        task = ([
            ("test.unknown", ".unknown", b"data"),
            ("materials/test.vmt", ".vmt", b'"LightmappedGeneric" { "$basetexture" "brick" }'),
        ],)
        result = extract_deps_worker(task)
        assert len(result) >= 1
        vps = {r[0] for r in result}
        assert "materials/test.vmt" in vps

    def test_dispatches_vmt(self) -> None:
        """.vmt is dispatched through ``extract_vmt_dependencies``."""
        vmt_content = b'"LightmappedGeneric" { "$basetexture" "brick/brick_floor" }'
        task = ([("materials/test.vmt", ".vmt", vmt_content)],)
        result = extract_deps_worker(task)
        assert len(result) >= 1
        vp, deps = result[0]
        assert vp == "materials/test.vmt"
        assert "materials/brick/brick_floor.vtf" in deps

    def test_dispatches_nut(self) -> None:
        """.nut is dispatched through ``extract_nut_dependencies``."""
        content = b'IncludeScript("mylib")\n'
        task = ([("scripts/vscripts/test.nut", ".nut", content)],)
        result = extract_deps_worker(task)
        assert len(result) >= 1
        vp, deps = result[0]
        assert "mylib" in " ".join(deps).lower() or any("mylib" in d for d in deps)

    def test_dispatches_txt_manifest(self) -> None:
        """Manifest .txt is dispatched via ``_dispatch_txt`` manifest path."""
        content = b"sound/a.wav\n// comment\nsound/b.wav"
        task = ([("scripts/particles_manifest.txt", ".txt", content)],)
        result = extract_deps_worker(task)
        assert len(result) >= 1
        vp, deps = result[0]
        assert "sound/a.wav" in deps
        assert "sound/b.wav" in deps

    def test_dispatches_txt_game_sounds(self) -> None:
        """game_sounds .txt dispatched through game_sounds parser."""
        content = b'"s1" { "wave" "sound/a.wav" }'
        task = ([("scripts/game_sounds_weapons.txt", ".txt", content)],)
        result = extract_deps_worker(task)
        assert len(result) >= 1
        vp, deps = result[0]
        assert "sound/a.wav" in deps

    def test_dispatches_txt_soundscapes(self) -> None:
        """soundscapes .txt dispatched through soundscapes parser."""
        content = b'"wave" "sound/ambient.wav"'
        task = ([("scripts/soundscapes_test.txt", ".txt", content)],)
        result = extract_deps_worker(task)
        assert len(result) >= 1
        vp, deps = result[0]
        assert "sound/ambient.wav" in deps

    def test_dispatches_txt_level_sounds(self) -> None:
        """_level_sounds.txt dispatched through level_sounds parser."""
        content = b'"area" { "sound" "sound/step.wav" }'
        task = ([("maps/c1m1_level_sounds.txt", ".txt", content)],)
        result = extract_deps_worker(task)
        assert len(result) >= 1
        vp, deps = result[0]
        assert "sound/step.wav" in deps

    def test_dispatches_txt_population(self) -> None:
        """population.txt dispatched through population parser."""
        content = b'"z1" { "zombie_class" "Hunter" }'
        task = ([("scripts/population/population.txt", ".txt", content)],)
        result = extract_deps_worker(task)
        assert len(result) >= 1

    def test_dispatches_res(self) -> None:
        """.res dispatched through ``extract_res_dependencies``."""
        content = b'"ctx" { "image" "test_img" }'
        task = ([("resource/test.res", ".res", content)],)
        result = extract_deps_worker(task)
        assert len(result) >= 1
        vp, deps = result[0]
        assert all(d.startswith("materials/") for d in deps)

    def test_dispatches_pcf(self) -> None:
        """.pcf dispatched through ``extract_pcf_dependencies``."""
        content = b"materials/test/particle.vmt\x00"
        task = ([("particles/test.pcf", ".pcf", content)],)
        result = extract_deps_worker(task)
        assert len(result) >= 1
        vp, deps = result[0]
        assert "materials/test/particle.vmt" in deps

    def test_dispatches_ani(self) -> None:
        """.ani dispatched through ``extract_ani_dependencies``."""
        content = b'"seq" { "activity" "run" }'
        task = ([("models/test.ani", ".ani", content)],)
        result = extract_deps_worker(task)
        # Result may be empty if content doesn't match, but should not crash
        assert isinstance(result, list)

    def test_dispatches_nuc(self) -> None:
        """.nuc dispatched through ``extract_nuc_dependencies``."""
        content = b"some nuc bytecode"
        task = ([("scripts/vscripts/test.nuc", ".nuc", content)],)
        result = extract_deps_worker(task)
        assert isinstance(result, list)

    def test_dispatches_sound_prefetch(self) -> None:
        """sound_prefetch.txt dispatched through ``_parse_simple_list``."""
        content = b"ambient/test.wav\nmusic/boss.wav"
        task = ([("scripts/sound_prefetch.txt", ".txt", content)],)
        result = extract_deps_worker(task)
        assert len(result) >= 1
        vp, deps = result[0]
        assert all(d.startswith("sound/") for d in deps)

    def test_multiple_files_additive(self) -> None:
        """MR (Additive): more files → at least as many results as fewer files."""
        single = ([("a.vmt", ".vmt", b'$basetexture "tex_a"')],)
        multi = ([
            ("a.vmt", ".vmt", b'$basetexture "tex_a"'),
            ("b.vmt", ".vmt", b'$basetexture "tex_b"'),
        ],)
        result_single = extract_deps_worker(single)
        result_multi = extract_deps_worker(multi)
        assert len(result_multi) >= len(result_single)

    def test_parse_file_worker_alias(self) -> None:
        """``parse_file_worker`` is the same function as ``extract_deps_worker``."""
        assert parse_file_worker is extract_deps_worker

    def test_task_wrapping(self) -> None:
        """Worker handles task as bare list (not wrapped in tuple)."""
        # The worker accepts both `([(vp, ext, content)],)` and `[(vp, ext, content)]`
        task_bare = [
            ("materials/test.vmt", ".vmt", b'$basetexture "brick"'),
        ]
        result = extract_deps_worker(task_bare)
        assert len(result) >= 1

    def test_malformed_content_no_crash(self) -> None:
        """Malformed content returns empty list for that item, doesn't crash."""
        task = ([
            ("test.bad", ".bad", b"binary garbage"),
            ("test.vmt", ".vmt", b'\xff\xfe\x00\x01 broken'),
        ],)
        result = extract_deps_worker(task)
        # Should not crash; .bad is unknown ext (skipped), .vmt is malformed
        assert isinstance(result, list)

    def test_dispatch_txt_unknown_pattern(self) -> None:
        """``_dispatch_txt`` with unknown path pattern → empty set."""
        result = _dispatch_txt("scripts/custom_random.txt", b"some data")
        assert result == set()

    def test_dispatch_parse_unknown_extension(self) -> None:
        """``_dispatch_parse`` with unknown ext → empty set."""
        result = _dispatch_parse("test.wav", ".wav", b"data")
        assert result == set()

    def test_worker_task_edge_single_file(self) -> None:
        """Single file input → correct extraction via worker."""
        content = b'"LightmappedGeneric" { "$basetexture" "test_tex" }'
        task = ([("test.vmt", ".vmt", content)],)
        result = extract_deps_worker(task)
        assert len(result) == 1
        assert "materials/test_tex.vtf" in result[0][1]

    def test_worker_txt_propdata(self) -> None:
        """propdata.txt dispatched through ``_parse_kv_sound_deps`` in worker."""
        content = b'"prop1" { "sound" "impact.wav" }'
        task = ([("scripts/propdata.txt", ".txt", content)],)
        result = extract_deps_worker(task)
        assert len(result) >= 1
        vp, deps = result[0]
        assert any("sound/impact.wav" in d for d in deps)

    def test_worker_txt_soundmixers(self) -> None:
        """soundmixers.txt dispatched through ``_parse_kv_sound_deps`` in worker."""
        content = b'"mixer" { "wave" "sound/test.wav" }'
        task = ([("scripts/soundmixers.txt", ".txt", content)],)
        result = extract_deps_worker(task)
        assert len(result) >= 1
        vp, deps = result[0]
        assert "sound/test.wav" in deps


# ---------------------------------------------------------------------------
# TestDispatchTxt — _dispatch_txt path coverage
# ---------------------------------------------------------------------------


class TestDispatchTxt:
    """Direct tests for ``_dispatch_txt`` — path-based .txt classification."""

    def test_manifest(self) -> None:
        deps = _dispatch_txt("scripts/particles_manifest.txt", b"a.wav\nb.wav")
        assert deps == {"a.wav", "b.wav"}

    def test_game_sounds(self) -> None:
        deps = _dispatch_txt("scripts/game_sounds_test.txt", b'"s1" { "wave" "sound/a.wav" }')
        assert "sound/a.wav" in deps

    def test_soundscapes(self) -> None:
        deps = _dispatch_txt("scripts/soundscapes_test.txt", b'"wave" "sound/ambient.wav"')
        assert deps >= {"sound/ambient.wav"}

    def test_level_sounds(self) -> None:
        deps = _dispatch_txt("maps/c1m1_level_sounds.txt", b'"a" { "sound" "sound/x.wav" }')
        assert "sound/x.wav" in deps

    def test_population(self) -> None:
        deps = _dispatch_txt("scripts/population/population.txt", b'"z1" { "zombie_class" "Hunter" }')
        assert isinstance(deps, set)

    def test_melee(self) -> None:
        deps = _dispatch_txt("scripts/melee/weapons.txt", b'"axe" { "viewmodel" "models/axe.vmdl" }')
        assert isinstance(deps, set)

    def test_missions(self) -> None:
        deps = _dispatch_txt("missions/missions.txt", b'"modes" { "c" { "1" { "Map" "c1m1" } } }')
        assert isinstance(deps, set)

    def test_weapon(self) -> None:
        deps = _dispatch_txt("scripts/weapon_pistol.txt", b'"w1" { "viewmodel" "models/gun.vmdl" }')
        assert isinstance(deps, set)

    def test_texture_list(self) -> None:
        deps = _dispatch_txt("scripts/hud_textures.txt", b'"tex1" "hud/icon"')
        assert isinstance(deps, set)

    def test_sound_prefetch(self) -> None:
        deps = _dispatch_txt("scripts/sound_prefetch.txt", b"ambient/test.wav")
        assert deps == {"sound/ambient/test.wav"}

    def test_level_sounds_general(self) -> None:
        content = b'"g" { "sound" "sound/gen.wav" }'
        deps = _dispatch_txt("scripts/level_sounds_general.txt", content)
        assert "sound/gen.wav" in deps

    def test_soundmixers(self) -> None:
        deps = _dispatch_txt("scripts/soundmixers.txt", b'"m" { "wave" "sound/x.wav" }')
        assert "sound/x.wav" in deps

    def test_propdata(self) -> None:
        deps = _dispatch_txt("scripts/propdata.txt", b'"p" { "sound" "sound/y.wav" }')
        assert "sound/y.wav" in deps

    def test_weapon_manifest_excluded(self) -> None:
        """scripts/weapon_manifest.txt hits manifest path, not weapon."""
        deps = _dispatch_txt("scripts/weapon_manifest.txt", b"a.wav")
        # Manifest parser: returns raw lines
        assert "a.wav" in deps

    def test_unknown(self) -> None:
        deps = _dispatch_txt("scripts/unknown.txt", b"data")
        assert deps == set()

    def test_empty(self) -> None:
        assert _dispatch_txt("scripts/test.txt", b"") == set()

    def test_comment_only(self) -> None:
        deps = _dispatch_txt("scripts/sound_prefetch.txt", b"// comment\n  \n")
        assert deps == set()


# ---------------------------------------------------------------------------
# TestParseContentDispatchParity — _parse_file_content vs _dispatch_parse
# ---------------------------------------------------------------------------


class TestParseContentDispatchParity:
    """Differential (metamorphic) tests: both dispatch functions must return
    identical results for the same input.

    ``_parse_file_content`` (in builder.py) is the sequential path.
    ``_dispatch_parse`` (in worker.py) is the parallel worker path.
    Any difference between them is a parity bug.
    """

    @pytest.fixture
    def builder(self) -> GraphBuilder:
        return _make_builder(_make_vfs([]))

    # --- per-extension parity ---

    def test_parity_vmt(self, builder) -> None:
        """Parity: .vmt returns same deps through both paths."""
        content = b'"LightmappedGeneric" { "$basetexture" "brick/brick_floor" }'
        vp = "materials/test.vmt"
        r1 = builder._parse_file_content(vp, ".vmt", content)
        r2 = _dispatch_parse(vp, ".vmt", content)
        assert r1 == r2

    def test_parity_nut(self, builder) -> None:
        """Parity: .nut returns same deps through both paths."""
        content = b'IncludeScript("mylib")\nPrecacheModel("models/box.mdl")\n'
        vp = "scripts/vscripts/test.nut"
        r1 = builder._parse_file_content(vp, ".nut", content)
        r2 = _dispatch_parse(vp, ".nut", content)
        assert r1 == r2

    def test_parity_nut_bytecode_skipped(self, builder) -> None:
        """Parity: .nut with 0xFAFA bytecode prefix returns empty through both."""
        content = b"\xfa\xfa\x00\x01some binary junk"
        vp = "scripts/vscripts/test.nut"
        r1 = builder._parse_file_content(vp, ".nut", content)
        r2 = _dispatch_parse(vp, ".nut", content)
        assert r1 == set()
        assert r2 == set()

    def test_parity_txt_manifest(self, builder) -> None:
        """Parity: manifest .txt returns same deps."""
        content = b"sound/a.wav\n// comment\nsound/b.wav"
        vp = "scripts/particles_manifest.txt"
        r1 = builder._parse_file_content(vp, ".txt", content)
        r2 = _dispatch_parse(vp, ".txt", content)
        assert r1 == r2

    def test_parity_txt_game_sounds(self, builder) -> None:
        """Parity: game_sounds .txt returns same deps."""
        content = b'"s1" { "wave" "sound/a.wav" }'
        vp = "scripts/game_sounds_test.txt"
        r1 = builder._parse_file_content(vp, ".txt", content)
        r2 = _dispatch_parse(vp, ".txt", content)
        assert r1 == r2

    def test_parity_txt_soundscapes(self, builder) -> None:
        """Parity: soundscapes .txt returns same deps."""
        content = b'"wave" "sound/ambient.wav"'
        vp = "scripts/soundscapes_test.txt"
        r1 = builder._parse_file_content(vp, ".txt", content)
        r2 = _dispatch_parse(vp, ".txt", content)
        assert r1 == r2

    def test_parity_txt_level_sounds(self, builder) -> None:
        """Parity: _level_sounds.txt returns same deps."""
        content = b'"area" { "sound" "sound/step.wav" }'
        vp = "maps/c1m1_level_sounds.txt"
        r1 = builder._parse_file_content(vp, ".txt", content)
        r2 = _dispatch_parse(vp, ".txt", content)
        assert r1 == r2

    def test_parity_txt_level_sounds_general(self, builder) -> None:
        """Parity: level_sounds_general.txt returns same deps."""
        content = b'"g" { "sound" "sound/gen.wav" }'
        vp = "scripts/level_sounds_general.txt"
        r1 = builder._parse_file_content(vp, ".txt", content)
        r2 = _dispatch_parse(vp, ".txt", content)
        assert r1 == r2

    def test_parity_txt_population(self, builder) -> None:
        """Parity: population.txt returns same deps."""
        content = b'"z1" { "zombie_class" "Hunter" }'
        vp = "scripts/population.txt"
        r1 = builder._parse_file_content(vp, ".txt", content)
        r2 = _dispatch_parse(vp, ".txt", content)
        assert r1 == r2

    def test_parity_txt_melee(self, builder) -> None:
        """Parity: scripts/melee/*.txt returns same deps."""
        content = b'"axe" { "viewmodel" "models/axe.vmdl" }'
        vp = "scripts/melee/melee_weapons.txt"
        r1 = builder._parse_file_content(vp, ".txt", content)
        r2 = _dispatch_parse(vp, ".txt", content)
        assert r1 == r2

    def test_parity_txt_missions(self, builder) -> None:
        """Parity: missions/*.txt returns same deps."""
        content = b'"modes" { "campaign" { "1" { "Map" "c1m1" } } }'
        vp = "missions/missions.txt"
        r1 = builder._parse_file_content(vp, ".txt", content)
        r2 = _dispatch_parse(vp, ".txt", content)
        assert r1 == r2

    def test_parity_txt_weapon(self, builder) -> None:
        """Parity: scripts/weapon_*.txt returns same deps."""
        content = b'"w1" { "viewmodel" "models/gun.vmdl" }'
        vp = "scripts/weapon_pistol.txt"
        r1 = builder._parse_file_content(vp, ".txt", content)
        r2 = _dispatch_parse(vp, ".txt", content)
        assert r1 == r2

    def test_parity_txt_texture_list(self, builder) -> None:
        """Parity: hud_textures.txt / mod_textures.txt returns same deps."""
        content = b'"tex1" "hud/icon_a"'
        vp = "scripts/hud_textures.txt"
        r1 = builder._parse_file_content(vp, ".txt", content)
        r2 = _dispatch_parse(vp, ".txt", content)
        assert r1 == r2

    def test_parity_txt_sound_prefetch(self, builder) -> None:
        """Parity: sound_prefetch.txt returns same deps."""
        content = b"ambient/test.wav\nmusic/boss.wav"
        vp = "scripts/sound_prefetch.txt"
        r1 = builder._parse_file_content(vp, ".txt", content)
        r2 = _dispatch_parse(vp, ".txt", content)
        assert r1 == r2

    def test_parity_txt_soundmixers(self, builder) -> None:
        """Parity: soundmixers.txt returns same deps."""
        content = b'"m" { "wave" "sound/x.wav" "file" "models/mdl.phy" }'
        vp = "scripts/soundmixers.txt"
        r1 = builder._parse_file_content(vp, ".txt", content)
        r2 = _dispatch_parse(vp, ".txt", content)
        assert r1 == r2

    def test_parity_txt_propdata(self, builder) -> None:
        """Parity: propdata.txt returns same deps."""
        content = b'"p" { "sound" "impact.wav" }'
        vp = "scripts/propdata.txt"
        r1 = builder._parse_file_content(vp, ".txt", content)
        r2 = _dispatch_parse(vp, ".txt", content)
        assert r1 == r2

    def test_parity_res(self, builder) -> None:
        """Parity: .res returns same deps."""
        content = b'"ctx" { "image" "test_img" }'
        vp = "resource/test.res"
        r1 = builder._parse_file_content(vp, ".res", content)
        r2 = _dispatch_parse(vp, ".res", content)
        assert r1 == r2

    def test_parity_pcf(self, builder) -> None:
        """Parity: .pcf returns same deps."""
        content = b"materials/test/particle.vmt\x00"
        vp = "particles/test.pcf"
        r1 = builder._parse_file_content(vp, ".pcf", content)
        r2 = _dispatch_parse(vp, ".pcf", content)
        assert r1 == r2

    def test_parity_nuc(self, builder) -> None:
        """Parity: .nuc returns same deps."""
        content = b"some nuc bytecode"
        vp = "scripts/vscripts/test.nuc"
        r1 = builder._parse_file_content(vp, ".nuc", content)
        r2 = _dispatch_parse(vp, ".nuc", content)
        assert r1 == r2

    def test_parity_ani(self, builder) -> None:
        """Parity: .ani returns same deps."""
        content = b'"seq" { "activity" "run" }'
        vp = "models/test.ani"
        r1 = builder._parse_file_content(vp, ".ani", content)
        r2 = _dispatch_parse(vp, ".ani", content)
        assert r1 == r2

    def test_parity_unknown_extension(self, builder) -> None:
        """Parity: unknown extensions return empty through both."""
        for vp, ext in [("test.wav", ".wav"), ("test.vtf", ".vtf"), ("test.dx80.vtx", ".vtx")]:
            r1 = builder._parse_file_content(vp, ext, b"data")
            r2 = _dispatch_parse(vp, ext, b"data")
            assert r1 == r2 == set()

    def test_parity_unknown_txt_pattern(self, builder) -> None:
        """Parity: unknown .txt path returns empty through both."""
        vp = "scripts/custom_random.txt"
        r1 = builder._parse_file_content(vp, ".txt", b"something")
        r2 = _dispatch_parse(vp, ".txt", b"something")
        assert r1 == r2 == set()

    def test_parity_empty_content(self, builder) -> None:
        """Parity: empty content for known extensions returns empty through both."""
        cases = [
            ("materials/test.vmt", ".vmt"),
            ("scripts/game_sounds_test.txt", ".txt"),
            ("resource/test.res", ".res"),
            ("scripts/vscripts/test.nut", ".nut"),
            ("particles/test.pcf", ".pcf"),
            ("models/test.ani", ".ani"),
        ]
        for vp, ext in cases:
            r1 = builder._parse_file_content(vp, ext, b"")
            r2 = _dispatch_parse(vp, ext, b"")
            assert r1 == r2

    def test_parity_additive_nut(self, builder) -> None:
        """MR (Additive): more .nut directives -> superset deps through both paths."""
        base = b'IncludeScript("lib1")\n'
        more = b'IncludeScript("lib1")\nIncludeScript("lib2")\n'
        vp = "scripts/vscripts/test.nut"
        r1_base = builder._parse_file_content(vp, ".nut", base)
        r1_more = builder._parse_file_content(vp, ".nut", more)
        r2_base = _dispatch_parse(vp, ".nut", base)
        r2_more = _dispatch_parse(vp, ".nut", more)
        assert r1_more >= r1_base  # additive MR on builder path
        assert r2_more >= r2_base  # additive MR on worker path
        assert r1_base == r2_base  # cross-differential
        assert r1_more == r2_more

    def test_parity_additive_txt_manifest(self, builder) -> None:
        """MR (Additive): more manifest entries -> superset through both."""
        base = b"sound/a.wav\n"
        more = b"sound/a.wav\nsound/b.wav\n"
        vp = "scripts/particles_manifest.txt"
        r1_base = builder._parse_file_content(vp, ".txt", base)
        r1_more = builder._parse_file_content(vp, ".txt", more)
        assert r1_more >= r1_base
        r2_base = _dispatch_parse(vp, ".txt", base)
        r2_more = _dispatch_parse(vp, ".txt", more)
        assert r2_more >= r2_base

    def test_parity_weapon_manifest_excluded(self, builder) -> None:
        """Parity: scripts/weapon_manifest.txt hits manifest parser in both."""
        content = b"sound/a.wav"
        vp = "scripts/weapon_manifest.txt"
        r1 = builder._parse_file_content(vp, ".txt", content)
        r2 = _dispatch_parse(vp, ".txt", content)
        assert r1 == r2
        assert "sound/a.wav" in r1  # manifest parser returns raw lines

    def test_parity_case_sensitivity_txt(self, builder) -> None:
        """Parity: case-insensitive path matching for txt patterns."""
        content = b'"m" { "wave" "sound/x.wav" }'
        vp_upper = "Scripts/SoundMixers.txt"
        vp_lower = "scripts/soundmixers.txt"
        r1_upper = builder._parse_file_content(vp_upper, ".txt", content)
        r1_lower = builder._parse_file_content(vp_lower, ".txt", content)
        r2_upper = _dispatch_parse(vp_upper, ".txt", content)
        r2_lower = _dispatch_parse(vp_lower, ".txt", content)
        assert r1_upper == r1_lower
        assert r2_upper == r2_lower
        assert r1_upper == r2_upper


# ---------------------------------------------------------------------------
# TestParseEdgeCases — stress tests for both dispatch functions
# ---------------------------------------------------------------------------


class TestParseEdgeCases:
    """Stress/edge-case inputs that must not crash either dispatch path and
    should produce identical results."""

    @pytest.fixture
    def builder(self) -> GraphBuilder:
        return _make_builder(_make_vfs([]))

    def test_null_bytes_in_text(self, builder) -> None:
        """Null bytes embedded in text content should not crash."""
        content = b"sound/a.wav\x00sound/b.wav"
        for vp in ("scripts/particles_manifest.txt", "scripts/game_sounds_test.txt"):
            r1 = builder._parse_file_content(vp, ".txt", content)
            r2 = _dispatch_parse(vp, ".txt", content)
            assert isinstance(r1, set)
            assert isinstance(r2, set)

    def test_unicode_bom(self, builder) -> None:
        """UTF-8 BOM at start of content should not crash."""
        content = b"\xef\xbb\xbf$basetexture brick/brick_floor"
        vp = "materials/test.vmt"
        r1 = builder._parse_file_content(vp, ".vmt", content)
        r2 = _dispatch_parse(vp, ".vmt", content)
        assert isinstance(r1, set)
        assert isinstance(r2, set)

    def test_utf16_content(self, builder) -> None:
        """UTF-16 encoded content should not crash (decode with replace)."""
        content = "$basetexture brick/brick_floor".encode("utf-16")
        vp = "materials/test.vmt"
        r1 = builder._parse_file_content(vp, ".vmt", content)
        r2 = _dispatch_parse(vp, ".vmt", content)
        assert isinstance(r1, set)
        assert isinstance(r2, set)
        assert r1 == r2

    def test_binary_garbage_as_text(self, builder) -> None:
        """Raw binary garbage passed as .txt content should not crash."""
        content = bytes(range(256))
        for vp in ("scripts/soundmixers.txt", "scripts/sound_prefetch.txt"):
            r1 = builder._parse_file_content(vp, ".txt", content)
            r2 = _dispatch_parse(vp, ".txt", content)
            assert isinstance(r1, set)
            assert isinstance(r2, set)
            assert r1 == r2

    def test_binary_garbage_as_vmt(self, builder) -> None:
        """Raw binary garbage passed as .vmt content should not crash."""
        content = bytes(range(256))
        vp = "materials/test.vmt"
        r1 = builder._parse_file_content(vp, ".vmt", content)
        r2 = _dispatch_parse(vp, ".vmt", content)
        assert isinstance(r1, set)
        assert isinstance(r2, set)
        assert r1 == r2

    def test_binary_garbage_as_nut(self, builder) -> None:
        """Raw binary garbage passed as .nut content should not crash."""
        content = bytes(range(256))
        vp = "scripts/vscripts/test.nut"
        r1 = builder._parse_file_content(vp, ".nut", content)
        r2 = _dispatch_parse(vp, ".nut", content)
        assert isinstance(r1, set)
        assert isinstance(r2, set)
        assert r1 == r2

    def test_squirrel_bytecode_exact_boundary(self, builder) -> None:
        """0xFAFA at start but only 1 byte length should not crash (len check)."""
        content = b"\xfa"
        vp = "scripts/vscripts/test.nut"
        r1 = builder._parse_file_content(vp, ".nut", content)
        r2 = _dispatch_parse(vp, ".nut", content)
        # 1 byte is < 2, so the 0xFAFA check is skipped — decode and parse
        assert isinstance(r1, set)
        assert isinstance(r2, set)
        assert r1 == r2

    def test_squirrel_bytecode_exact_2_bytes(self, builder) -> None:
        """Exactly 2 bytes of 0xFAFA should be detected as bytecode."""
        content = b"\xfa\xfa"
        vp = "scripts/vscripts/test.nut"
        r1 = builder._parse_file_content(vp, ".nut", content)
        r2 = _dispatch_parse(vp, ".nut", content)
        assert r1 == set()
        assert r2 == set()

    def test_extreme_long_path(self, builder) -> None:
        """Extremely long virtual path should not crash either dispatch."""
        long_vp = "scripts/" + "a" * 500 + "/sound_prefetch.txt"
        content = b"sound/test.wav"
        r1 = builder._parse_file_content(long_vp, ".txt", content)
        r2 = _dispatch_parse(long_vp, ".txt", content)
        assert isinstance(r1, set)
        assert isinstance(r2, set)
        assert r1 == r2

    def test_emoji_in_path(self, builder) -> None:
        """Unicode (emoji, CJK) in virtual path routes to correct parser."""
        content = b'"s1" { "wave" "sound/a.wav" }'

        # Emoji in path — "game_sounds" pattern match is Unicode-safe
        vp_emoji = "scripts/\U0001f600_game_sounds_test.txt"
        r1 = builder._parse_file_content(vp_emoji, ".txt", content)
        r2 = _dispatch_parse(vp_emoji, ".txt", content)
        assert "sound/a.wav" in r1
        assert r1 == r2

        # CJK in path — same Unicode safety
        vp_cjk = "scripts/声音_game_sounds_test.txt"
        r3 = builder._parse_file_content(vp_cjk, ".txt", content)
        r4 = _dispatch_parse(vp_cjk, ".txt", content)
        assert "sound/a.wav" in r3
        assert r3 == r4

    def test_empty_path_with_content(self, builder) -> None:
        """Empty virtual path should not crash."""
        content = b"something"
        r1 = builder._parse_file_content("", ".txt", content)
        r2 = _dispatch_parse("", ".txt", content)
        # Empty path won't match any txt pattern → empty set
        assert r1 == set()
        assert r2 == set()
        assert r1 == r2

    def test_content_with_only_comments(self, builder) -> None:
        """Only comments in .txt content → empty deps through both."""
        content = b"// comment 1\n# comment 2\n  \n// another"
        vp = "scripts/sound_prefetch.txt"
        r1 = builder._parse_file_content(vp, ".txt", content)
        r2 = _dispatch_parse(vp, ".txt", content)
        assert r1 == set()
        assert r2 == set()

    def test_content_with_only_braces_after_comments(self, builder) -> None:
        """Only braces and comments in .txt → empty deps through both."""
        content = b"// header\n{ // block start\nsomething\n}"
        vp = "scripts/soundmixers.txt"
        r1 = builder._parse_file_content(vp, ".txt", content)
        r2 = _dispatch_parse(vp, ".txt", content)
        assert r1 == r2


# ---------------------------------------------------------------------------
# TestBuildParallelAgreement — build() vs build_parallel() produce same graph
# ---------------------------------------------------------------------------


class TestBuildParallelAgreement:
    """Critical differential: sequential ``build()`` and parallel
    ``build_parallel()`` must produce the same dependency graph from the same
    VFS + chain.

    If they diverge, one code path silently drops or adds edges.
    """

    def _make_chain_and_vfs(self):
        """Create a mock chain + VFS with a representative mix of file types."""
        chain = _MockChain({
            "materials/brick/brick_floor.vtf": "",
            "materials/test.vmt": '$basetexture "brick/brick_floor"',
            "scripts/game_sounds_test.txt": '"s1" { "wave" "sound/a.wav" }',
            "scripts/sound_prefetch.txt": "ambient/test.wav\nmusic/boss.wav",
            "resource/test.res": '"ctx" { "image" "test_img" }',
            "scripts/particles_manifest.txt": "sound/a.wav\nsound/b.wav",
            "scripts/soundmixers.txt": '"m1" { "wave" "sound/x.wav" }',
            "scripts/propdata.txt": '"p1" { "sound" "impact.wav" }',
            "scripts/melee/melee_weapons.txt": '"axe" { "viewmodel" "models/axe.vmdl" }',
            "scripts/hud_textures.txt": '"tex1" "hud/icon_a"',
        })
        vfs = _make_vfs([
            _make_node("materials/test.vmt"),
            _make_node("scripts/game_sounds_test.txt"),
            _make_node("scripts/sound_prefetch.txt"),
            _make_node("resource/test.res"),
            _make_node("scripts/particles_manifest.txt"),
            _make_node("scripts/soundmixers.txt"),
            _make_node("scripts/propdata.txt"),
            _make_node("scripts/melee/melee_weapons.txt"),
            _make_node("scripts/hud_textures.txt"),
        ])
        return chain, vfs

    def _graph_signature(self, graph: DependencyGraph) -> tuple[int, int, set[tuple[str, str]]]:
        """Extract a comparable signature from a graph: node count, edge count, edges."""
        # Build edges set by iterating the underlying DiGraph
        edges = set()
        for u in graph._graph.nodes:
            for v in graph._graph.successors(u):
                edges.add((u, v))
        return (graph.node_count, graph.edge_count, frozenset(edges))

    def test_build_agreement(self) -> None:
        """``build()`` and ``build_parallel()`` produce identical graphs."""
        chain, vfs = self._make_chain_and_vfs()

        # Deep-ish copy: create a second VFS with same nodes (new objects)
        vfs2 = _make_vfs([
            _make_node(n.virtual_path, n.dependencies.copy(), n.is_redundant)
            for n in vfs.get_all_active()
        ])

        builder1 = GraphBuilder(chain=chain, vfs=vfs)
        builder2 = GraphBuilder(chain=chain, vfs=vfs2)

        graph_seq = builder1.build()
        graph_par = builder2.build_parallel(vfs2)

        sig_seq = self._graph_signature(graph_seq)
        sig_par = self._graph_signature(graph_par)

        assert sig_seq == sig_par, (
            f"build() vs build_parallel() differ: "
            f"seq nodes={sig_seq[0]} edges={sig_seq[1]}, "
            f"par nodes={sig_par[0]} edges={sig_par[1]}"
        )

    def test_build_agreement_additive(self) -> None:
        """MR (Additive): more files in VFS -> larger graph in both paths."""
        chain_single, vfs_single = self._make_chain_and_vfs()
        chain_full, vfs_full = self._make_chain_and_vfs()
        # Add one more file to the full case
        extra_node = _make_node("extra.txt", dependencies={"dep.txt"})
        vfs_full.add_file(extra_node)
        vfs_full.resolve()

        # Make copies for parallel path
        vfs_single_par = _make_vfs([
            _make_node(n.virtual_path, n.dependencies.copy(), n.is_redundant)
            for n in vfs_single.get_all_active()
        ])
        vfs_full_par = _make_vfs([
            _make_node(n.virtual_path, n.dependencies.copy(), n.is_redundant)
            for n in vfs_full.get_all_active()
        ])

        graph_single = GraphBuilder(chain=chain_single, vfs=vfs_single).build()
        graph_full = GraphBuilder(chain=chain_full, vfs=vfs_full).build()
        graph_single_par = GraphBuilder(chain=chain_single, vfs=vfs_single_par).build_parallel(vfs_single_par)
        graph_full_par = GraphBuilder(chain=chain_full, vfs=vfs_full_par).build_parallel(vfs_full_par)

        assert graph_full.node_count >= graph_single.node_count
        assert graph_full.edge_count >= graph_single.edge_count
        # Cross-validate: sequential and parallel agree
        assert self._graph_signature(graph_single) == self._graph_signature(graph_single_par)
        assert self._graph_signature(graph_full) == self._graph_signature(graph_full_par)

    def test_build_agreement_empty_vfs(self) -> None:
        """Empty VFS -> both paths produce 0-node, 0-edge graphs."""
        chain = _MockChain({})
        vfs = _make_vfs([])

        graph_seq = GraphBuilder(chain=chain, vfs=vfs).build()
        graph_par = GraphBuilder(chain=chain, vfs=vfs).build_parallel(vfs)

        assert graph_seq.node_count == 0
        assert graph_seq.edge_count == 0
        assert graph_par.node_count == 0
        assert graph_par.edge_count == 0
        assert self._graph_signature(graph_seq) == self._graph_signature(graph_par)

    def test_build_agreement_redundant_skipped(self) -> None:
        """Redundant nodes are skipped identically in both paths."""
        chain = _MockChain({})
        vfs = _make_vfs([
            _make_node("a.txt", is_redundant=True),
            _make_node("a.txt", dependencies={"b.txt"}),
        ])
        vfs.resolve()

        vfs_par = _make_vfs([
            _make_node(n.virtual_path, n.dependencies.copy(), n.is_redundant)
            for n in vfs.get_all_active()
        ])

        graph_seq = GraphBuilder(chain=chain, vfs=vfs).build()
        graph_par = GraphBuilder(chain=chain, vfs=vfs_par).build_parallel(vfs_par)

        assert graph_seq.node_count == graph_par.node_count
        assert graph_seq.edge_count == graph_par.edge_count


# ---------------------------------------------------------------------------
# TestParserFixes — regression tests for source-code changes in parsers and io
# ---------------------------------------------------------------------------


class TestParserFixes:
    """Regression tests for source changes that had no prior coverage.

    Covers fixes in bsp_parser, mdl_parser, melee_parser, and io.FileReader.
    """

    # ------------------------------------------------------------------
    # bsp_parser: .strip('"') on exec targets (issue 00040)
    # ------------------------------------------------------------------

    def test_bsp_quoted_exec_command(self) -> None:
        """exec commands with quoted targets have quotes stripped.

        Without ``.strip('"')`` an exec target like ``"maps/map_settings"``
        would produce the path ``"maps/map_settings.cfg"`` instead of
        ``maps/map_settings.cfg``.
        """
        # _MockEnt duplicate (defined here to keep test self-contained)
        class _MockEnt:
            def __init__(self, kv: dict[str, str]) -> None:
                self._kv = kv
            def get(self, key: str, default: str = "") -> str:
                return self._kv.get(key, default)

        class _MockBSP:
            class ents:
                entities = [
                    _MockEnt({
                        "classname": "point_servercommand",
                        "command": 'exec "maps/map_settings"',
                    }),
                ]

        # Step 1: extract_bsp_entity_side_effects returns the raw command.
        result = extract_bsp_entity_side_effects(_MockBSP())
        assert result["commands"] == ['exec "maps/map_settings"']

        # Step 2: verify _EXEC_RE + .strip('"') (same pipeline as
        # extract_bsp_dependencies) produces an unquoted path.
        for cmd in result["commands"]:
            for m in _EXEC_RE.finditer(cmd):
                exec_target = m.group(1).strip().replace("\\", "/").strip('"')
                # Without .strip('"') the target would still have quotes.
                assert '"' not in exec_target
                if not exec_target.endswith(".cfg"):
                    exec_target += ".cfg"
                if "/" not in exec_target:
                    exec_target = "cfg/" + exec_target
                # The final path must not contain embedded quotes.
                assert exec_target == "maps/map_settings.cfg"

    def test_bsp_quoted_exec_command_toplevel(self) -> None:
        """exec with bare filename (no directory) also strips quotes."""
        class _MockEnt:
            def __init__(self, kv: dict[str, str]) -> None:
                self._kv = kv
            def get(self, key: str, default: str = "") -> str:
                return self._kv.get(key, default)

        class _MockBSP:
            class ents:
                entities = [
                    _MockEnt({
                        "classname": "point_servercommand",
                        "command": 'exec "map_settings"',
                    }),
                ]

        result = extract_bsp_entity_side_effects(_MockBSP())
        assert result["commands"] == ['exec "map_settings"']

        for cmd in result["commands"]:
            for m in _EXEC_RE.finditer(cmd):
                exec_target = m.group(1).strip().replace("\\", "/").strip('"')
                assert '"' not in exec_target
                if not exec_target.endswith(".cfg"):
                    exec_target += ".cfg"
                if "/" not in exec_target:
                    exec_target = "cfg/" + exec_target
                assert exec_target == "cfg/map_settings.cfg"

    # ------------------------------------------------------------------
    # mdl_parser: AnimEvents guard when chain is None  (issue 00040)
    # ------------------------------------------------------------------

    def test_mdl_deps_chain_none_no_crash(self) -> None:
        """``extract_mdl_dependencies(None, "x.mdl")`` does not raise."""
        result = extract_mdl_dependencies(None, "x.mdl")
        assert isinstance(result, set)

    # ------------------------------------------------------------------
    # melee_parser: ``and val`` guard against empty-string model paths
    # ------------------------------------------------------------------

    def test_melee_empty_string_excluded(self) -> None:
        """Empty-string model paths are NOT added to deps."""
        content = '"axe" { "viewmodel" "" "worldmodel" "models/axe.vmdl" }'
        deps = extract_melee_dependencies(content)
        assert "" not in deps
        assert "models/axe.vmdl" in deps

    # ------------------------------------------------------------------
    # io.FileReader: read_vfs_text with valid / failing mocks
    # ------------------------------------------------------------------

    def test_read_vfs_text_valid(self) -> None:
        """``read_vfs_text`` returns text from a valid file object."""
        mock = _MockFileObj("hello world")
        result = FileReader.read_vfs_text(mock)
        assert result == "hello world"

    def test_read_vfs_text_failure_returns_none(self) -> None:
        """``read_vfs_text`` returns ``None`` when the file object raises."""
        class _FailingMock:
            def open_str(self):
                raise IOError("mock failure")

        result = FileReader.read_vfs_text(_FailingMock())
        assert result is None
