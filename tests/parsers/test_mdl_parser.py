"""Tests for parallelines.parsers.mdl_parser — MDL model dependency extraction."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


from parallelines.parsers.mdl_parser import _normalise_vtf_path, extract_mdl_dependencies


def test_extract_mdl_dependencies_graceful_degradation() -> None:
    """Graceful degradation: None chain or broken chain returns empty set."""
    # Chain is None — TypeError on subscript is caught by try/except
    deps = extract_mdl_dependencies(None, "dummy.mdl")
    assert deps == set()

    # Chain raises on __getitem__ — exception is caught
    broken_chain = MagicMock()
    broken_chain.__getitem__.side_effect = RuntimeError("chain broken")
    deps = extract_mdl_dependencies(broken_chain, "models/props/brick.mdl")
    assert deps == set()


def test_empty_content() -> None:
    """When srctools is unavailable, extract_mdl_dependencies returns empty set."""
    with patch("parallelines.parsers.mdl_parser.SRCTOOLS_AVAILABLE", False):
        deps = extract_mdl_dependencies(MagicMock(), "dummy.mdl")

    assert deps == set()


class TestMdlNormalisePath:
    """Tests for _normalise_vtf_path — path normalisation for MDL textures."""

    def test_bare_name(self) -> None:
        assert _normalise_vtf_path("brick") == "materials/brick.vtf"

    def test_with_extension(self) -> None:
        assert _normalise_vtf_path("brick.vtf") == "materials/brick.vtf"

    def test_with_materials_prefix(self) -> None:
        assert _normalise_vtf_path("materials/brick/brick.vtf") == "materials/brick/brick.vtf"

    def test_backslashes_converted(self) -> None:
        assert _normalise_vtf_path(r"materials\brick\brick.vtf") == "materials/brick/brick.vtf"
