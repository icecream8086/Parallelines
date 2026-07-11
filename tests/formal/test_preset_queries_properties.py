"""Layer 1+2 — Oracle-Free tests for query preset integrity.

Covers two bug classes discovered 2026-07-11:
  B1 — SQL ``%`` wildcard in ``like`` patterns (engine uses ``fnmatch`` with ``*``)
  B2 — Broken query format (old v1 group_by, count_where in select, missing columns)

Methodology (devdocs/oracle-free-testing-prompt.md):
  - Property test on all preset files (parse + validate) — catches B2
  - Metamorphic relation for like-pattern wildcard translation — catches B1
"""

from __future__ import annotations

import fnmatch
import json
import re
from pathlib import Path

import pytest

from parallelines.engine import (
    AddonRow,
    CascadeOverrideRow,
    DepConflictRow,
    DependencyCycleRow,
    DependencyRow,
    EntryPointRow,
    ExternalFileRow,
    FileRow,
    GlobalScriptRow,
    HashConflictRow,
    ImpactRow,
    ImplicitDepRow,
    IsolatedPackageRow,
    ModTypeRow,
    Relation,
    ResultStore,
)
from parallelines.engine.query_parser import QueryParser
from parallelines.engine.query_validator import QueryValidator

# ── Queries directory resolution (mirrors _find_queries_dir in cli.py) ──────

_QUERIES_DIR = (Path(__file__).resolve().parent.parent.parent / "queries").resolve()


