"""Tests for parallelines.parsers.nut_parser — NUT script dependency extraction."""

from __future__ import annotations

from parallelines.parsers.nut_parser import extract_nut_dependencies


def test_extract_include() -> None:
    """Parse a NUT script and extract IncludeScript dependencies.

    ``IncludeScript("mymod/mylib")`` resolves to ``mymod/mylib.nut`` because
    the path already contains a directory separator; the ``scripts/vscripts/``
    prefix is added only for bare filenames without a ``/``.
    """
    content = '#base "vpklib:/scripts/mymod/mylib.nut"\nIncludeScript("mymod/mylib")\n'
    deps = extract_nut_dependencies(content)
    assert "mymod/mylib.nut" in deps


def test_empty_content() -> None:
    """Empty content returns an empty set."""
    assert extract_nut_dependencies("") == set()


def test_no_match() -> None:
    """Content without include directives returns an empty set."""
    content = 'my_function <- function() {\n    print("Hello, world!");\n}\n'
    assert extract_nut_dependencies(content) == set()
