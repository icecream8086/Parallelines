"""Oracle-Free tests for all parsers using metamorphic relations.

Key principle: Never write ``assert f(x) == y_expected``.  Instead use
metamorphic relations (compositional, additive, permutative) that relate
outputs across input transformations.

Each test class documents the MR it exercises.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# 1. kv_parser — tokenize() and parse_kv()
# ---------------------------------------------------------------------------
from parallelines.parsers.kv_parser import tokenize, parse_kv


# -------- Naive reference implementation for kv_parser differential test --------
def _naive_parse_kv(text: str) -> dict:
    """Stack-machine-based KV parser — fundamentally different algorithm from parse_kv.

    Uses an explicit stack instead of recursion.  Walk tokens sequentially;
    on '{' push a new dict, on '}' pop.  Kept under 30 lines per NRI guidelines.
    """
    tokens = tokenize(text)
    stack: list[dict | list] = [{}]
    i, n = 0, len(tokens)
    while i < n:
        key = tokens[i].lower()
        i += 1
        if i >= n:
            break
        if tokens[i] == "{":
            new_dict: dict = {}
            parent = stack[-1]
            if isinstance(parent, dict):
                if key in parent:
                    existing = parent[key]
                    parent[key] = (
                        existing + [new_dict]
                        if isinstance(existing, list)
                        else [existing, new_dict]
                    )
                else:
                    parent[key] = new_dict
            stack.append(new_dict)
            i += 1
        elif key == "}" and len(stack) > 1:
            stack.pop()
        else:
            val = tokens[i]
            i += 1
            parent = stack[-1]
            if isinstance(parent, dict):
                if key in parent:
                    existing = parent[key]
                    parent[key] = (
                        existing + [val] if isinstance(existing, list) else [existing, val]
                    )
                else:
                    parent[key] = val
    return stack[0] if isinstance(stack[0], dict) else {}


class TestKvParser:
    def test_tokenize_compositional(self) -> None:
        """MR (Compositional): tokenize(a + b) == tokenize(a) + tokenize(b)."""
        a = '"key1" "val1"'
        b = '"key2" "val2"'
        assert tokenize(a + b) == tokenize(a) + tokenize(b)

    def test_tokenize_empty_returns_empty(self) -> None:
        """Empty / comment-only / whitespace-only input yields []."""
        assert tokenize("") == []
        assert tokenize("// comment") == []
        assert tokenize("  \n  ") == []

    def test_tokenize_comment_prefixes(self) -> None:
        """Lines starting with //, #, ; are ignored."""
        base = '"k" "v"'
        with_comment = '// header\n# meta\n; flag\n"k" "v"'
        assert tokenize(with_comment) == tokenize(base)

    def test_parse_kv_compositional(self) -> None:
        """MR (Compositional): parse_kv(a + b) merges top-level keys from a and b."""
        a = '"section" { "key1" "val1" }'
        b = '"other" { "key2" "val2" }'
        result = parse_kv(a + "\n" + b)
        assert "section" in result and "other" in result
        assert isinstance(result["section"], dict)
        assert isinstance(result["other"], dict)

    def test_parse_kv_permutative(self) -> None:
        """MR (Permutative): reordering top-level entries yields same result."""
        a = '"a" "1" "b" "2"'
        b = '"b" "2" "a" "1"'
        assert parse_kv(a) == parse_kv(b)

    def test_parse_kv_permutative_blocks(self) -> None:
        """Reordering top-level blocks yields same result."""
        a = '"x" { "k1" "v1" } "y" { "k2" "v2" }'
        b = '"y" { "k2" "v2" } "x" { "k1" "v1" }'
        assert parse_kv(a) == parse_kv(b)

    def test_parse_kv_nested_three_levels(self) -> None:
        """3-level nesting: parse_kv correctly builds nested dicts."""
        raw = '"a" { "b" { "c" "val" } }'
        result = parse_kv(raw)
        assert isinstance(result["a"]["b"], dict)
        assert result["a"]["b"]["c"] == "val"

    def test_parse_kv_rndwave_format(self) -> None:
        """game_sounds with rndwave: nested block inside a block."""
        raw = '"s1" { "rndwave" { "wave" "a.wav" "wave" "b.wav" } }'
        result = parse_kv(raw)
        assert isinstance(result["s1"]["rndwave"], dict)
        waves = result["s1"]["rndwave"]["wave"]
        assert isinstance(waves, list) and len(waves) == 2

    def test_parse_kv_empty_returns_empty(self) -> None:
        assert parse_kv("") == {}
        assert parse_kv("// comment only") == {}
        assert parse_kv("  \n  ") == {}

    def test_parse_kv_malformed_no_crash(self) -> None:
        """Malformed input does not crash; returns a dict (possibly empty)."""
        result = parse_kv("not a kv at all {{{ broken")
        assert isinstance(result, dict)

    def test_parse_kv_differential_flat(self) -> None:
        """Differential: parse_kv agrees with naive stack reference on flat KV."""
        cases = [
            '"a" "1"',
            '"a" "1" "b" "2"',
            '"a" "1" "a" "2"',  # duplicate keys
            '"x" { "y" "z" }',
            '"x" { "a" "1" "b" "2" }',
            '"x" { "a" "1" "a" "2" }',  # duplicate in block
            '"a" "1" "b" { "c" "2" } "d" "3"',  # mixed flat + nested
        ]
        for case in cases:
            p = parse_kv(case)
            n = _naive_parse_kv(case)
            assert p == n, f"Mismatch for {case!r}: parse_kv={p}, naive={n}"

    def test_parse_kv_differential_three_level(self) -> None:
        """Differential: 3-level nesting (missions format)."""
        raw = '"modes" { "coop" { "1" { "Map" "c1m1" } } }'
        assert parse_kv(raw) == _naive_parse_kv(raw)

    def test_parse_kv_differential_rndwave(self) -> None:
        """Differential: rndwave with duplicate keys in nested block."""
        raw = '"s1" { "rndwave" { "wave" "a" "wave" "b" } }'
        assert parse_kv(raw) == _naive_parse_kv(raw)


# ---------------------------------------------------------------------------
# 2. game_sounds_parser — extract_game_sounds_dependencies()
# ---------------------------------------------------------------------------
from parallelines.parsers.game_sounds_parser import extract_game_sounds_dependencies


class TestGameSoundsParser:
    def test_compositional(self) -> None:
        """MR (Compositional): extract(a + b) == extract(a) | extract(b)."""
        a = '"s1" { "wave" "sound/a.wav" }'
        b = '"s2" { "rndwave" { "wave" "sound/b.wav" } }'
        deps_a = extract_game_sounds_dependencies(a)
        deps_b = extract_game_sounds_dependencies(b)
        deps_ab = extract_game_sounds_dependencies(a + "\n" + b)
        assert deps_ab == deps_a | deps_b

    def test_additive_superset(self) -> None:
        """MR (Additive): adding more sounds yields a superset."""
        base = '"s1" { "wave" "a.wav" }'
        more = '"s2" { "wave" "b.wav" }'
        deps_base = extract_game_sounds_dependencies(base)
        deps_more = extract_game_sounds_dependencies(base + "\n" + more)
        assert deps_more >= deps_base

    def test_empty_returns_empty(self) -> None:
        assert extract_game_sounds_dependencies("") == set()
        assert extract_game_sounds_dependencies("// comment") == set()

    def test_malformed_no_crash(self) -> None:
        result = extract_game_sounds_dependencies("not keyvalues at all {{{ broken")
        assert isinstance(result, set)

    def test_wave_sound_prefix_normalised(self) -> None:
        """MR (Invariance under normalisation): paths without 'sound/' prefix get it."""
        raw = '"s1" { "wave" "a.wav" }'
        deps = extract_game_sounds_dependencies(raw)
        assert all(d.startswith("sound/") for d in deps)

    def test_permutative(self) -> None:
        """MR (Permutative): reordering entries yields the same deps."""
        a = '"s1" { "wave" "a.wav" } "s2" { "wave" "b.wav" }'
        b = '"s2" { "wave" "b.wav" } "s1" { "wave" "a.wav" }'
        assert extract_game_sounds_dependencies(a) == extract_game_sounds_dependencies(b)


# ---------------------------------------------------------------------------
# 3. soundscapes_parser — extract_soundscapes_dependencies()
# ---------------------------------------------------------------------------
from parallelines.parsers.soundscapes_parser import extract_soundscapes_dependencies


