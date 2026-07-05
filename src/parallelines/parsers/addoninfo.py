"""Parse addoninfo.txt — extract addon metadata and dependency declarations.

Supports standard L4D2-style addoninfo.txt VDF format with an optional
``"dependencies"`` block listing Workshop IDs.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    from srctools.keyvalues import Keyvalues as _Keyvalues

    SRCTOOLS_AVAILABLE = True
except ImportError:
    SRCTOOLS_AVAILABLE = False
    _Keyvalues: Any = None  # type: ignore[no-redef]


def parse_addoninfo(content: str) -> dict[str, Any]:
    """Parse addoninfo.txt content and return a metadata dictionary.

    The returned dict contains the following keys (when present):

    - ``addon_name`` — human-readable addon name
    - ``addon_id`` — unique addon identifier (typically a numeric string)
    - ``addon_description`` — description text
    - ``addon_url`` — URL string
    - ``addon_version`` — version string
    - ``dependencies`` — list of dependency dicts, each with optional keys
      such as ``workshop_id``

    When ``srctools.keyvalues`` is not available the function returns an empty
    dict and issues a warning.

    Args:
        content: Raw text content of an addoninfo.txt file.

    Returns:
        A dict of parsed metadata (may be empty on parse failure).
    """
    if not SRCTOOLS_AVAILABLE:
        logger.warning("srctools not available; addoninfo.txt parsing disabled")
        return {}

    if not content.strip():
        return {}

    try:
        kv = _Keyvalues.parse(content)
        return _kv_addoninfo_to_dict(kv)
    except Exception as exc:
        logger.debug("Failed to parse addoninfo.txt: %s", exc)
        return {}


def _kv_addoninfo_to_dict(kv: Any) -> dict[str, Any]:
    """Convert a Keyvalues tree to a flat addon metadata dict.

    ``Keyvalues.parse()`` returns a virtual root whose children are the named
    blocks in the file (e.g. ``"addoninfo.txt"``).  This function iterates
    over each named block and flattens its children into a single dict.
    Sub-blocks such as ``"dependencies"`` become lists of dicts.
    """
    result: dict[str, Any] = {}

    try:
        # The parsed KV is a virtual root.  Iterating yields each named block
        # (e.g. the "addoninfo.txt" block).
        for block in kv:
            if not hasattr(block, "value") or not isinstance(block.value, list):
                continue

            # Process children of this block (addon_name, addon_id, etc.)
            for child in block.value:
                if not hasattr(child, "name"):
                    continue
                name = str(child.name).lower()

                if hasattr(child, "value") and isinstance(child.value, list):
                    # Sub-block (e.g. "dependencies")
                    items: list[dict[str, str]] = []
                    for sub in child.value:
                        item: dict[str, str] = {}
                        if hasattr(sub, "name"):
                            sub_val = (
                                str(sub.value)
                                if hasattr(sub, "value")
                                and not isinstance(sub.value, list)
                                else ""
                            )
                            item[str(sub.name)] = sub_val
                        if item:
                            items.append(item)
                    result[name] = items
                else:
                    value = str(child.value) if hasattr(child, "value") else ""
                    result[name] = value
    except Exception as exc:
        logger.debug("Error converting Keyvalues to addoninfo dict: %s", exc)

    return result


def parse_addoninfo_file(path: str | Path) -> dict[str, Any]:
    """Read and parse an addoninfo.txt file from disk.

    Args:
        path: Filesystem path to the addoninfo.txt file.

    Returns:
        Parsed metadata dict (empty on failure).
    """
    path_obj = Path(path)
    if not path_obj.exists():
        logger.debug("addoninfo.txt not found: %s", path)
        return {}

    try:
        content = path_obj.read_text(encoding="utf-8", errors="replace")
        return parse_addoninfo(content)
    except Exception as exc:
        logger.debug("Failed to read addoninfo.txt at %s: %s", path, exc)
        return {}


def extract_dependency_ids(addon_meta: dict[str, Any]) -> list[str]:
    """Extract dependency Workshop IDs from parsed addoninfo metadata.

    Args:
        addon_meta: Dict returned by :func:`parse_addoninfo`.

    Returns:
        A list of dependency identifier strings (e.g. ``["0987654321"]``).
    """
    dep_ids: list[str] = []
    try:
        deps = addon_meta.get("dependencies", [])
        if isinstance(deps, list):
            for dep in deps:
                if isinstance(dep, dict):
                    wid = dep.get("workshop_id", "")
                    if wid:
                        dep_ids.append(str(wid))
    except Exception as exc:
        logger.debug("Failed to extract dependency IDs: %s", exc)
    return dep_ids
