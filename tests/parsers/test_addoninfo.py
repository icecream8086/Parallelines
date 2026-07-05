"""Tests for parallelines.parsers.addoninfo — addoninfo.txt parsing and dependency extraction."""

from __future__ import annotations

from unittest.mock import patch

from parallelines.parsers.addoninfo import (
    extract_dependency_ids,
    parse_addoninfo,
)


class _MockNode:
    """Minimal mock that mimics a srctools Keyvalues node.

    Attributes:
        name: The key name.
        value: Either a str leaf value or a list[_MockNode] for sub-blocks.
    """

    def __init__(self, name: str, value: str | list):
        self.name = name
        self.value = value


def _make_root(blocks: list[_MockNode]) -> list[_MockNode]:
    """Return a list mimicking the srctools Keyvalues virtual root.

    Iterating the return value yields *blocks*, each representing a top-level
    VDF block in the file.
    """
    return blocks


def test_parse_addoninfo_basic() -> None:
    """Parse a simple addoninfo.txt VDF structure and verify field extraction."""
    root = _make_root(
        [
            _MockNode(
                "addoninfo.txt",
                [
                    _MockNode("addon_name", "My Addon"),
                    _MockNode("addon_version", "1.0"),
                ],
            ),
        ]
    )
    with (
        patch("parallelines.parsers.addoninfo.SRCTOOLS_AVAILABLE", True),
        patch("parallelines.parsers.addoninfo._Keyvalues") as mock_kv,
    ):
        mock_kv.parse.return_value = root
        result = parse_addoninfo("dummy content")

    assert result.get("addon_name") == "My Addon"
    assert result.get("addon_version") == "1.0"


def test_parse_addoninfo_empty() -> None:
    """Empty content should return an empty dict."""
    result = parse_addoninfo("")
    assert result == {}


def test_extract_dependency_ids() -> None:
    """Parse content with dependencies and verify Workshop ID extraction."""
    root = _make_root(
        [
            _MockNode(
                "addoninfo.txt",
                [
                    _MockNode(
                        "dependencies",
                        [
                            _MockNode("workshop_id", "12345"),
                            _MockNode("workshop_id", "67890"),
                        ],
                    ),
                ],
            ),
        ]
    )
    with (
        patch("parallelines.parsers.addoninfo.SRCTOOLS_AVAILABLE", True),
        patch("parallelines.parsers.addoninfo._Keyvalues") as mock_kv,
    ):
        mock_kv.parse.return_value = root
        meta = parse_addoninfo("dummy content")

    ids = extract_dependency_ids(meta)
    assert ids == ["12345", "67890"]