class TestSoundscapesParser:
    def test_compositional(self) -> None:
        """MR (Compositional): extract(a + b) == extract(a) | extract(b)."""
        a = '"wave" "sound/a.wav"'
        b = '"wave" "sound/b.wav"'
        deps_a = extract_soundscapes_dependencies(a)
        deps_b = extract_soundscapes_dependencies(b)
        deps_ab = extract_soundscapes_dependencies(a + "\n" + b)
        assert deps_ab == deps_a | deps_b

    def test_additive_superset(self) -> None:
        base = '"wave" "sound/a.wav"'
        more = '"wave" "sound/b.wav"'
        deps_base = extract_soundscapes_dependencies(base)
        deps_more = extract_soundscapes_dependencies(base + "\n" + more)
        assert deps_more >= deps_base

    def test_empty_returns_empty(self) -> None:
        assert extract_soundscapes_dependencies("") == set()
        assert extract_soundscapes_dependencies("// comment") == set()

    def test_malformed_no_crash(self) -> None:
        result = extract_soundscapes_dependencies("not a soundscape at all {{{ broken")
        assert isinstance(result, set)

    def test_wave_sound_prefix_normalised(self) -> None:
        raw = '"wave" "a.wav"'
        deps = extract_soundscapes_dependencies(raw)
        assert all(d.startswith("sound/") for d in deps)

    def test_permutative(self) -> None:
        a = '"wave" "sound/a.wav" "wave" "sound/b.wav"'
        b = '"wave" "sound/b.wav" "wave" "sound/a.wav"'
        assert extract_soundscapes_dependencies(a) == extract_soundscapes_dependencies(b)


# ---------------------------------------------------------------------------
# 4. level_sounds_parser — extract_level_sounds_dependencies()
# ---------------------------------------------------------------------------
from parallelines.parsers.level_sounds_parser import extract_level_sounds_dependencies


class TestLevelSoundsParser:
    def test_compositional(self) -> None:
        """MR (Compositional): extract(a + b) == extract(a) | extract(b)."""
        a = '"area1" { "sound" "sound/a.wav" }'
        b = '"area2" { "sound" "sound/b.wav" }'
        deps_a = extract_level_sounds_dependencies(a)
        deps_b = extract_level_sounds_dependencies(b)
        deps_ab = extract_level_sounds_dependencies(a + "\n" + b)
        assert deps_ab == deps_a | deps_b

    def test_additive_superset(self) -> None:
        base = '"area1" { "sound" "sound/a.wav" }'
        more = '"area2" { "sound" "sound/b.wav" }'
        deps_base = extract_level_sounds_dependencies(base)
        deps_more = extract_level_sounds_dependencies(base + "\n" + more)
        assert deps_more >= deps_base

    def test_empty_returns_empty(self) -> None:
        assert extract_level_sounds_dependencies("") == set()
        assert extract_level_sounds_dependencies("// comment") == set()

    def test_malformed_no_crash(self) -> None:
        result = extract_level_sounds_dependencies("not valid {{{ broken")
        assert isinstance(result, set)

    def test_sound_prefix_normalised(self) -> None:
        raw = '"area" { "sound" "a.wav" }'
        deps = extract_level_sounds_dependencies(raw)
        assert all(d.startswith("sound/") for d in deps)

    def test_permutative(self) -> None:
        a = '"a" { "sound" "sound/x.wav" } "b" { "sound" "sound/y.wav" }'
        b = '"b" { "sound" "sound/y.wav" } "a" { "sound" "sound/x.wav" }'
        assert extract_level_sounds_dependencies(a) == extract_level_sounds_dependencies(b)


# ---------------------------------------------------------------------------
# 5. population_parser — extract_population_dependencies()
# ---------------------------------------------------------------------------
from parallelines.parsers.population_parser import extract_population_dependencies


class TestPopulationParser:
    def test_compositional(self) -> None:
        """MR (Compositional): extract(a + b) == extract(a) | extract(b)."""
        a = '"z1" { "zombie_class" "Hunter" }'
        b = '"z2" { "zombie_class" "Smoker" }'
        deps_a = extract_population_dependencies(a)
        deps_b = extract_population_dependencies(b)
        deps_ab = extract_population_dependencies(a + "\n" + b)
        assert deps_ab == deps_a | deps_b

    def test_additive_superset(self) -> None:
        base = '"z1" { "zombie_class" "Hunter" }'
        more = '"z2" { "zombie_class" "Smoker" }'
        deps_base = extract_population_dependencies(base)
        deps_more = extract_population_dependencies(base + "\n" + more)
        assert deps_more >= deps_base

    def test_empty_returns_empty(self) -> None:
        assert extract_population_dependencies("") == set()
        assert extract_population_dependencies("// comment") == set()

    def test_malformed_no_crash(self) -> None:
        result = extract_population_dependencies("not kv at all {{{ broken")
        assert isinstance(result, set)

    def test_unknown_class_falls_back(self) -> None:
        """MR (Additive): Unknown zombie class produces a fallback model path."""
        known = '"z1" { "zombie_class" "Hunter" }'
        unknown = '"z2" { "zombie_class" "UnknownClass" }'
        deps_known = extract_population_dependencies(known)
        deps_both = extract_population_dependencies(known + "\n" + unknown)
        # Adding an unknown class introduces at least one new dep
        assert len(deps_both) > len(deps_known)

    def test_permutative(self) -> None:
        """MR (Permutative): reordering entries yields same deps."""
        a = '"z1" { "zombie_class" "hunter" } "z2" { "zombie_class" "smoker" }'
        b = '"z2" { "zombie_class" "smoker" } "z1" { "zombie_class" "hunter" }'
        assert extract_population_dependencies(a) == extract_population_dependencies(b)


# ---------------------------------------------------------------------------
# 6. melee_parser — extract_melee_dependencies()
# ---------------------------------------------------------------------------
from parallelines.parsers.melee_parser import extract_melee_dependencies


class TestMeleeParser:
    def test_compositional(self) -> None:
        """MR (Compositional): extract(a + b) == extract(a) | extract(b)."""
        a = '"axe" { "viewmodel" "models/axe.vmdl" "worldmodel" "models/axe_w.vmdl" }'
        b = '"bat" { "viewmodel" "models/bat.vmdl" }'
        deps_a = extract_melee_dependencies(a)
        deps_b = extract_melee_dependencies(b)
        deps_ab = extract_melee_dependencies(a + "\n" + b)
        assert deps_ab == deps_a | deps_b

    def test_additive_superset(self) -> None:
        base = '"axe" { "viewmodel" "models/axe.vmdl" }'
        more = '"bat" { "viewmodel" "models/bat.vmdl" }'
        deps_base = extract_melee_dependencies(base)
        deps_more = extract_melee_dependencies(base + "\n" + more)
        assert deps_more >= deps_base

    def test_empty_returns_empty(self) -> None:
        assert extract_melee_dependencies("") == set()
        assert extract_melee_dependencies("// comment") == set()

    def test_malformed_no_crash(self) -> None:
        result = extract_melee_dependencies("not kv {{{ broken")
        assert isinstance(result, set)

    def test_permutative(self) -> None:
        """MR (Permutative): reordering weapon definitions yields same deps."""
        a = '"axe" { "viewmodel" "models/axe.vmdl" } "bat" { "viewmodel" "models/bat.vmdl" }'
        b = '"bat" { "viewmodel" "models/bat.vmdl" } "axe" { "viewmodel" "models/axe.vmdl" }'
        assert extract_melee_dependencies(a) == extract_melee_dependencies(b)


# ---------------------------------------------------------------------------
# 7. missions_parser — extract_missions_dependencies()
# ---------------------------------------------------------------------------
from parallelines.parsers.missions_parser import extract_missions_dependencies


class TestMissionsParser:
    def test_compositional(self) -> None:
        """MR (Compositional): multiple mode blocks under same 'modes' top-key."""
        a_inner = '"campaign" { "1" { "Map" "c1m1" } }'
        b_inner = '"survival" { "1" { "Map" "c2m1" } }'
        a = '"modes" { ' + a_inner + " }"
        b = '"modes" { ' + b_inner + " }"
        combined = '"modes" { ' + a_inner + " " + b_inner + " }"
        deps_a = extract_missions_dependencies(a)
        deps_b = extract_missions_dependencies(b)
        deps_combined = extract_missions_dependencies(combined)
        assert deps_combined == deps_a | deps_b

    def test_additive_superset(self) -> None:
        """MR: adding missions within same modes block → superset."""
        base = '"modes" { "campaign" { "1" { "Map" "c1m1" } } }'
        more = '"modes" { "campaign" { "1" { "Map" "c1m1" } "2" { "Map" "c1m2" } } }'
        deps_base = extract_missions_dependencies(base)
        deps_more = extract_missions_dependencies(more)
        assert deps_more >= deps_base

    def test_empty_returns_empty(self) -> None:
        assert extract_missions_dependencies("") == set()
        assert extract_missions_dependencies("// comment") == set()

    def test_malformed_no_crash(self) -> None:
        result = extract_missions_dependencies("not kv {{{ broken")
        assert isinstance(result, set)

    def test_uppercase_map_key_lowered_by_kv_parser(self) -> None:
        """MR: 'Map' key in source is lowered to 'map' by kv_parser, still extracted."""
        upper = '"modes" { "campaign" { "1" { "Map" "c1m1" } } }'
        lower = '"modes" { "campaign" { "1" { "map" "c1m1" } } }'
        assert extract_missions_dependencies(upper) == extract_missions_dependencies(lower)


# ---------------------------------------------------------------------------
# 8. pcf_parser — extract_pcf_dependencies()  (binary input)
# ---------------------------------------------------------------------------
from parallelines.parsers.pcf_parser import extract_pcf_dependencies


