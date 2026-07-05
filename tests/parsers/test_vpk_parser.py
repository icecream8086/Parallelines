"""Tests for parallelines.parsers.vpk_parser — VPK index parsing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from parallelines.exceptions import ParseError
from parallelines.parsers.vpk_parser import parse_vpk_index


def test_import_error() -> None:
    """When SRCTOOLS_AVAILABLE is False, parse_vpk_index raises ParseError."""
    with (
        patch.object(Path, "exists", return_value=True),
        patch("parallelines.parsers.vpk_parser.SRCTOOLS_AVAILABLE", False),
    ):
        with pytest.raises(ParseError, match="srctools is not available"):
            parse_vpk_index("/tmp/fake.vpk")


def test_module_importable() -> None:
    """The vpk_parser module can be imported successfully."""
    from parallelines.parsers import vpk_parser  # noqa: F811

    assert vpk_parser is not None
