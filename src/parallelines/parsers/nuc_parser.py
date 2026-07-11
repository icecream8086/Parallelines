"""Extract dependencies from .nuc files (ICE-encrypted Squirrel source code).

.nuc files in L4D2 (and other Source Engine games) are ICE-encrypted .nut
source. This module decrypts them and extracts dependency references using
the same regex patterns as :mod:`nut_parser`.
"""

from __future__ import annotations

import logging

from parallelines.parsers.ice import IceKey
from parallelines.parsers.nut_parser import extract_nut_dependencies

logger = logging.getLogger(__name__)

# ── Game-specific ICE keys ──────────────────────────────────────────────
# Fallback table used when no key is configured in config.toml.
_DEFAULT_ICE_KEYS: dict[str, str] = {
    "l4d2": "SDhfi878",
    "css": "d7NSuLq2",
    "csgo": "d7NSuLq2",
    "tf2": "E2NcUkG2",
    "dods": "Wl0u5B3F",
    "hl2": "x9Ke0BY7",
    "portal2": "x9Ke0BY7",
}

# Compiled Squirrel bytecode signature (first two bytes).
_CNUT_SIGNATURE = b"\xfa\xfa"


def _get_ice_key() -> str | None:
    """Resolve the ICE key for the current game.

    Priority:
    1. Explicit ``ice_key`` from config.toml (``[toolchain]`` section).
    2. Game ID lookup in :data:`_DEFAULT_ICE_KEYS`.

    Returns:
        The 8-byte ICE key as a string, or ``None`` if no key can be
        determined.
    """
    try:
        from parallelines.config import load_config

        config = load_config()

        # Prefer explicit config key
        if config.toolchain.ice_key:
            return config.toolchain.ice_key

        # Fall back to game ID lookup
        game = config.general.game
        if game and game.lower() in _DEFAULT_ICE_KEYS:
            return _DEFAULT_ICE_KEYS[game.lower()]
    except Exception:
        logger.debug("Failed to load config for ICE key resolution", exc_info=True)
    return None


def extract_nuc_dependencies(file_content: bytes) -> set[str]:
    """Decrypt an ICE-encrypted ``.nuc`` and extract dependency references.

    Args:
        file_content: Raw bytes of the ``.nuc`` file.

    Returns:
        Set of resolved dependency paths (same format as
        :func:`.nut_parser.extract_nut_dependencies`). Returns an empty set
        when the file is not an ICE-encrypted script (compiled bytecode),
        when no ICE key is available, or on any parse failure.
    """
    # ── Detect compiled Squirrel bytecode (0xFAFA header) ────────────
    if file_content[:2] == _CNUT_SIGNATURE:
        logger.debug("Compiled Squirrel bytecode (.cnut) detected — skipping ICE decrypt")
        return set()

    key = _get_ice_key()
    if key is None:
        logger.debug("No ICE key configured — .nuc files will not be parsed")
        return set()

    try:
        decrypted = IceKey.decrypt_buffer(file_content, key.encode("ascii"))
        text = decrypted.decode("utf-8", errors="replace")
        return extract_nut_dependencies(text)
    except Exception as exc:
        logger.warning("Failed to parse .nuc file: %s", exc)
        return set()