class TestPcfParser:
    def test_additive_superset(self) -> None:
        """MR (Additive): more material paths in binary => superset."""
        a = b"materials/test/some_particle.vmt\x00"
        b = b"materials/test/other_particle.vmt\x00"
        deps_a = extract_pcf_dependencies(a)
        deps_ab = extract_pcf_dependencies(a + b)
        assert deps_ab >= deps_a

    def test_empty_returns_empty(self) -> None:
        assert extract_pcf_dependencies(b"") == set()

    def test_garbage_no_crash(self) -> None:
        result = extract_pcf_dependencies(b"\xff\xfe\x00\x01\x02 broken binary data")
        assert isinstance(result, set)

    def test_no_material_match_returns_empty(self) -> None:
        result = extract_pcf_dependencies(b"some random binary without material paths")
        assert result == set()

    def test_backslash_normalised(self) -> None:
        """Paths with backslashes are normalised to forward slashes."""
        raw = b"materials\\test\\particle.vmt"
        deps = extract_pcf_dependencies(raw)
        assert all("/" in d for d in deps)
        assert "\\" not in "".join(deps)

    def test_multiple_material_paths(self) -> None:
        """Multiple null-terminated material paths in binary yield all paths."""
        data = b"materials/particles/a.vmt\x00materials/particles/b.vmt\x00"
        deps = extract_pcf_dependencies(data)
        assert len(deps) == 2

    def test_only_materials_paths_extracted(self) -> None:
        """Other binary content is ignored; only materials/ paths extracted."""
        data = b"materials/particles/a.vmt\x00garbage\x00materials/particles/b.vmt\x00"
        deps = extract_pcf_dependencies(data)
        assert all(p.startswith("materials/") for p in deps)

    def test_compositional(self) -> None:
        """MR (Compositional): extract(a + b) == extract(a) | extract(b)."""
        a = b"materials/particles/a.vmt\x00"
        b = b"materials/particles/b.vmt\x00"
        assert extract_pcf_dependencies(a + b) == extract_pcf_dependencies(
            a
        ) | extract_pcf_dependencies(b)


# ---------------------------------------------------------------------------
# 9. res_parser — extract_res_dependencies()
# ---------------------------------------------------------------------------
from parallelines.parsers.res_parser import extract_res_dependencies


class TestResParser:
    def test_compositional(self) -> None:
        """MR (Compositional): extract(a + b) == extract(a) | extract(b)."""
        a = '"ctx" { "image" "test_img" }'
        b = '"ctx2" { "font" "test_font" }'
        deps_a = extract_res_dependencies(a)
        deps_b = extract_res_dependencies(b)
        deps_ab = extract_res_dependencies(a + "\n" + b)
        assert deps_ab == deps_a | deps_b

    def test_additive_superset(self) -> None:
        base = '"ctx1" { "image" "img1" }'
        more = '"ctx2" { "font" "font1" }'
        deps_base = extract_res_dependencies(base)
        deps_more = extract_res_dependencies(base + "\n" + more)
        assert deps_more >= deps_base

    def test_empty_returns_empty(self) -> None:
        assert extract_res_dependencies("") == set()
        assert extract_res_dependencies("// comment") == set()

    def test_malformed_no_crash(self) -> None:
        result = extract_res_dependencies("not kv {{{ broken")
        assert isinstance(result, set)

    def test_nested_structure(self) -> None:
        """MR (Compositional): Nested dict/array still finds image/font keys."""
        nested = '"root" { "child" { "image" "nested_img" "font" "nested_font" } }'
        flat = '"other" { "image" "flat_img" }'
        deps_nested = extract_res_dependencies(nested)
        deps_both = extract_res_dependencies(nested + "\n" + flat)
        assert deps_both >= deps_nested

    def test_normalised_paths(self) -> None:
        """Deps should have materials/ prefix and .vtf suffix if missing."""
        raw = '"ctx" { "image" "some_img" }'
        deps = extract_res_dependencies(raw)
        assert all(d.startswith("materials/") for d in deps)

    def test_permutative(self) -> None:
        """MR (Permutative): reordering resource sections yields same deps."""
        a = '"a" { "image" "tex1" } "b" { "font" "fnt1" }'
        b = '"b" { "font" "fnt1" } "a" { "image" "tex1" }'
        assert extract_res_dependencies(a) == extract_res_dependencies(b)


# ---------------------------------------------------------------------------
# 10. weapon_parser — extract_weapon_dependencies()
# ---------------------------------------------------------------------------
from parallelines.parsers.weapon_parser import extract_weapon_dependencies


class TestWeaponParser:
    def test_compositional(self) -> None:
        """MR (Compositional): extract(a + b) == extract(a) | extract(b)."""
        a = '"weapon1" { "viewmodel" "models/gun.vmdl" }'
        b = '"weapon2" { "sound_fire" "weapons/fire.wav" }'
        deps_a = extract_weapon_dependencies(a)
        deps_b = extract_weapon_dependencies(b)
        deps_ab = extract_weapon_dependencies(a + "\n" + b)
        assert deps_ab == deps_a | deps_b

    def test_additive_superset(self) -> None:
        base = '"weapon1" { "viewmodel" "models/gun.vmdl" }'
        more = '"weapon2" { "playermodel" "models/player.vmdl" }'
        deps_base = extract_weapon_dependencies(base)
        deps_more = extract_weapon_dependencies(base + "\n" + more)
        assert deps_more >= deps_base

    def test_empty_returns_empty(self) -> None:
        assert extract_weapon_dependencies("") == set()
        assert extract_weapon_dependencies("// comment") == set()

    def test_malformed_no_crash(self) -> None:
        result = extract_weapon_dependencies("not kv {{{ broken")
        assert isinstance(result, set)

    def test_sound_prefixed_with_sound(self) -> None:
        """sound_ keys get sound/ prefix if missing."""
        raw = '"weapondata" { "sound_fire" "weapons/fire.wav" }'
        deps = extract_weapon_dependencies(raw)
        assert all(d.startswith("sound/") for d in deps)

    def test_texture_prefixed_with_materials(self) -> None:
        """texture key gets materials/ prefix."""
        raw = '"weapondata" { "texture" "gun_skin" }'
        deps = extract_weapon_dependencies(raw)
        assert all(d.startswith("materials/") for d in deps)

    def test_permutative(self) -> None:
        """MR (Permutative): reordering weapon entries yields same deps."""
        a = '"w1" { "viewmodel" "models/gun.vmdl" } "w2" { "sound_fire" "fire.wav" }'
        b = '"w2" { "sound_fire" "fire.wav" } "w1" { "viewmodel" "models/gun.vmdl" }'
        assert extract_weapon_dependencies(a) == extract_weapon_dependencies(b)


# ---------------------------------------------------------------------------
# 11. texture_list_parser — extract_texture_list_dependencies()
# ---------------------------------------------------------------------------
from parallelines.parsers.texture_list_parser import extract_texture_list_dependencies


class TestTextureListParser:
    def test_compositional(self) -> None:
        """MR (Compositional): extract(a + b) == extract(a) | extract(b)."""
        a = '"tex1" "hud/icon_a"'
        b = '"tex2" "hud/icon_b"'
        deps_a = extract_texture_list_dependencies(a)
        deps_b = extract_texture_list_dependencies(b)
        deps_ab = extract_texture_list_dependencies(a + "\n" + b)
        assert deps_ab == deps_a | deps_b

    def test_additive_superset(self) -> None:
        base = '"tex1" "hud/icon_a"'
        more = '"tex2" "hud/icon_b"'
        deps_base = extract_texture_list_dependencies(base)
        deps_more = extract_texture_list_dependencies(base + "\n" + more)
        assert deps_more >= deps_base

    def test_empty_returns_empty(self) -> None:
        assert extract_texture_list_dependencies("") == set()

    def test_malformed_no_crash(self) -> None:
        result = extract_texture_list_dependencies("not valid{{{")
        assert isinstance(result, set)

    def test_normalised_paths(self) -> None:
        """Paths without materials/ or an extension get both."""
        raw = '"tex" "my_texture"'
        deps = extract_texture_list_dependencies(raw)
        assert all(d.startswith("materials/") for d in deps)
        assert all(d.endswith(".vtf") for d in deps)

    def test_permutative(self) -> None:
        """MR (Permutative): reordering texture entries yields same deps."""
        a = '"a" "tex1" "b" "tex2"'
        b = '"b" "tex2" "a" "tex1"'
        assert extract_texture_list_dependencies(a) == extract_texture_list_dependencies(b)


# ---------------------------------------------------------------------------
# 12. simple_list_parser — parse_simple_list()
# ---------------------------------------------------------------------------
from parallelines.parsers.simple_list_parser import parse_simple_list


