"""ManifestCollector: standalone VPK manifest collection for cache validation.

Extracts the VPK-discovery logic from VfsBuilder into a testable unit
with no dependency on VfsBuilder.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from parallelines.game_strategy import GameStrategy

from parallelines.parsers.gameinfo import extract_all_game_dirs

logger = logging.getLogger(__name__)


class ManifestCollector:
    """Scans game directories and addon directories to build a VPK manifest
    for cache validation.

    The manifest contains file metadata (path, mtime, size) so the cache
    layer can detect when VPKs have changed between runs.

    This class is a pure discovery unit -- it performs no VPK parsing,
    has no dependency on ``VfsBuilder``, and can be tested in isolation.
    """

    def __init__(
        self,
        strategy: GameStrategy,
        game_root: Path,
        resolve_path: Callable[[str], Path | None],
    ) -> None:
        self.strategy = strategy
        self.game_root = game_root
        self._resolve_path = resolve_path

    def collect(
        self, search_paths: dict[str, Any], addon_roots: list[str]
    ) -> list[dict]:
        """Build a manifest of all discoverable VPKs for cache validation.

        Iterates game directories (from ``SearchPaths``) and addon
        directories (including workshop) to collect VPK metadata.

        Args:
            search_paths: Parsed ``SearchPaths`` from ``gameinfo.txt``.
            addon_roots: Addon root directories extracted from search paths.

        Returns:
            List of dicts with keys ``source_name``, ``name``, ``path``,
            ``mtime``, ``size``.
        """
        manifest: list[dict] = []
        seen: set[str] = set()

        # Game VPKs from all Game* search paths
        all_game_dirs = extract_all_game_dirs(search_paths)
        for _token, game_dir in all_game_dirs:
            resolved = self._resolve_path(game_dir)
            if resolved is None or not resolved.is_dir():
                continue
            for vpk_file in sorted(resolved.glob(self.strategy.vpk_glob)):
                if str(vpk_file) in seen:
                    continue
                seen.add(str(vpk_file))
                try:
                    st = vpk_file.stat()
                except OSError:
                    continue
                manifest.append(
                    {
                        "source_name": vpk_file.name,
                        "name": vpk_file.name,
                        "path": str(vpk_file),
                        "mtime": st.st_mtime,
                        "size": st.st_size,
                    }
                )

        # Addon VPKs (including workshop)
        for addon_root_dir in dict.fromkeys(addon_roots + ["addons"]):
            resolved = self._resolve_path(addon_root_dir)
            if resolved is None or not resolved.is_dir():
                continue
            for vpk_file in sorted(resolved.glob(self.strategy.addon_vpk_glob)):
                if vpk_file.suffix.lower() != ".vpk":
                    continue
                if str(vpk_file) in seen:
                    continue
                seen.add(str(vpk_file))
                try:
                    st = vpk_file.stat()
                except OSError:
                    continue
                manifest.append(
                    {
                        "source_name": vpk_file.name,
                        "name": vpk_file.name,
                        "path": str(vpk_file),
                        "mtime": st.st_mtime,
                        "size": st.st_size,
                    }
                )

            # Workshop addon VPKs
            if self.strategy.scan_workshop:
                workshop_dir = resolved / "workshop"
                if workshop_dir.is_dir():
                    for vpk_file in sorted(
                        workshop_dir.glob(self.strategy.addon_vpk_glob)
                    ):
                        if vpk_file.suffix.lower() != ".vpk":
                            continue
                        if str(vpk_file) in seen:
                            continue
                        seen.add(str(vpk_file))
                        try:
                            st = vpk_file.stat()
                        except OSError:
                            continue
                        manifest.append(
                            {
                                "source_name": vpk_file.name,
                                "name": vpk_file.name,
                                "path": str(vpk_file),
                                "mtime": st.st_mtime,
                                "size": st.st_size,
                            }
                        )

        return manifest
