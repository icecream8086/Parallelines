from dataclasses import dataclass, field


@dataclass
class FileRow:
    virtual_path: str
    source_name: str
    source_type: str  # "game" | "vpk" | "addon"
    priority: int
    file_hash: str
    file_size: int
    is_active: bool
    is_dead: bool = False
    is_redundant: bool = False


@dataclass
class DependencyRow:
    from_path: str
    to_path: str
    expected_source: str


@dataclass
class AddonRow:
    addon_id: str
    name: str
    enabled: bool
    priority: int


@dataclass
class HashConflictRow:
    virtual_path: str
    winner_source: str
    loser_source: str
    winner_hash: str
    loser_hash: str


@dataclass
class DepConflictRow:
    from_path: str
    to_path: str
    expected_source: str
    actual_source: str


@dataclass
class IsolatedPackageRow:
    source_name: str
    dead_file_count: int
    example_paths: list[str] = field(default_factory=list)


@dataclass
class ImpactRow:
    virtual_path: str
    source_name: str
    impact_count: int


@dataclass
class EntryPointRow:
    virtual_path: str
    source_type: str  # "manifest" | "map" | "script" | "user_specified"