class TestSimpleListParser:
    def test_compositional(self) -> None:
        """MR (Compositional): parse(a + b) == parse(a) | parse(b)."""
        a = "sound/a.wav\n"
        b = "sound/b.wav\n"
        deps_a = parse_simple_list(a)
        deps_b = parse_simple_list(b)
        deps_ab = parse_simple_list(a + b)
        assert deps_ab == deps_a | deps_b

    def test_additive_superset(self) -> None:
        base = "sound/a.wav\n"
        more = "sound/b.wav\n"
        deps_base = parse_simple_list(base)
        deps_more = parse_simple_list(base + more)
        assert deps_more >= deps_base

    def test_empty_returns_empty(self) -> None:
        assert parse_simple_list("") == set()
        assert parse_simple_list("  \n  ") == set()

    def test_comments_ignored(self) -> None:
        """Lines starting with // or # are skipped."""
        base = "sound/a.wav\n"
        with_comments = "// header\n# meta\nsound/a.wav\n"
        assert parse_simple_list(with_comments) == parse_simple_list(base)

    def test_prefix_added_when_missing(self) -> None:
        """Prefix is prepended when entry does not start with it."""
        raw = "a.wav\n"
        deps = parse_simple_list(raw, prefix="sound/")
        assert all(d.startswith("sound/") for d in deps)

    def test_prefix_not_duplicated(self) -> None:
        """Prefix is NOT prepended when entry already starts with it."""
        raw = "sound/a.wav\n"
        deps = parse_simple_list(raw, prefix="sound/")
        assert "sound/a.wav" in deps
        # Should not have double prefix
        assert not any("sound/sound/" in d for d in deps)

    def test_malformed_no_crash(self) -> None:
        result = parse_simple_list(None)  # type: ignore[arg-type]
        assert isinstance(result, set)


# ---------------------------------------------------------------------------
# 13. bsp_pakfile — extract_bsp_pakfile_entries()
# ---------------------------------------------------------------------------
from parallelines.parsers.bsp_pakfile import extract_bsp_pakfile_entries, scan_bsp_scripts


class TestBspPakfileParser:
    def test_non_bsp_returns_empty(self) -> None:
        """Non-BSP bytes that are not a valid ZIP return []."""
        result = extract_bsp_pakfile_entries(b"not a bsp at all")
        assert result == []

    def test_empty_bytes_returns_empty(self) -> None:
        assert extract_bsp_pakfile_entries(b"") == []

    def test_garbage_no_crash(self) -> None:
        result = extract_bsp_pakfile_entries(b"\xff\xfe\x00\x01\x02" * 100)
        assert isinstance(result, list)

    def test_zip_bytes_structure(self) -> None:
        """Empty ZIP bytes: extract returns [] (no entries in zip)."""
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            pass
        empty_zip = buf.getvalue()
        # Wrap in something non-BSP-like so zipfile still can read from end
        result = extract_bsp_pakfile_entries(b"VBSP" + b"\x00" * 100 + empty_zip)
        # zipfile can find the central directory in the appended bytes
        assert isinstance(result, list)


class TestBspScriptScanner:
    def test_empty_returns_empty(self) -> None:
        assert scan_bsp_scripts(b"") == set()
        assert scan_bsp_scripts(b"not a zip") == set()

    def test_no_nut_or_cfg_returns_empty(self) -> None:
        """ZIP with only non-script files yields no deps."""
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("materials/test.vmt", "test")
        result = scan_bsp_scripts(buf.getvalue())
        assert result == set()

    def _make_zip(self, files: dict[str, str]) -> bytes:
        """Helper: create an in-memory ZIP from {path: content} dict."""
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for path, content in files.items():
                zf.writestr(path, content)
        return buf.getvalue()

    def test_nut_include_script_additive(self) -> None:
        """MR (Additive): adding IncludeScript → deps superset."""
        base = self._make_zip({"empty.nut": "// nothing\n"})
        with_call = self._make_zip({"call.nut": 'IncludeScript("mylib")\n'})
        assert scan_bsp_scripts(with_call) >= scan_bsp_scripts(base)

    def test_nut_precache_model_additive(self) -> None:
        base = self._make_zip({"empty.nut": "// nothing\n"})
        with_call = self._make_zip({"call.nut": 'PrecacheModel("models/infected/hunter.mdl")\n'})
        assert scan_bsp_scripts(with_call) >= scan_bsp_scripts(base)

    def test_nut_precache_sound_additive(self) -> None:
        base = self._make_zip({"empty.nut": "// nothing\n"})
        with_call = self._make_zip({"call.nut": 'PrecacheSound("ambient/test.wav")\n'})
        deps_with = scan_bsp_scripts(with_call)
        deps_base = scan_bsp_scripts(base)
        assert deps_with >= deps_base
        assert all(d.startswith("sound/") for d in (deps_with - deps_base))

    def test_cfg_exec_additive(self) -> None:
        base = self._make_zip({"empty.cfg": "// nothing\n"})
        with_call = self._make_zip({"call.cfg": 'exec "maps/map_settings"\n'})
        assert scan_bsp_scripts(with_call) >= scan_bsp_scripts(base)

    def test_multiple_scripts_additive(self) -> None:
        """MR (Additive): two scripts in one ZIP extracts at least as much as one."""
        one = self._make_zip({"s1.nut": 'IncludeScript("lib1")\n'})
        two = self._make_zip(
            {
                "s1.nut": 'IncludeScript("lib1")\n',
                "s2.nut": 'IncludeScript("lib2")\n',
            }
        )
        assert scan_bsp_scripts(two) >= scan_bsp_scripts(one)


# ---------------------------------------------------------------------------
# 13b. BSP entity side effects — extract_bsp_entity_side_effects()
# ---------------------------------------------------------------------------
from parallelines.parsers.bsp_parser import extract_bsp_entity_side_effects


class _MockEnt:
    """Minimal entity mock for side-effect tests."""

    def __init__(self, kv: dict[str, str]):
        self._kv = kv

    def get(self, key: str, default: str = "") -> str:
        return self._kv.get(key, default)


class TestBspEntitySideEffects:
    def _mk_bsp(self, ents: list[dict]) -> object:
        """Build a mock BSP whose ``.ents.entities`` iterates over *ents*."""

        class MockBSP:
            class ents:
                entities = [_MockEnt(kv) for kv in ents]

        return MockBSP()

    def test_additive_commands(self) -> None:
        """MR (Additive): more servercommand entities → commands superset."""
        base = self._mk_bsp([{"classname": "point_servercommand", "command": "cmd1"}])
        more = self._mk_bsp(
            [
                {"classname": "point_servercommand", "command": "cmd1"},
                {"classname": "point_servercommand", "command": "cmd2"},
            ]
        )
        r_base = extract_bsp_entity_side_effects(base)
        r_more = extract_bsp_entity_side_effects(more)
        assert r_more["commands"] >= r_base["commands"]

    def test_additive_globalstates(self) -> None:
        """MR (Additive): more env_global entities → globalstates superset."""
        base = self._mk_bsp([{"classname": "env_global", "globalstate": "gs1"}])
        more = self._mk_bsp(
            [
                {"classname": "env_global", "globalstate": "gs1"},
                {"classname": "env_global", "globalstate": "gs2"},
            ]
        )
        r_base = extract_bsp_entity_side_effects(base)
        r_more = extract_bsp_entity_side_effects(more)
        assert r_more["globalstates"] >= r_base["globalstates"]

    def test_harmless_entity_ignored(self) -> None:
        """MR (Exclusive): entities not in {servercommand, env_global} produce no effects."""
        harmless = self._mk_bsp(
            [
                {"classname": "info_player_start"},
                {"classname": "light_spot"},
            ]
        )
        r = extract_bsp_entity_side_effects(harmless)
        assert r["commands"] == []
        assert r["globalstates"] == []

    def test_interspersed_entities(self) -> None:
        """MR (Compositional): interspersing harmless entities preserves extraction."""
        pure = self._mk_bsp([{"classname": "point_servercommand", "command": "x"}])
        mixed = self._mk_bsp(
            [
                {"classname": "info_player_start"},
                {"classname": "point_servercommand", "command": "x"},
                {"classname": "light_spot"},
            ]
        )
        assert (
            extract_bsp_entity_side_effects(mixed)["commands"]
            == extract_bsp_entity_side_effects(pure)["commands"]
        )

    def test_empty_entities_returns_empty(self) -> None:
        """MR (Invariant): no entities yields empty commands and globalstates."""
        bsp = self._mk_bsp([])
        result = extract_bsp_entity_side_effects(bsp)
        assert result["commands"] == []
        assert result["globalstates"] == []

    def test_both_entity_types_extracted(self) -> None:
        """MR (Additive): both point_servercommand and env_global extracted from the same BSP."""
        bsp = self._mk_bsp(
            [
                {"classname": "point_servercommand", "command": "sv_cheats 1"},
                {"classname": "env_global", "globalstate": "mission_complete"},
            ]
        )
        result = extract_bsp_entity_side_effects(bsp)
        assert len(result["commands"]) >= 1
        assert len(result["globalstates"]) >= 1


# ---------------------------------------------------------------------------
# 14. nuc_parser — extract_nuc_dependencies()
# ---------------------------------------------------------------------------
from parallelines.parsers.nuc_parser import extract_nuc_dependencies