def _load_all_presets() -> list[tuple[str, dict]]:
    """Load every .json preset file from queries/. Returns [(name, dict), ...]."""
    if not _QUERIES_DIR.is_dir():
        return []
    presets: list[tuple[str, dict]] = []
    for p in sorted(_QUERIES_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            presets.append((p.name, data))
        except json.JSONDecodeError:
            presets.append((p.name, {}))  # will fail parse test
    return presets


# ═══════════════════════════════════════════════════════════════════════════════
# Property 1: Every preset parses without error
# ═══════════════════════════════════════════════════════════════════════════════


class TestPresetsParse:
    """Property: every .json file in queries/ must produce a valid Query AST.

    If this fails, the parser encountered a format error (e.g. dict where
    a string was expected, as in ``complete_dead_by_type.json`` B2).
    """

    @pytest.mark.parametrize(
        "name,data",
        [(n, d) for n, d in _load_all_presets()],
        ids=[n for n, _ in _load_all_presets()],
    )
    def test_preset_parses(self, name: str, data: dict) -> None:
        """MR (Invertive): parse(JSON) never raises → round-trip structural invariant."""
        assert isinstance(data, dict) and len(data) > 0, (
            f"Preset '{name}' is empty or not a dict"
        )
        # Must have at minimum 'select' and 'from'
        assert "select" in data, f"Preset '{name}' missing 'select'"
        assert "from" in data, f"Preset '{name}' missing 'from'"

        # Parsing must succeed — if it doesn't, the query is structurally broken.
        ast = QueryParser.parse(data)
        assert ast is not None, f"Parser returned None for '{name}'"

    @pytest.mark.parametrize(
        "name,data",
        [(n, d) for n, d in _load_all_presets()],
        ids=[n for n, _ in _load_all_presets()],
    )
    def test_preset_group_by_format(self, name: str, data: dict) -> None:
        """MR (Structural): group_by must use v2 format {"by": [...], "agg": {...}}.

        Catches old v1 format {"key": ..., "order": ...} used in B2.
        """
        if "group_by" in data:
            gb = data["group_by"]
            assert isinstance(gb, dict), (
                f"Preset '{name}': group_by must be a dict, got {type(gb).__name__}"
            )
            assert "by" in gb, (
                f"Preset '{name}': group_by missing 'by' key — "
                f"old v1 format? Use v2: {{\"by\": [...], \"agg\": {...}}}"
            )
            assert "agg" in gb, (
                f"Preset '{name}': group_by missing 'agg' key — "
                f"old v1 format? Use v2: {{\"by\": [...], \"agg\": {...}}}"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# Property 2: All presets validate against a full store
# ═══════════════════════════════════════════════════════════════════════════════


def _make_full_store() -> ResultStore:
    """Build a ResultStore with all relations that presets may reference.

    Each relation has a single dummy row so the schema is populated.
    """
    store = ResultStore()

    store.files = Relation[FileRow].from_rows("files", [
        FileRow("a.txt", "base", "game", 100, "aaa", 1024, True),
        FileRow("b.txt", "addon_x", "addon", 200, "bbb", 512, True),
    ])

    store.dependencies = Relation[DependencyRow].from_rows("dependencies", [
        DependencyRow("a.txt", "b.txt", "base"),
    ])

    store.addons = Relation[AddonRow].from_rows("addons", [
        AddonRow("base", "Base Game", True, 100),
    ])

    store.hash_conflicts = Relation[HashConflictRow].from_rows("hash_conflicts", [
        HashConflictRow("shared.vmt", "src_a", "src_b", "aaa", "bbb"),
    ])

    store.dep_conflicts = Relation[DepConflictRow].from_rows("dep_conflicts", [
        DepConflictRow("a.txt", "b.txt", "addon_x", "MISSING"),
    ])

    store.isolated = Relation[IsolatedPackageRow].from_rows("isolated", [
        IsolatedPackageRow("broken_pkg", 5, ["a.txt"]),
    ])

    store.impact = Relation[ImpactRow].from_rows("impact", [
        ImpactRow("a.txt", "base", 42),
    ])

    store.entry_points = Relation[EntryPointRow].from_rows("entry_points", [
        EntryPointRow("maps/test.bsp", "map"),
    ])

    store.dependency_cycles = Relation[DependencyCycleRow].from_rows(
        "dependency_cycles",
        [DependencyCycleRow(["a.vpk", "b.vpk", "a.vpk"], 3)],
    )

    store.cascade_overrides = Relation[CascadeOverrideRow].from_rows(
        "cascade_overrides",
        [CascadeOverrideRow("shared.vmt", ["a", "b"], [100, 50], "a")],
    )

    store.global_scripts = Relation[GlobalScriptRow].from_rows("global_scripts", [
        GlobalScriptRow("scripts/vscripts/global.nut", "base", "game"),
    ])

    store.implicit_deps = Relation[ImplicitDepRow].from_rows("implicit_deps", [
        ImplicitDepRow("addon_a", "addon_b", "shared.vmt"),
    ])

    store.mod_types = Relation[ModTypeRow].from_rows("mod_types", [
        ModTypeRow("addon_x", "map", 10, 2, 1, 7, False),
    ])

    store.external_files = Relation[ExternalFileRow].from_rows("external_files", [
        ExternalFileRow("a.txt", "ref:ext", 2000, "xxx", 1024),
    ])
    store.external_files.build_index("virtual_path")

    return store


class TestPresetsValidate:
    """Property: every preset validates against a full-schema store.

    Catches column-reference errors (e.g. ``ext`` column not in FileRow, B2).
    """

    _store = _make_full_store()

    @pytest.mark.parametrize(
        "name,data",
        [(n, d) for n, d in _load_all_presets() if d],
        ids=[n for n, d in _load_all_presets() if d],
    )
    def test_preset_validates(self, name: str, data: dict) -> None:
        """MR (Differential): validator errors == [] for every preset.

        Uses the full-schema store so relation-not-found and column-not-found
        errors are caught before shipping.
        """
        ast = QueryParser.parse(data)
        errors = QueryValidator.validate(ast, self._store)
        assert errors == [], (
            f"Preset '{name}' validation errors:\n"
            + "\n".join(f"  {e}" for e in errors)
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Property 3: No preset uses SQL % wildcard in like patterns
# ═══════════════════════════════════════════════════════════════════════════════

# Characters that are fnmatch glob wildcards but look like SQL LIKE to a
# database-experienced author.
_SQL_LIKE_RE = re.compile(r"(?<!\\)%")


def _collect_like_preds(data: dict) -> list[str]:
    """Extract all ``like`` pattern strings from a query dict (recursive)."""
    patterns: list[str] = []

    def _walk(obj):
        if isinstance(obj, dict):
            if "like" in obj and len(obj) == 1:
                pat = obj["like"][1]
                if isinstance(pat, str):
                    patterns.append(pat)
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(data)
    return patterns


class TestPresetsLikePattern:
    """Property: no preset ``like`` pattern contains SQL ``%`` wildcard.

    The engine uses ``fnmatch.fnmatch()`` (shell glob: ``*``, ``?``).
    ``%`` is a *literal* character in fnmatch, not a wildcard.  A pattern
    like ``materials/%.vmt`` will only match the exact filename ``%.vmt``
    — it will never match real files like ``brick.vmt``.
    """

    @pytest.mark.parametrize(
        "name,data",
        [(n, d) for n, d in _load_all_presets() if d],
        ids=[n for n, d in _load_all_presets() if d],
    )
    def test_like_patterns_no_sql_wildcards(self, name: str, data: dict) -> None:
        """Structural check: no ``like`` pattern in any preset uses ``%``."""
        for pattern in _collect_like_preds(data):
            assert not _SQL_LIKE_RE.search(pattern), (
                f"Preset '{name}': like pattern '{pattern}' uses SQL '%' wildcard. "
                f"The engine uses fnmatch (shell glob). Use '*' instead of '%'."
            )


# ═══════════════════════════════════════════════════════════════════════════════
# Metamorphic relation: like pattern wildcard translation
# ═══════════════════════════════════════════════════════════════════════════════

_SQL_TO_FNMATCH = str.maketrans({"%": "*", "_": "?"})


def _translate_sql_to_fnmatch(pattern: str) -> str:
    """Translate SQL LIKE wildcards to fnmatch glob: % → *, _ → ?."""
    return pattern.translate(_SQL_TO_FNMATCH)


class TestLikeWildcardMetamorphic:
    """MR: translating ``%`` → ``*`` in a ``like`` pattern never shrinks the result.

    Formally: ∀ pattern p, ∀ value set V:
      {v ∈ V | fnmatch(v, translate(p))} ⊇ {v ∈ V | fnmatch(v, p)}

    This is because ``*`` matches strictly more strings than ``%`` (which
    is a literal character in fnmatch), and ``?`` matches strictly more
    than ``_``.

    If the superset relation is violated, the author likely wrote SQL
    wildcards assuming the engine would interpret them.
    """

    def test_sql_percent_is_subset_of_star(self) -> None:
        """MR (Additive): fnmatch with * matches superset of fnmatch with literal %.

        ``materials/%.vmt`` (fnmatch-literal %) ⊂ ``materials/*.vmt`` (glob).
        """
        vals = [
            "materials/brick.vmt",
            "materials/metal.vmt",
            "materials/%.vmt",   # literal percent — extremely unlikely in practice
            "models/player.mdl",
        ]
        sql_pat = "materials/%.vmt"    # B1: author wrote this thinking SQL LIKE
        glob_pat = _translate_sql_to_fnmatch(sql_pat)  # → materials/*.vmt

        sql_matches = {v for v in vals if fnmatch.fnmatch(v, sql_pat)}
        glob_matches = {v for v in vals if fnmatch.fnmatch(v, glob_pat)}

        # The glob pattern must match at least as many values.
        assert glob_matches >= sql_matches, (
            f"MR violated: translate(like) ⊉ original like\n"
            f"  pattern:      '{sql_pat}'\n"
            f"  translated:   '{glob_pat}'\n"
            f"  sql_matches:  {sql_matches}\n"
            f"  glob_matches: {glob_matches}"
        )

        # In practical cases: glob matches real files, sql (literal %) matches none.
        assert "materials/brick.vmt" in glob_matches, (
            "Glob * did not match real file path"
        )
        assert "materials/brick.vmt" not in sql_matches, (
            "Literal % incorrectly matched real file path (should not happen)"
        )

    def test_sql_underscore_is_subset_of_question(self) -> None:
        """MR (Additive): fnmatch ``?`` matches superset of literal ``_``."""
        vals = ["file_a.txt", "file_b.txt", "file_.txt", "file1.txt"]
        sql_pat = "file_.txt"
        glob_pat = _translate_sql_to_fnmatch(sql_pat)  # → file?.txt

        sql_matches = {v for v in vals if fnmatch.fnmatch(v, sql_pat)}
        glob_matches = {v for v in vals if fnmatch.fnmatch(v, glob_pat)}

        assert glob_matches >= sql_matches, (
            f"MR violated for _ → ? translation: "
            f"sql={sql_matches}, glob={glob_matches}"
        )

    def test_sql_to_fnmatch_roundtrip_on_shell_pattern(self) -> None:
        """MR (Invertive): a pattern already using glob syntax is unchanged by translate."""
        patterns = [
            "materials/*.vmt",
            "sound/*.wav",
            "models/infected/*.mdl",
            "scripts/melee/*",
            "*.pcf",
            "*.res",
        ]
        for pat in patterns:
            assert _translate_sql_to_fnmatch(pat) == pat, (
                f"Glob pattern '{pat}' was altered by translate — should be identity"
            )

    def test_translate_mixed_preserves_structure(self) -> None:
        """MR (Compositional): translate replaces ALL % → * and _ → ? in one pass."""
        pattern = "materials/%/texture_%.vtf"
        result = _translate_sql_to_fnmatch(pattern)
        # Both % become *, _ becomes ?: materials/*/texture?*.vtf
        assert "%" not in result, f"SQL '%' not fully translated: {result}"
        assert "_" not in result, f"SQL '_' not fully translated: {result}"
        assert "*" in result and "?" in result, (
            f"Glob wildcards missing from translated result: {result}"
        )
