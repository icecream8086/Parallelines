"""Lightweight Source Engine KeyValues tokenizer for bulk .txt parsing."""

from __future__ import annotations

import re
from typing import Any

_TOKEN_RE = re.compile(r'"([^"]*)"|(\S+)')
_COMMENT_PREFIXES = ("//", "#", ";")


def tokenize(text: str) -> list[str]:
    """Tokenize KeyValues text into a flat list of bare strings (quotes stripped)."""
    tokens: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(_COMMENT_PREFIXES):
            continue
        for m in _TOKEN_RE.finditer(stripped):
            if m.group(1) is not None:
                tokens.append(m.group(1))
            elif m.group(2) is not None:
                tokens.append(m.group(2))
    return tokens


def _parse_block(tokens: list[str], start: int) -> tuple[dict[str, Any], int]:
    """Parse tokens from start until matching '}' token.

    Returns (parsed_dict, index_after_closing_brace).
    """
    block: dict[str, Any] = {}
    i = start
    n = len(tokens)
    while i < n and tokens[i] != "}":
        bk = tokens[i].lower()
        i += 1
        if i >= n:
            break
        if tokens[i] == "{":
            sub_block, i = _parse_block(tokens, i + 1)
            if bk in block:
                existing = block[bk]
                block[bk] = existing + [sub_block] if isinstance(existing, list) else [existing, sub_block]
            else:
                block[bk] = sub_block
        else:
            bv = tokens[i]
            i += 1
            if bk in block:
                existing = block[bk]
                block[bk] = existing + [bv] if isinstance(existing, list) else [existing, bv]
            else:
                block[bk] = bv
    if i < n and tokens[i] == "}":
        i += 1
    return block, i


def parse_kv(text: str) -> dict[str, Any]:
    """Parse KeyValues text into nested dicts.

    Brace-delimited blocks become nested dicts.  Duplicate keys become lists.
    Recursively handles arbitrary nesting depth.
    """
    tokens = tokenize(text)
    result: dict[str, Any] = {}
    i, n = 0, len(tokens)
    while i < n:
        key = tokens[i].lower()
        i += 1
        if i >= n:
            break
        if tokens[i] == "{":
            block, i = _parse_block(tokens, i + 1)
            if key in result:
                existing = result[key]
                result[key] = existing + [block] if isinstance(existing, list) else [existing, block]
            else:
                result[key] = block
        else:
            val = tokens[i]
            i += 1
            if key in result:
                existing = result[key]
                result[key] = existing + [val] if isinstance(existing, list) else [existing, val]
            else:
                result[key] = val
    return result