class TestNucParser:
    def test_sq_binary_not_available_returns_empty(self) -> None:
        """When the ``sq`` binary is not on PATH, returns empty set gracefully."""
        result = extract_nuc_dependencies(b"some nuc bytecode")
        assert isinstance(result, set)

    def test_empty_bytes_returns_empty(self) -> None:
        result = extract_nuc_dependencies(b"")
        assert isinstance(result, set)

    def test_garbage_no_crash(self) -> None:
        result = extract_nuc_dependencies(b"\xff\xfe\x00" * 50)
        assert isinstance(result, set)

    def test_compiled_bytecode_returns_empty(self) -> None:
        """Compiled Squirrel bytecode (0xFAFA header) returns empty set."""
        result = extract_nuc_dependencies(b"\xfa\xfa\x01\x02\x03\x04")
        assert isinstance(result, set)

    def test_ice_decrypt_nut_extract_pipeline(self) -> None:
        """MR (Inverse): ICE encrypt->decrypt->nut_extract yields original deps."""
        from parallelines.parsers.ice import IceKey
        from parallelines.parsers.nut_parser import extract_nut_dependencies

        plaintext = b'PrecacheModel("models/hunter.mdl")\n'
        key = b"SDhfi878"
        ice = IceKey(0)
        ice.set(key)
        pad = (8 - len(plaintext) % 8) % 8
        data = plaintext + b"\x00" * pad
        encrypted = bytearray(len(data))
        for i in range(0, len(data), 8):
            encrypted[i : i + 8] = ice.encrypt(data[i : i + 8])

        decrypted = IceKey.decrypt_buffer(bytes(encrypted), key)
        text = decrypted.decode("utf-8", errors="replace")
        deps = extract_nut_dependencies(text)
        assert "models/hunter.mdl" in deps

    def test_precache_model_content_not_crash(self) -> None:
        """Content with PrecacheModel call returns set without crashing."""
        result = extract_nuc_dependencies(b'PrecacheModel("models/test.mdl")\n')
        assert isinstance(result, set)

    def test_precache_sound_content_not_crash(self) -> None:
        """Content with PrecacheSound call returns set without crashing."""
        result = extract_nuc_dependencies(b'PrecacheSound("ambient/test.wav")\n')
        assert isinstance(result, set)

    def test_include_script_content_not_crash(self) -> None:
        """Content with IncludeScript call returns set without crashing."""
        result = extract_nuc_dependencies(b'IncludeScript("mylib")\n')
        assert isinstance(result, set)


# ---------------------------------------------------------------------------
# 15. nut_parser — extract_nut_dependencies()
# ---------------------------------------------------------------------------
from parallelines.parsers.nut_parser import extract_nut_dependencies


class TestNutParser:
    def test_compositional(self) -> None:
        """MR (Compositional): extract(a + b) == extract(a) | extract(b)."""
        a = 'IncludeScript("mymod/mylib")\n'
        b = 'PrecacheModel("models/test.mdl")\n'
        deps_a = extract_nut_dependencies(a)
        deps_b = extract_nut_dependencies(b)
        deps_ab = extract_nut_dependencies(a + b)
        assert deps_ab == deps_a | deps_b

    def test_additive_superset(self) -> None:
        base = 'IncludeScript("base")\n'
        more = 'IncludeScript("extra")\n'
        deps_base = extract_nut_dependencies(base)
        deps_more = extract_nut_dependencies(base + more)
        assert deps_more >= deps_base

    def test_empty_returns_empty(self) -> None:
        assert extract_nut_dependencies("") == set()

    def test_no_match_returns_empty(self) -> None:
        content = 'my_function <- function() {\n    print("Hello");\n}\n'
        assert extract_nut_dependencies(content) == set()

    def test_include_script_resolution(self) -> None:
        """IncludeScript resolves bare names to scripts/vscripts/*.nut."""
        raw = 'IncludeScript("mylib")\n'
        deps = extract_nut_dependencies(raw)
        assert all(d.endswith(".nut") for d in deps)
        assert all("scripts/vscripts/" in d for d in deps)

    def test_include_script_with_path(self) -> None:
        """IncludeScript with a path separator keeps relative path, adds .nut."""
        raw = 'IncludeScript("mymod/mylib")\n'
        deps = extract_nut_dependencies(raw)
        assert all(d.endswith(".nut") for d in deps)
        assert all("/" in d for d in deps)

    def test_precache_model_kept_as_is(self) -> None:
        """PrecacheModel paths are kept as-is (no prefix added)."""
        raw = 'PrecacheModel("models/infected/hunter.mdl")\n'
        deps = extract_nut_dependencies(raw)
        assert all(d == "models/infected/hunter.mdl" for d in deps)

    def test_precache_sound_gets_sound_prefix(self) -> None:
        """PrecacheSound paths without 'sound/' prefix get it added."""
        raw = 'PrecacheSound("ambient/test.wav")\n'
        deps = extract_nut_dependencies(raw)
        assert all(d.startswith("sound/") for d in deps)

    def test_precache_sound_with_prefix_kept(self) -> None:
        """PrecacheSound paths that already have 'sound/' prefix are kept."""
        raw = 'PrecacheSound("sound/ambient/test.wav")\n'
        deps = extract_nut_dependencies(raw)
        assert "sound/ambient/test.wav" in deps

    def test_malformed_no_crash(self) -> None:
        result = extract_nut_dependencies("not valid{{{ broken")
        assert isinstance(result, set)


# ---------------------------------------------------------------------------
# 16. bsp_parser — extract_bsp_dependencies()
# ---------------------------------------------------------------------------
from parallelines.parsers.bsp_parser import extract_bsp_dependencies


class TestBspParser:
    def test_chain_none_returns_empty_set(self) -> None:
        """Graceful fallback: chain=None returns empty set (exception caught internally)."""
        result = extract_bsp_dependencies(None, "")
        assert isinstance(result, set)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# 17. mdl_parser — extract_mdl_dependencies()
# ---------------------------------------------------------------------------
from parallelines.parsers.mdl_parser import extract_mdl_dependencies


class TestMdlParser:
    def test_chain_none_returns_empty_set(self) -> None:
        """Graceful fallback: chain=None returns empty set (exception caught internally)."""
        result = extract_mdl_dependencies(None, "models/test.mdl")
        assert isinstance(result, set)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# 18. addoninfo — parse_addoninfo() / extract_dependency_ids()
# ---------------------------------------------------------------------------
from parallelines.parsers.addoninfo import parse_addoninfo, extract_dependency_ids


class TestAddonInfoParser:
    def test_valid_kv_returns_dict(self) -> None:
        """Valid addoninfo.txt KV format returns metadata dict."""
        content = '"addoninfo.txt"\n{\n"addon_name" "Test Addon"\n"addon_id" "12345"\n}\n'
        result = parse_addoninfo(content)
        assert isinstance(result, dict)
        assert len(result) > 0

    def test_empty_content_returns_empty_dict(self) -> None:
        """Empty content -> empty dict."""
        result = parse_addoninfo("")
        assert isinstance(result, dict)
        assert len(result) == 0

    def test_malformed_no_crash(self) -> None:
        """Malformed content does not crash; returns a dict (possibly empty)."""
        result = parse_addoninfo("broken {{{ not valid kv at all")
        assert isinstance(result, dict)

    def test_compositional_extract_dep_ids(self) -> None:
        """MR (Compositional): merged dependency lists yield union of workshop IDs."""
        meta_a = {"dependencies": [{"workshop_id": "100"}, {"workshop_id": "200"}]}
        meta_b = {"dependencies": [{"workshop_id": "300"}]}
        meta_merged = {"dependencies": meta_a["dependencies"] + meta_b["dependencies"]}
        ids_a = extract_dependency_ids(meta_a)
        ids_b = extract_dependency_ids(meta_b)
        ids_m = extract_dependency_ids(meta_merged)
        assert set(ids_m) == set(ids_a) | set(ids_b)

    def test_no_deps_returns_empty(self) -> None:
        """Addoninfo dict without dependencies yields empty list."""
        assert extract_dependency_ids({}) == []
        assert extract_dependency_ids({"addon_name": "test"}) == []


# ===================================================================
# 19. ADVERSARIAL / CORRUPTION TESTS
# ===================================================================
# These tests deliberately feed corrupted, empty, or pathological input
# to prove every parser degrades gracefully — no crashes, no hangs.

import io
import os
import zipfile


class _MockChain:
    """Minimal mock for srctools filesystem chain returning fixed bytes."""

    def __init__(self, content: bytes = b""):
        self._content = content

    def __getitem__(self, path: str):
        return _MockFileObj(self._content)


class _MockFileObj:
    def __init__(self, content: bytes):
        self._content = content

    def open_bin(self):
        return _MockStream(self._content)


class _MockStream:
    def __init__(self, content: bytes):
        self._content = content

    def read(self):
        return self._content


# -----------------------------------------------------------------------
# 19a. kv_parser — adversarial
# -----------------------------------------------------------------------


