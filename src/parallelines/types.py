from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(eq=False)
class FileNode:
    """Represents a single file in the virtual file system.

    Multiple FileNodes can share the same virtual_path (from different sources),
    but only the highest-priority enabled one becomes "active".
    """

    virtual_path: str
    source_type: str  # "game", "vpk", "addon"
    source_name: str  # vpk filename, addon name, or "base"
    source_path: str = ""  # full path to source VPK (disambiguates same-name sources)
    addon_id: Optional[str] = None
    priority: int = 0
    file_size: int = 0
    file_hash: Optional[str] = None
    is_enabled: bool = True
    dependencies: set[str] = field(default_factory=set)
    is_dead: bool = False
    is_redundant: bool = False
    is_disabled_addon: bool = False


@dataclass
class AddonManifest:
    """Parsed addon metadata."""

    addon_id: str
    is_enabled: bool
    priority: int
    name: str


@dataclass
class ConflictRecord:
    """A single conflict found during analysis."""

    conflict_type: str  # "hash_conflict" | "dep_breakage" | "isolated_package"
    involved_vpks: list[str]
    conflict_files: list[dict] = field(default_factory=list)
    dependency_chain: list[str] = field(default_factory=list)
    suggestion: str = ""
