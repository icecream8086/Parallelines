"""Tests for parallelines.parsers.mdl_parser — MDL model dependency extraction."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from parallelines.parsers.mdl_parser import extract_mdl_dependencies


def test_extract_textures() -> None:
    """Parse a model and extract texture and material references."""
    mock_chain = MagicMock()
    mock_mdl_file = MagicMock()
    mock_vmt_file = MagicMock()
    mock_vmt_file.open_str.return_value.read.return_value = (
        'VertexLitGeneric { $basetexture "materials/brick/brick" '
        '$bumpmap "materials/brick/brick_normal" }'
    )

    def _chain_getitem(path: str) -> MagicMock:
        if path == "models/props/brick.mdl":
            return mock_mdl_file
        return mock_vmt_file

    mock_chain.__getitem__.side_effect = _chain_getitem

    mock_model = MagicMock()
    mock_model.iter_textures.return_value = [
        "materials/brick/brick.vmt",
    ]

    mock_material = MagicMock()
    mock_material.get.side_effect = lambda key: {
        "$basetexture": "materials/brick/brick",
        "$bumpmap": "materials/brick/brick_normal",
    }.get(key)

    with (
        patch("parallelines.parsers.mdl_parser.SRCTOOLS_AVAILABLE", True),
        patch("parallelines.parsers.mdl_parser.Model", return_value=mock_model),
        patch(
            "parallelines.parsers.mdl_parser.Material.parse",
            return_value=mock_material,
        ),
    ):
        deps = extract_mdl_dependencies(mock_chain, "models/props/brick.mdl")

    assert "materials/brick/brick.vmt" in deps
    assert "materials/brick/brick.vtf" in deps
    assert "materials/brick/brick_normal.vtf" in deps


def test_empty_content() -> None:
    """When srctools is unavailable, extract_mdl_dependencies returns empty set."""
    with patch("parallelines.parsers.mdl_parser.SRCTOOLS_AVAILABLE", False):
        deps = extract_mdl_dependencies(MagicMock(), "dummy.mdl")

    assert deps == set()
