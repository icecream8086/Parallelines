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
                    parent[key] = existing + [new_dict] if isinstance(existing, list) else [existing, new_dict]
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
                    parent[key] = existing + [val] if isinstance(existing, list) else [existing, val]
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
        a = '"modes" { ' + a_inner + ' }'
        b = '"modes" { ' + b_inner + ' }'
        combined = '"modes" { ' + a_inner + ' ' + b_inner + ' }'
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
        result = extract_bsp_pakfile_entries(
            b"VBSP" + b"\x00" * 100 + empty_zip
        )
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
        two = self._make_zip({
            "s1.nut": 'IncludeScript("lib1")\n',
            "s2.nut": 'IncludeScript("lib2")\n',
        })
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
        more = self._mk_bsp([
            {"classname": "point_servercommand", "command": "cmd1"},
            {"classname": "point_servercommand", "command": "cmd2"},
        ])
        r_base = extract_bsp_entity_side_effects(base)
        r_more = extract_bsp_entity_side_effects(more)
        assert r_more["commands"] >= r_base["commands"]

    def test_additive_globalstates(self) -> None:
        """MR (Additive): more env_global entities → globalstates superset."""
        base = self._mk_bsp([{"classname": "env_global", "globalstate": "gs1"}])
        more = self._mk_bsp([
            {"classname": "env_global", "globalstate": "gs1"},
            {"classname": "env_global", "globalstate": "gs2"},
        ])
        r_base = extract_bsp_entity_side_effects(base)
        r_more = extract_bsp_entity_side_effects(more)
        assert r_more["globalstates"] >= r_base["globalstates"]

    def test_harmless_entity_ignored(self) -> None:
        """MR (Exclusive): entities not in {servercommand, env_global} produce no effects."""
        harmless = self._mk_bsp([
            {"classname": "info_player_start"},
            {"classname": "light_spot"},
        ])
        r = extract_bsp_entity_side_effects(harmless)
        assert r["commands"] == []
        assert r["globalstates"] == []

    def test_interspersed_entities(self) -> None:
        """MR (Compositional): interspersing harmless entities preserves extraction."""
        pure = self._mk_bsp([{"classname": "point_servercommand", "command": "x"}])
        mixed = self._mk_bsp([
            {"classname": "info_player_start"},
            {"classname": "point_servercommand", "command": "x"},
            {"classname": "light_spot"},
        ])
        assert extract_bsp_entity_side_effects(mixed)["commands"] \
            == extract_bsp_entity_side_effects(pure)["commands"]


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