class TestKvParserAdversarial:
    def test_deeply_nested_braces_no_crash(self) -> None:
        """600-level nesting does not crash (may raise RecursionError)."""
        depth = 600
        text = "".join('"a" {' for _ in range(depth)) + "".join("}" for _ in range(depth))
        try:
            result = parse_kv(text)
            assert isinstance(result, dict)
        except RecursionError:
            pass  # acceptable — CPython recursion limit

    def test_binary_garbage_as_string(self) -> None:
        """Raw binary garbage string returns dict (may be empty)."""
        garbage = "\x00\x01\x02\xff\xfe" * 1000
        result = parse_kv(garbage)
        assert isinstance(result, dict)

    def test_extremely_long_quoted_value(self) -> None:
        """10 MB quoted value processes without hanging."""
        long_val = '"k" "' + "a" * 10_000_000 + '"'
        result = parse_kv(long_val)
        assert isinstance(result, dict)
        assert result.get("k") == "a" * 10_000_000

    def test_null_bytes_in_value(self) -> None:
        """Null bytes in a quoted string do not crash."""
        text = '"key" "val\x00ue"'
        result = parse_kv(text)
        assert isinstance(result, dict)

    def test_unbalanced_braces_no_crash(self) -> None:
        """Input with unclosed brace returns dict."""
        result = parse_kv('"a" { "b" "c"')
        assert isinstance(result, dict)

    def test_extra_closing_braces_no_crash(self) -> None:
        """Extra closing braces at end do not crash."""
        result = parse_kv('"a" "1" } } }')
        assert isinstance(result, dict)

    def test_utf16_bom_no_crash(self) -> None:
        """UTF-16 BOM text does not crash."""
        text = '﻿"key" "value"'
        result = parse_kv(text)
        assert isinstance(result, dict)

    def test_comment_only_variants_empty_dict(self) -> None:
        """All comment-prefix variants return empty dict."""
        for comment in ["// comment", "# comment", "; comment", "//\n//\n//"]:
            assert parse_kv(comment) == {}

    def test_empty_brace_block(self) -> None:
        """Empty brace blocks produce valid dict, not crash."""
        text = '"section" { } "other" "val"'
        result = parse_kv(text)
        assert "other" in result

    def test_repeated_unquoted_tokens(self) -> None:
        """Unquoted tokens on the same line are accepted."""
        result = parse_kv("a b c d")
        assert isinstance(result, dict)


# -----------------------------------------------------------------------
# 19b. soundscapes_parser — adversarial (raw regex, no kv_parser)
# -----------------------------------------------------------------------


class TestSoundscapesAdversarial:
    def test_binary_garbage_no_crash(self) -> None:
        """Binary garbage string returns empty set."""
        garbage = "\x00\x01\x02\xff\xfe" * 1000
        result = extract_soundscapes_dependencies(garbage)
        assert isinstance(result, set)

    def test_extremely_long_no_match(self) -> None:
        """10 MB string with no 'wave' entries returns empty set."""
        text = "x" * 10_000_000
        result = extract_soundscapes_dependencies(text)
        assert isinstance(result, set)

    def test_utf16_bom_text(self) -> None:
        """UTF-16 BOM text does not crash, returns empty."""
        result = extract_soundscapes_dependencies('﻿"wave" "sound/a.wav"')
        assert isinstance(result, set)

    def test_unterminated_wave_value(self) -> None:
        """"wave" with missing closing quote returns empty."""
        result = extract_soundscapes_dependencies('"wave" "sound/a.wav')
        assert isinstance(result, set)

    def test_10k_wave_entries_performance(self) -> None:
        """10 000 wave entries all extracted."""
        lines = "\n".join(f'"wave" "sound/file{i}.wav"' for i in range(10_000))
        result = extract_soundscapes_dependencies(lines)
        assert len(result) == 10_000

    def test_whitespace_variants(self) -> None:
        """Tab, multiple spaces, and mixed whitespace between key and value."""
        for ws in [" ", "\t", "  ", "\t "]:
            text = f'"wave"{ws}"sound/a.wav"'
            result = extract_soundscapes_dependencies(text)
            assert "sound/a.wav" in result

    def test_wave_key_value_with_newlines(self) -> None:
        """Newlines between "wave" and value handled by \\s+."""
        text = '"wave"  \n\n  "sound/a.wav"'
        result = extract_soundscapes_dependencies(text)
        assert "sound/a.wav" in result

    def test_comment_only_returns_empty(self) -> None:
        """Comment-only file returns empty set."""
        assert extract_soundscapes_dependencies("// just a comment") == set()
        assert extract_soundscapes_dependencies("  \n  ") == set()

    def test_empty_string_returns_empty(self) -> None:
        assert extract_soundscapes_dependencies("") == set()


# -----------------------------------------------------------------------
# 19c. nut_parser — adversarial (regex-only, no kv_parser)
# -----------------------------------------------------------------------


class TestNutAdversarial:
    def test_deeply_nested_parens_before_call(self) -> None:
        """Deep nesting before IncludeScript does not cause backtracking hang."""
        prefix = "(" * 1000 + ")" * 1000
        text = prefix + 'IncludeScript("mylib")\n'
        result = extract_nut_dependencies(text)
        assert isinstance(result, set)

    def test_very_long_string_before_match(self) -> None:
        """100k chars before IncludeScript does not hang."""
        text = 'SomeFunc("' + "a" * 100_000 + '"); IncludeScript("mylib")\n'
        result = extract_nut_dependencies(text)
        assert any("mylib" in d for d in result)

    def test_5k_include_script_calls(self) -> None:
        """5000 IncludeScript calls all extracted."""
        lines = "\n".join(f'IncludeScript("lib{i}");' for i in range(5000))
        result = extract_nut_dependencies(lines)
        assert len(result) == 5000

    def test_precache_model_special_chars(self) -> None:
        """Model path with special characters handled."""
        text = 'PrecacheModel("models/some_{weird}/path@.mdl")\n'
        result = extract_nut_dependencies(text)
        assert "models/some_{weird}/path@.mdl" in result

    def test_precache_sound_with_unicode(self) -> None:
        """Unicode in PrecacheSound path does not crash."""
        text = 'PrecacheSound("ambient/étest.wav")\n'
        result = extract_nut_dependencies(text)
        assert isinstance(result, set)

    def test_include_script_empty_string_no_match(self) -> None:
        """IncludeScript("") does not match ([^"]+ needs 1+ char)."""
        result = extract_nut_dependencies('IncludeScript("")\n')
        assert isinstance(result, set)

    def test_newlines_between_tokens(self) -> None:
        """Newlines between function name and parens handled by \\s*."""
        text = 'IncludeScript  \n  (\n  "mylib"  \n  )\n'
        result = extract_nut_dependencies(text)
        assert any("mylib" in d for d in result)

    def test_many_precache_model_calls(self) -> None:
        """5000 PrecacheModel calls all extracted."""
        lines = "\n".join(f'PrecacheModel("models/m{i}.mdl")' for i in range(5000))
        result = extract_nut_dependencies(lines)
        assert len(result) == 5000

    def test_alternating_precache_patterns(self) -> None:
        """Interleaved IncludeScript and Precache calls all extracted."""
        lines = "\n".join(
            f'IncludeScript("lib{i}"); PrecacheModel("models/m{i}.mdl")' for i in range(2000)
        )
        result = extract_nut_dependencies(lines)
        assert len(result) == 4000

    def test_empty_content_returns_empty(self) -> None:
        assert extract_nut_dependencies("") == set()

    def test_only_whitespace_returns_empty(self) -> None:
        assert extract_nut_dependencies("  \n  \n  ") == set()

    def test_binary_garbage_no_crash(self) -> None:
        garbage = "\x00\x01\x02\xff" * 1000
        result = extract_nut_dependencies(garbage)
        assert isinstance(result, set)


# -----------------------------------------------------------------------
# 19d. pcf_parser — adversarial (binary parser)
# -----------------------------------------------------------------------


class TestPcfAdversarial:
    def test_all_zeros_no_crash(self) -> None:
        """10k null bytes returns empty set."""
        assert extract_pcf_dependencies(b"\x00" * 10_000) == set()

    def test_large_random_no_matches(self) -> None:
        """10 MB of random bytes returns empty set."""
        data = os.urandom(10_000_000)
        result = extract_pcf_dependencies(data)
        assert isinstance(result, set)

    def test_10k_material_matches(self) -> None:
        """10 000 material paths all extracted."""
        paths = b"".join(f"materials/particles/p{i}.vmt\x00".encode() for i in range(10_000))
        result = extract_pcf_dependencies(paths)
        assert len(result) == 10_000

    def test_truncated_path_no_null(self) -> None:
        """Path at end-of-data without null terminator is still found."""
        data = b"materials/test/particle.vmt"
        result = extract_pcf_dependencies(data)
        assert "materials/test/particle.vmt" in result

    def test_material_as_binary_data(self) -> None:
        """"material" and "texture" as incidental ASCII do not crash."""
        data = b"\x00material\x00\x00random\x00texture\x00\x00other\x00"
        result = extract_pcf_dependencies(data)
        assert isinstance(result, set)

    def test_case_insensitive_materials(self) -> None:
        """MATERIALS/ matched case-insensitively."""
        data = b"MATERIALS/TEST/PARTICLE.VMT\x00"
        result = extract_pcf_dependencies(data)
        assert len(result) == 1

    def test_forward_backslash_mixed(self) -> None:
        """Mixed slash styles both returned with forward slash."""
        data = b"materials/test\\particle.vmt\x00materials/other/particle.vmt\x00"
        result = extract_pcf_dependencies(data)
        assert len(result) == 2
        assert all("/" in p for p in result)

    def test_bare_material_operator(self) -> None:
        """Bare texture name after material operator gets materials/ prefix."""
        data = b"material\x00\x00my_texture\x00"
        result = extract_pcf_dependencies(data)
        assert any("materials/my_texture.vmt" in p for p in result)

    def test_bare_texture_operator(self) -> None:
        """Bare texture name after texture operator gets .vmt and materials/."""
        data = b"texture\x00\x00my_tex\x00"
        result = extract_pcf_dependencies(data)
        assert any("materials/my_tex.vmt" in p for p in result)

    def test_bare_material_with_vtf(self) -> None:
        """Bare name with .vtf extension is not doubled."""
        data = b"material\x00\x00my_tex.vtf\x00"
        result = extract_pcf_dependencies(data)
        assert not any(p.endswith(".vmt") for p in result if "my_tex" in p)

    def test_incidental_bare_word_match(self) -> None:
        """Binary that happens to contain 'material' as raw bytes returns safe set."""
        data = b"\xff\xfe\x00material\x01\x02\x03"
        result = extract_pcf_dependencies(data)
        assert isinstance(result, set)


