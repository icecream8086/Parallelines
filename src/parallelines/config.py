from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from parallelines.exceptions import ConfigError

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]


@dataclass
class GeneralConfig:
    game: str = ""  # Source Engine game ID: l4d2, csgo, tf2, portal2, dota2, ...
    game_root: str = ""
    gameinfo_path: str = ""
    cache_dir: str = ""  # "" = resolved by default_cache_dir()
    enable_cache: bool = True
    cache_strategy: str = "mtime"
    num_workers: int = 0  # 0 = auto (cpu_count - 1), 1 = single, N = specific
    memory_limit: str = ""  # e.g. "4GB", "2048MB", "" = auto, "0" = no limit
    io_limit: int = 2  # max concurrent I/O operations (0 = unlimited)
    nolimit: bool = False  # bypass all resource limits, use maximum available
    log_level: str = "INFO"


@dataclass
class AnalysisConfig:
    detect_redundant: bool = True
    detect_dead: bool = True
    detect_hash_conflicts: bool = True
    detect_dependency_conflicts: bool = True
    detect_isolated_packages: bool = True
    compute_impact: bool = False
    include_disabled_addons: bool = False


@dataclass
class EntryPointsConfig:
    auto_manifests: bool = True
    all_maps_as_entries: bool = True
    custom_entries: list[str] = field(default_factory=list)
    use_pure_server_whitelist: bool = False
    pure_server_whitelist_path: str = ""


@dataclass
class AddonsConfig:
    parse_fireaxe: bool = False
    fireaxe_json_path: str = ""
    parse_addoninfo: bool = True
    addon_state_source: str = "addonlist"
    addonlist_path: str = ""  # empty string = use GameStrategy default


@dataclass
class OutputConfig:
    format: str = "json"
    output_dir: str = "./reports"
    include_dependency_chain: bool = True
    generate_graphviz: bool = False


@dataclass
class ToolchainConfig:
    sq_path: str = ""  # path to Squirrel compiler/decompiler binary (deprecated)
    ice_key: str = ""  # ICE decryption key; "" = auto-detect from game ID


@dataclass
class AppConfig:
    general: GeneralConfig = field(default_factory=GeneralConfig)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    entry_points: EntryPointsConfig = field(default_factory=EntryPointsConfig)
    addons: AddonsConfig = field(default_factory=AddonsConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    toolchain: ToolchainConfig = field(default_factory=ToolchainConfig)


def default_cache_dir() -> str:
    """Return the platform-appropriate default cache directory.

    Frozen (PyInstaller exe):
        ``%LOCALAPPDATA%/parallelines/cache`` (Windows) or
        ``~/.cache/parallelines`` (Linux/macOS) — persistent, user-local,
        and never affected by the exe's install location.

    Development:
        ``./cache`` — CWD-relative, keeps the cache next to the source tree.
    """
    if getattr(sys, "frozen", False):
        if sys.platform == "win32":
            base = (os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or "").strip()
            if base:
                return str(Path(base) / "parallelines" / "cache")
            # ponytail: temp dir, unlikely to hit given Windows always sets APPDATA
            return str(Path(tempfile.gettempdir()) / "parallelines" / "cache")
        # Linux / macOS
        return str(Path.home() / ".cache" / "parallelines")
    return "./cache"


def load_config(config_path: Path | None = None) -> AppConfig:
    """Load config from TOML file, falling back to defaults."""
    config = AppConfig()

    if config_path is None:
        # Frozen exe: try next to exe first, then CWD.
        # Dev: try CWD first, then script-relative as fallback.
        if getattr(sys, "frozen", False):
            config_path = Path(sys.executable).resolve().parent / "config.toml"
            if not config_path.exists():
                config_path = Path.cwd() / "config.toml"
        else:
            config_path = Path.cwd() / "config.toml"
            if not config_path.exists():
                config_path = Path(__file__).resolve().parent.parent.parent / "config.toml"

    if not config_path.exists():
        return config

    try:
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
    except Exception as e:
        raise ConfigError(f"Failed to parse {config_path}: {e}") from e

    _merge_config(config, data)
    return config


def _merge_config(config: AppConfig, data: dict) -> None:
    """Recursively merge TOML data into AppConfig dataclass fields."""
    for section_name, section_data in data.items():
        if not isinstance(section_data, dict):
            continue
        section_obj = getattr(config, section_name, None)
        if section_obj is None:
            continue
        for key, value in section_data.items():
            if hasattr(section_obj, key):
                setattr(section_obj, key, value)