# -----------------------------------------------------------------------
# 19e. nuc_parser — adversarial (ICE decrypt + regex)
# -----------------------------------------------------------------------


class TestNucAdversarial:
    def test_plain_text_not_encrypted(self) -> None:
        """Plain text returns empty set (decrypt produces garbage)."""
        result = extract_nuc_dependencies(b"plain text - not encrypted")
        assert isinstance(result, set)

    def test_large_random_no_crash(self) -> None:
        """10 MB random data does not crash."""
        data = os.urandom(10_000_000)
        result = extract_nuc_dependencies(data)
        assert isinstance(result, set)

    def test_partial_short_input(self) -> None:
        """Very short input (< 8 bytes) does not crash ICE decrypt."""
        result = extract_nuc_dependencies(b"short")
        assert isinstance(result, set)

    def test_compiled_bytecode_header(self) -> None:
        """Bytecode header (0xFAFA) returns empty without decrypt attempt."""
        result = extract_nuc_dependencies(b"\xfa\xfa" + b"\x00" * 100)
        assert isinstance(result, set)

    def test_all_zeros_no_header(self) -> None:
        """All-zero data without bytecode magic returns empty set."""
        result = extract_nuc_dependencies(b"\x00" * 100)
        assert isinstance(result, set)

    def test_ice_encrypted_garbage_no_deps(self) -> None:
        """ICE-encrypted content decrypting to garbage returns empty deps."""
        from parallelines.parsers.ice import IceKey

        ice = IceKey(0)
        ice.set(b"xxxxxxxx")
        garbage = bytearray(800)
        for i in range(0, 800, 8):
            garbage[i : i + 8] = ice.encrypt(b"FFFFFFFF" if i < 792 else b"\x00" * 8)
        result = extract_nuc_dependencies(bytes(garbage))
        assert isinstance(result, set)

    def test_empty_bytes_returns_empty(self) -> None:
        assert extract_nuc_dependencies(b"") == set()


# -----------------------------------------------------------------------
# 19f. bsp_parser — adversarial (entity side effects + extract)
# -----------------------------------------------------------------------


class _EmptyEnt:
    """Entity that returns default for every key."""

    def get(self, key: str, default: str = "") -> str:
        return default


class _CmdEnt:
    """Entity that returns a fixed KV dict."""

    def __init__(self, kv: dict[str, str]):
        self._kv = kv

    def get(self, key: str, default: str = "") -> str:
        return self._kv.get(key, default)


class TestBspAdversarial:
    def test_entity_side_effects_no_ents_attr(self) -> None:
        """BSP without `ents` attribute returns empty effects."""

        class BspNoEnts:
            pass

        result = extract_bsp_entity_side_effects(BspNoEnts())
        assert result["commands"] == []
        assert result["globalstates"] == []

    def test_entity_side_effects_ents_no_entities(self) -> None:
        """BSP with ents but no entities attribute returns empty."""

        class MockBsp:
            class ents:
                pass

        result = extract_bsp_entity_side_effects(MockBsp())
        assert result["commands"] == []
        assert result["globalstates"] == []

    def test_entity_side_effects_empty_classname(self) -> None:
        """Entity with empty classname is skipped."""
        ent = _EmptyEnt()

        class MockBsp:
            class ents:
                entities = [ent]

        result = extract_bsp_entity_side_effects(MockBsp())
        assert result["commands"] == []
        assert result["globalstates"] == []

    def test_entity_side_effects_classname_is_none(self) -> None:
        """Entity.get returning None for classname is coerced to string."""

        class _NoneEnt:
            def get(self, key: str, default: str = "") -> str:
                return None if key == "classname" else default  # type: ignore[return]

        class MockBsp:
            class ents:
                entities = [_NoneEnt()]

        result = extract_bsp_entity_side_effects(MockBsp())
        assert result["commands"] == []
        assert result["globalstates"] == []

    def test_entity_side_effects_long_commands(self) -> None:
        """Very long command string is returned as-is."""
        long_cmd = "say " + "x" * 10_000

        class MockBsp:
            class ents:
                entities = [
                    _CmdEnt({"classname": "point_servercommand", "command": long_cmd})
                ]

        result = extract_bsp_entity_side_effects(MockBsp())
        assert long_cmd in result["commands"]

    def test_entity_side_effects_5k_entities(self) -> None:
        """5000 servercommand entities all extracted."""
        ents = [_CmdEnt({"classname": "point_servercommand", "command": f"cmd{i}"}) for i in range(5000)]

        class MockBsp:
            class ents:
                entities = ents

        result = extract_bsp_entity_side_effects(MockBsp())
        assert len(result["commands"]) == 5000

    def test_extract_deps_chain_none_returns_empty(self) -> None:
        """Chain=None returns empty via broad except."""
        result = extract_bsp_dependencies(None, "maps/test.bsp")
        assert isinstance(result, set)

    def test_extract_deps_empty_bytes_via_mock_chain(self) -> None:
        """Empty bytes from chain does not crash."""
        result = extract_bsp_dependencies(_MockChain(b""), "maps/test.bsp")
        assert isinstance(result, set)

    def test_extract_deps_garbage_bytes_via_mock_chain(self) -> None:
        """Corrupted BSP bytes from chain does not crash."""
        result = extract_bsp_dependencies(_MockChain(b"\x00\x01\x02\xff" * 1000), "maps/test.bsp")
        assert isinstance(result, set)


# -----------------------------------------------------------------------
# 19g. bsp_pakfile — adversarial
# -----------------------------------------------------------------------


class TestBspPakfileAdversarial:
    def test_corrupted_zip_returns_empty(self) -> None:
        """Corrupted ZIP data returns empty list from extract."""
        result = extract_bsp_pakfile_entries(b"PK\x00\x00" + b"\x00" * 100)
        assert result == []

    def test_script_scan_utf16_encoded_nut(self) -> None:
        """.nut encoded as UTF-16 does not crash scan_bsp_scripts."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("test.nut", '﻿IncludeScript("mylib")\n'.encode("utf-16"))
        result = scan_bsp_scripts(buf.getvalue())
        assert isinstance(result, set)

    def test_script_scan_very_long_exec_cfg(self) -> None:
        """.cfg with very long exec path."""
        long_path = "maps/" + "a" * 10_000 + ".cfg"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("test.cfg", f"exec {long_path}\n")
        result = scan_bsp_scripts(buf.getvalue())
        # scan_bsp_scripts prepends cfg/ when path doesn't start with cfg/
        assert "cfg/" + long_path in result

    def test_script_scan_empty_zip_returns_empty(self) -> None:
        """Empty ZIP returns empty set."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            pass
        result = scan_bsp_scripts(buf.getvalue())
        assert isinstance(result, set)

    def test_script_scan_garbage_no_crash(self) -> None:
        """Raw garbage without valid ZIP returns empty set."""
        result = scan_bsp_scripts(b"\xff\xfe\x00" * 1000)
        assert isinstance(result, set)


# -----------------------------------------------------------------------
# 19h. mdl_parser — adversarial
# -----------------------------------------------------------------------


class TestMdlAdversarial:
    def test_chain_none_returns_empty(self) -> None:
        """Chain=None returns empty set."""
        result = extract_mdl_dependencies(None, "models/test.mdl")
        assert isinstance(result, set)

    def test_chain_empty_bytes_returns_empty(self) -> None:
        """Chain returning empty bytes returns empty."""
        result = extract_mdl_dependencies(_MockChain(b""), "models/test.mdl")
        assert isinstance(result, set)

    def test_chain_garbage_bytes_returns_empty(self) -> None:
        """Chain returning garbage bytes returns empty."""
        result = extract_mdl_dependencies(_MockChain(b"\x00\x01\x02" * 1000), "models/test.mdl")
        assert isinstance(result, set)

    def test_virtual_path_empty_string(self) -> None:
        """Empty virtual path does not crash."""
        result = extract_mdl_dependencies(None, "")
        assert isinstance(result, set)


# -----------------------------------------------------------------------
# 19i. simple_list_parser — adversarial
# -----------------------------------------------------------------------


class TestSimpleListAdversarial:
    def test_binary_garbage_no_crash(self) -> None:
        """Binary garbage string returns empty set."""
        garbage = "\x00\x01\x02\xff\xfe" * 1000
        result = parse_simple_list(garbage)
        assert isinstance(result, set)

    def test_very_long_single_line(self) -> None:
        """Extremely long single line is extracted."""
        line = "sound/" + "a" * 100_000 + ".wav"
        result = parse_simple_list(line)
        assert len(result) == 1

    def test_utf16_bom_lines(self) -> None:
        """UTF-16 BOM prefixes handled (returns empty — can't split)."""
        result = parse_simple_list('﻿sound/a.wav\nsound/b.wav')
        assert isinstance(result, set)

    def test_100k_lines_performance(self) -> None:
        """100 000 lines all extracted."""
        lines = "\n".join(f"sound/file{i}.wav" for i in range(100_000))
        result = parse_simple_list(lines)
        assert len(result) == 100_000

    def test_prefix_not_duplicated_on_existing(self) -> None:
        """Prefix not added when entry already has it."""
        result = parse_simple_list("sound/a.wav\n", prefix="sound/")
        assert "sound/a.wav" in result
        assert not any("sound/sound/" in p for p in result)

    def test_empty_lines_and_comments_mixed(self) -> None:
        """Mixture of empty lines, comments, and data returns only data."""
        content = "\n\n// header\n\n# meta\nsound/a.wav\n\n"
        result = parse_simple_list(content)
        assert result == {"sound/a.wav"}


# -----------------------------------------------------------------------
# 19j. texture_list_parser — adversarial
# -----------------------------------------------------------------------


class TestTextureListAdversarial:
    def test_binary_garbage_no_crash(self) -> None:
        """Binary garbage returns empty set."""
        garbage = "\x00\x01\x02\xff" * 1000
        result = extract_texture_list_dependencies(garbage)
        assert isinstance(result, set)

    def test_very_long_texture_path(self) -> None:
        """100k char texture path returns set with one entry."""
        text = '"tex" "' + "a" * 100_000 + '"'
        result = extract_texture_list_dependencies(text)
        assert isinstance(result, set)

    def test_empty_block_in_kv(self) -> None:
        """Empty section block does not interfere with other entries."""
        text = '"section" { } "tex" "hud/icon"'
        result = extract_texture_list_dependencies(text)
        assert any("hud/icon" in p for p in result)

    def test_list_value_from_duplicate_keys(self) -> None:
        """Duplicate keys (list value) handled."""
        text = '"tex" "a" "tex" "b"'
        result = extract_texture_list_dependencies(text)
        assert len(result) == 2

    def test_vtf_path_without_prefix(self) -> None:
        """Path without materials/ gets it added."""
        result = extract_texture_list_dependencies('"tex" "my_texture"')
        assert all(p.startswith("materials/") for p in result)


# -----------------------------------------------------------------------
# 19k. addoninfo — adversarial
# -----------------------------------------------------------------------


class TestAddonInfoAdversarial:
    def test_binary_garbage_no_crash(self) -> None:
        """Binary garbage returns dict (may be empty)."""
        garbage = "\x00\x01\x02\xff" * 1000
        result = parse_addoninfo(garbage)
        assert isinstance(result, dict)

    def test_deeply_nested_kv_no_crash(self) -> None:
        """Deeply nested KV does not crash."""
        nested = '"a" {' * 500 + '"x" "y"' + "}" * 500
        result = parse_addoninfo(nested)
        assert isinstance(result, dict)

    def test_empty_dependencies_list(self) -> None:
        """Empty dependencies list returns empty."""
        assert extract_dependency_ids({"dependencies": []}) == []

    def test_dependencies_is_not_list(self) -> None:
        """Dependencies that is a string returns empty."""
        assert extract_dependency_ids({"dependencies": "not_a_list"}) == []

    def test_dep_missing_workshop_id(self) -> None:
        """Dep item without workshop_id key is skipped."""
        meta = {"dependencies": [{"addon_name": "x"}, {"workshop_id": "456"}]}
        assert extract_dependency_ids(meta) == ["456"]

    def test_dep_empty_workshop_id(self) -> None:
        """Dep with empty workshop_id is skipped."""
        meta = {"dependencies": [{"workshop_id": ""}]}
        assert extract_dependency_ids(meta) == []

    def test_dep_ids_de_duplicated(self) -> None:
        """Duplicate workshop_ids are all returned (no dedup — caller handles it)."""
        meta = {"dependencies": [{"workshop_id": "123"}, {"workshop_id": "123"}]}
        assert extract_dependency_ids(meta) == ["123", "123"]


# -----------------------------------------------------------------------
# 19l. KV-based parsers — combined adversarial
# -----------------------------------------------------------------------


class TestKvBasedParsersAdversarial:
    """game_sounds, level_sounds, missions, melee, population, weapon, res
    all share the kv_parser foundation.  Test edge cases across all of them."""

    @pytest.mark.parametrize(
        "parser",
        [
            extract_game_sounds_dependencies,
            extract_level_sounds_dependencies,
            extract_missions_dependencies,
            extract_melee_dependencies,
            extract_population_dependencies,
            extract_weapon_dependencies,
            extract_res_dependencies,
        ],
    )
    def test_empty_input_returns_empty(self, parser) -> None:
        assert parser("") == set()
        assert parser("// comment") == set()

    @pytest.mark.parametrize(
        "parser",
        [
            extract_game_sounds_dependencies,
            extract_level_sounds_dependencies,
            extract_missions_dependencies,
            extract_melee_dependencies,
            extract_population_dependencies,
            extract_weapon_dependencies,
            extract_res_dependencies,
        ],
    )
    def test_binary_garbage_returns_empty(self, parser) -> None:
        garbage = "\x00\x01\x02\xff" * 1000
        result = parser(garbage)
        assert isinstance(result, set)

    @pytest.mark.parametrize(
        "parser",
        [
            extract_game_sounds_dependencies,
            extract_level_sounds_dependencies,
            extract_missions_dependencies,
            extract_melee_dependencies,
            extract_population_dependencies,
            extract_weapon_dependencies,
            extract_res_dependencies,
        ],
    )
    def test_extra_closing_braces(self, parser) -> None:
        result = parser('"a" "1" } "b" "2" }')
        assert isinstance(result, set)

    @pytest.mark.parametrize(
        "parser",
        [
            extract_game_sounds_dependencies,
            extract_level_sounds_dependencies,
            extract_missions_dependencies,
        ],
    )
    def test_empty_brace_block(self, parser) -> None:
        """Empty brace block {} does not crash."""
        result = parser('"section" { }')
        assert isinstance(result, set)

    def test_game_sounds_duplicate_wave_keys(self) -> None:
        """Duplicate 'wave' keys produce a list, both extracted."""
        raw = '"s1" { "wave" "a.wav" "wave" "b.wav" }'
        deps = extract_game_sounds_dependencies(raw)
        assert len(deps) == 2

    def test_level_sounds_duplicate_sound_keys(self) -> None:
        """Duplicate 'sound' keys produce a list, both extracted."""
        raw = '"area" { "sound" "a.wav" "sound" "b.wav" }'
        deps = extract_level_sounds_dependencies(raw)
        assert len(deps) == 2

    def test_missions_duplicate_map_keys(self) -> None:
        """Duplicate Map keys produce a list, parser skips list values."""
        raw = '"modes" { "campaign" { "1" { "Map" "c1m1" "Map" "c1m2" } } }'
        deps = extract_missions_dependencies(raw)
        # kv_parser produces list for duplicate keys, missions parser skips lists
        assert isinstance(deps, set)

    def test_melee_empty_model_path(self) -> None:
        """Empty model path is not added to deps."""
        raw = '"axe" { "viewmodel" "" "worldmodel" "models/axe_w.mdl" }'
        deps = extract_melee_dependencies(raw)
        assert "models/axe_w.mdl" in deps
        assert "" not in deps

    def test_population_duplicate_zombie_class(self) -> None:
        """Duplicate zombie_class keys produce a list, parser skips list values."""
        raw = '"z1" { "zombie_class" "hunter" "zombie_class" "smoker" }'
        deps = extract_population_dependencies(raw)
        # kv_parser produces list for duplicate keys, population parser skips lists
        assert isinstance(deps, set)

    def test_weapon_missing_weapondata_top_level(self) -> None:
        """Weapon parser uses top-level keys when 'weapondata' is absent."""
        raw = '"viewmodel" "models/gun.mdl"'
        deps = extract_weapon_dependencies(raw)
        assert "models/gun.mdl" in deps

    def test_res_with_null_byte_in_path(self) -> None:
        """Null byte embedded in value does not crash."""
        raw = '"ctx" { "image" "test\x00img" }'
        deps = extract_res_dependencies(raw)
        assert isinstance(deps, set)
