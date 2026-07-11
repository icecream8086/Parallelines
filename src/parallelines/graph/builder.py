"""GraphBuilder — construct dependency graph by extracting references from file content.

Uses ``srctools.filesys.FileSystemChain`` for unified file access across
multiple VPKs and loose directories, supporting:

- ``.vmt`` → ``$basetexture`` / ``$bumpmap`` / ``$normalmap`` references
- ``.mdl`` → material / texture references via ``srctools.mdl.Model.iter_textures()``
- ``.nut`` → ``IncludeScript("...")`` / ``PrecacheModel("...")`` calls
- manifest ``.txt`` → included resource paths
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from parallelines.graph.deps import DependencyGraph
from parallelines.parsers.manifest_parser import is_manifest_path
from parallelines.parsers.vmt_parser import extract_vmt_dependencies

logger = logging.getLogger(__name__)

# Lazy imports for srctools-dependent parsers (optional).
try:
    from parallelines.parsers.mdl_parser import extract_mdl_dependencies

    HAS_MDL = True
except ImportError:
    HAS_MDL = False

try:
    from parallelines.parsers.nut_parser import extract_nut_dependencies

    HAS_NUT = True
except ImportError:
    HAS_NUT = False

try:
    from parallelines.parsers.bsp_parser import extract_bsp_dependencies

    HAS_BSP = True
except ImportError:
    HAS_BSP = False

try:
    from parallelines.parsers.bsp_pakfile import scan_bsp_scripts

    HAS_BSP_PAKFILE = True
except ImportError:
    HAS_BSP_PAKFILE = False

# Lazy imports for new parsers (parser-audit-fix.md ss1-2).
try:
    from parallelines.parsers.game_sounds_parser import extract_game_sounds_dependencies

    HAS_GAME_SOUNDS = True
except ImportError:
    HAS_GAME_SOUNDS = False

try:
    from parallelines.parsers.soundscapes_parser import extract_soundscapes_dependencies

    HAS_SOUNDSCAPES = True
except ImportError:
    HAS_SOUNDSCAPES = False

try:
    from parallelines.parsers.level_sounds_parser import extract_level_sounds_dependencies

    HAS_LEVEL_SOUNDS = True
except ImportError:
    HAS_LEVEL_SOUNDS = False

try:
    from parallelines.parsers.population_parser import extract_population_dependencies

    HAS_POPULATION = True
except ImportError:
    HAS_POPULATION = False

try:
    from parallelines.parsers.melee_parser import extract_melee_dependencies

    HAS_MELEE = True
except ImportError:
    HAS_MELEE = False

try:
    from parallelines.parsers.missions_parser import extract_missions_dependencies

    HAS_MISSIONS = True
except ImportError:
    HAS_MISSIONS = False

try:
    from parallelines.parsers.pcf_parser import extract_pcf_dependencies

    HAS_PCF = True
except ImportError:
    HAS_PCF = False

try:
    from parallelines.parsers.res_parser import extract_res_dependencies

    HAS_RES = True
except ImportError:
    HAS_RES = False

try:
    from parallelines.parsers.weapon_parser import extract_weapon_dependencies

    HAS_WEAPON = True
except ImportError:
    HAS_WEAPON = False

try:
    from parallelines.parsers.nuc_parser import extract_nuc_dependencies

    HAS_NUC = True
except ImportError:
    HAS_NUC = False

try:
    from parallelines.parsers.ani_parser import extract_ani_dependencies

    HAS_ANI = True
except ImportError:
    HAS_ANI = False

try:
    from parallelines.parsers.texture_list_parser import extract_texture_list_dependencies

    HAS_TEXTURE_LIST = True
except ImportError:
    HAS_TEXTURE_LIST = False

try:
    import importlib.util
    HAS_SIMPLE_LIST = importlib.util.find_spec("parallelines.parsers.simple_list_parser") is not None
except Exception:
    HAS_SIMPLE_LIST = False

# File extensions whose content we actually read to extract deps.
_TEXT_EXTENSIONS: frozenset[str] = frozenset({
    ".vmt", ".txt", ".nut", ".mdl", ".bsp", ".res", ".pcf", ".nuc", ".ani",
})


class GraphBuilder:
    """Construct dependency graph by reading active files and extracting references.

    Accepts a :class:`srctools.filesys.FileSystemChain` (or compatible) for
    reading file content from combined VPKs / loose directories.

    When *chain* is ``None`` (testing or missing srctools), only
    :attr:`FileNode.dependencies` that were pre-populated during VFS building
    are used; no on-demand file reading occurs.
    """

    def __init__(self, chain, vfs, debug: bool = False) -> None:
        self.chain = chain
        self.vfs = vfs
        self.debug = debug

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def build_from_cached(vfs) -> DependencyGraph:
        """Build graph directly from cached ``node.dependencies`` — zero I/O.

        Used when VFS was restored from SSD cache and every active
        :class:`~parallelines.types.FileNode` already has its dependency set
        populated from ``dependencies.parquet``.
        """
        graph = DependencyGraph()
        for node in vfs.get_all_active():
            if node.is_redundant:
                continue
            # Leaf nodes (no out-edges) are still added so ancestors_of queries work.
            graph.add_node(node.virtual_path)
            if node.dependencies:
                graph.add_edges(
                    [(node.virtual_path, dep) for dep in node.dependencies]
                )
        logger.debug(
            "Graph built from cache: %d nodes, %d edges",
            graph.node_count,
            graph.edge_count,
        )
        return graph

    def build(self) -> DependencyGraph:
        """Iterate all active files, extract dependencies, build graph.

        Returns a populated :class:`DependencyGraph`.
        """
        t0 = time.perf_counter()
        graph = DependencyGraph()

        for node in self.vfs.get_all_active():
            # Safety guard: skip any residual redundant nodes
            if node.is_redundant:
                continue

            # All active nodes are added to the graph (including leaves).
            graph.add_node(node.virtual_path)

            ext = Path(node.virtual_path).suffix.lower()

            if ext == ".vmt":
                deps = self._extract_vmt_deps(node)
            elif ext == ".mdl" and HAS_MDL:
                deps = self._extract_mdl_deps(node)
            elif ext == ".nut" and HAS_NUT:
                deps = self._extract_nut_deps(node)
            elif ext == ".txt":
                lower = node.virtual_path.lower()
                if is_manifest_path(node.virtual_path):
                    deps = self._extract_manifest_deps(node)
                elif "game_sounds" in lower and HAS_GAME_SOUNDS:
                    deps = self._extract_game_sounds_deps(node)
                elif "soundscapes" in lower and HAS_SOUNDSCAPES:
                    deps = self._extract_soundscapes_deps(node)
                elif lower.endswith("_level_sounds.txt") and HAS_LEVEL_SOUNDS:
                    deps = self._extract_level_sounds_deps(node)
                elif lower.endswith("population.txt") and HAS_POPULATION:
                    deps = self._extract_population_deps(node)
                elif lower.startswith("missions/") and HAS_MISSIONS:
                    deps = self._extract_missions_deps(node)
                elif lower.startswith("scripts/melee/") and HAS_MELEE:
                    deps = self._extract_melee_deps(node)
                elif lower.startswith("scripts/weapon_") and "manifest" not in lower and HAS_WEAPON:
                    deps = self._extract_weapon_deps(node)
                elif lower in ("scripts/hud_textures.txt", "scripts/mod_textures.txt") and HAS_TEXTURE_LIST:
                    deps = self._extract_texture_list_deps(node)
                elif lower.endswith("sound_prefetch.txt"):
                    deps = self._extract_sound_prefetch_deps(node)
                elif lower.endswith("level_sounds_general.txt") and HAS_LEVEL_SOUNDS:
                    deps = self._extract_level_sounds_deps(node)
                elif lower in ("scripts/soundmixers.txt", "scripts/propdata.txt"):
                    deps = self._extract_kv_sound_deps(node)
                else:
                    deps = set()
            elif ext == ".pcf" and HAS_PCF:
                deps = self._extract_pcf_deps(node)
            elif ext == ".res" and HAS_RES:
                deps = self._extract_res_deps(node)
            elif ext == ".nuc" and HAS_NUC:
                deps = self._extract_nuc_deps(node)
            elif ext == ".ani" and HAS_ANI:
                deps = self._extract_ani_deps(node)
            elif ext == ".bsp" and HAS_BSP:
                deps = self._extract_bsp_deps(node)
            else:
                continue

            if deps:
                node.dependencies.update(deps)
                edges = [(node.virtual_path, dep) for dep in deps]
                graph.add_edges(edges)

        # Add synthetic edges after all file parsing is complete.
        self._add_map_audio_edges(graph, self.vfs)
        self._add_phy_edges(graph, self.vfs)

        elapsed = time.perf_counter() - t0
        logger.debug(
            "Graph built in %.2fs: %d nodes, %d edges",
            elapsed,
            graph.node_count,
            graph.edge_count,
        )
        return graph

    def build_parallel(
        self,
        vfs,
        source_paths: dict[str, str] | None = None,
        num_workers: int = 0,
    ) -> DependencyGraph:
        """Build graph using pre-read + parallel parsing approach.

        Phase A: Pre-read all text/binary content through chain (main process).
        Phase B: Submit pre-read content to multiprocessing Pool for parsing.
        Phase C: Process .mdl/.bsp files sequentially (they need the chain).
        Phase D: Merge all results and add synthetic edges.

        This avoids the complexity of per-worker VPK open logic while still
        parallelising CPU-bound parser work (~90% of total time).
        """
        import os
        import time
        from multiprocessing import Pool

        if num_workers == 0:
            num_workers = max(1, (os.cpu_count() or 2) - 1)

        t0 = time.perf_counter()
        graph = DependencyGraph()

        # Add all nodes to graph first (fast, no I/O)
        for node in vfs.get_all_active():
            if node.is_redundant:
                continue
            graph.add_node(node.virtual_path)

        # Phase A: Pre-read file content
        _TEXT_EXTENSIONS: frozenset[str] = frozenset({".vmt", ".txt", ".res", ".ani"})
        _BIN_EXTENSIONS: frozenset[str] = frozenset({".pcf", ".nuc"})

        file_batch: list[tuple[str, str, bytes]] = []
        mdl_bsp_files: list = []

        for node in vfs.get_all_active():
            if node.is_redundant:
                continue
            ext = Path(node.virtual_path).suffix.lower()
            if ext == ".mdl":
                mdl_bsp_files.append(node)
            elif ext == ".bsp":
                mdl_bsp_files.append(node)
            elif ext == ".nut":
                raw = self._read_bytes(node.virtual_path)
                if raw:
                    if raw[:2] == b"\xfa\xfa":
                        logger.debug(
                            "Squirrel bytecode (.cnut) in %s — skipping",
                            node.virtual_path,
                        )
                        continue
                    content = raw.decode("utf-8", errors="replace")
                    file_batch.append((node.virtual_path, ext, content.encode("utf-8", errors="replace")))
            elif ext in _TEXT_EXTENSIONS:
                content = self._read_text(node.virtual_path)
                if content:
                    file_batch.append((node.virtual_path, ext, content.encode("utf-8", errors="replace")))
            elif ext in _BIN_EXTENSIONS:
                content = self._read_bytes(node.virtual_path)
                if content:
                    file_batch.append((node.virtual_path, ext, content))

        logger.info(
            "Pre-read %d files for parallel parsing (%d .mdl/.bsp remain sequential)",
            len(file_batch),
            len(mdl_bsp_files),
        )

        # Phase B + C: Parse in parallel, then sequential .mdl/.bsp
        results: list[tuple[str, list[str]]] = []

        # Lazy import worker to avoid circular imports
        try:
            from parallelines.graph.worker import parse_file_worker
        except ImportError:
            # Fallback worker for when the module doesn't exist yet
            parse_file_worker = None

        if parse_file_worker is not None and len(file_batch) >= 10:
            with Pool(num_workers) as pool:
                for worker_result in pool.imap_unordered(parse_file_worker, file_batch):
                    results.extend(worker_result)
        else:
            # Fallback: sequential in-process parsing
            for vp, ext, content in file_batch:
                deps = self._parse_file_content(vp, ext, content)
                if deps:
                    results.append((vp, list(deps)))

        # Phase C: .mdl/.bsp sequential
        for node in mdl_bsp_files:
            if node.virtual_path.lower().endswith(".mdl") and HAS_MDL:
                deps = self._extract_mdl_deps(node)
            elif HAS_BSP:
                deps = self._extract_bsp_deps(node)
            else:
                continue
            if deps:
                results.append((node.virtual_path, list(deps)))

        # Phase D: Merge results into graph
        for vp, deps_list in results:
            node = vfs.get_active_file(vp)
            if node:
                node.dependencies.update(deps_list)
                graph.add_edges([(vp, dep) for dep in deps_list])

        # Add synthetic map -> audio edges
        self._add_map_audio_edges(graph, vfs)

        # Add synthetic .mdl -> .phy edges
        self._add_phy_edges(graph, vfs)

        elapsed = time.perf_counter() - t0
        logger.info(
            "Graph built in %.1fs (parallel): %d nodes, %d edges",
            elapsed,
            graph.node_count,
            graph.edge_count,
        )
        return graph

    def _parse_file_content(self, virtual_path: str, ext: str, content: bytes) -> set[str]:
        """Parse a single file's content, dispatching by extension.

        Used by build_parallel fallback path when the worker module is not available.
        """
        from parallelines.parsers.manifest_parser import is_manifest_path
        from parallelines.parsers.vmt_parser import extract_vmt_dependencies

        if ext == ".vmt":
            return extract_vmt_dependencies(content.decode("utf-8", errors="replace"))
        if ext == ".nut" and HAS_NUT:
            text = content.decode("utf-8", errors="replace")
            return extract_nut_dependencies(text)
        if ext == ".txt":
            text = content.decode("utf-8", errors="replace")
            lower = virtual_path.lower()
            if is_manifest_path(virtual_path):
                deps: set[str] = set()
                for line in text.splitlines():
                    s = line.strip()
                    if s and not s.startswith(("//", "#")):
                        deps.add(s)
                return deps
            if "game_sounds" in lower and HAS_GAME_SOUNDS:
                return extract_game_sounds_dependencies(text)
            if "soundscapes" in lower and HAS_SOUNDSCAPES:
                return extract_soundscapes_dependencies(text)
            if lower.endswith("_level_sounds.txt") and HAS_LEVEL_SOUNDS:
                return extract_level_sounds_dependencies(text)
            if lower.endswith("population.txt") and HAS_POPULATION:
                return extract_population_dependencies(text)
            if lower.startswith("missions/") and HAS_MISSIONS:
                return extract_missions_dependencies(text)
            if lower.startswith("scripts/melee/") and HAS_MELEE:
                return extract_melee_dependencies(text)
            if lower.startswith("scripts/weapon_") and "manifest" not in lower and HAS_WEAPON:
                return extract_weapon_dependencies(text)
            if lower in ("scripts/hud_textures.txt", "scripts/mod_textures.txt") and HAS_TEXTURE_LIST:
                return extract_texture_list_dependencies(text)
            if lower.endswith("sound_prefetch.txt"):
                deps = set()
                for line in text.splitlines():
                    s = line.strip()
                    if s and not s.startswith(("//", "#")):
                        path = s.replace("\\", "/")
                        if not path.lower().startswith("sound/"):
                            path = "sound/" + path
                        deps.add(path)
                return deps
            if lower.endswith("level_sounds_general.txt") and HAS_LEVEL_SOUNDS:
                return extract_level_sounds_dependencies(text)
            if lower in ("scripts/soundmixers.txt", "scripts/propdata.txt"):
                deps = set()
                for line in text.splitlines():
                    s = line.strip()
                    if not s or s.startswith(("//", "#", "{")):
                        continue
                    for token in s.split('"'):
                        t = token.strip().replace("\\", "/")
                        if t.lower().endswith((".wav", ".phy")):
                            if t.lower().endswith(".wav") and not t.lower().startswith("sound/"):
                                t = "sound/" + t
                            deps.add(t)
                return deps
            return set()
        if ext == ".res" and HAS_RES:
            return extract_res_dependencies(content.decode("utf-8", errors="replace"))
        if ext == ".pcf" and HAS_PCF:
            return extract_pcf_dependencies(content)
        if ext == ".nuc" and HAS_NUC:
            return extract_nuc_dependencies(content)
        if ext == ".ani" and HAS_ANI:
            return extract_ani_dependencies(content.decode("utf-8", errors="replace"))
        return set()

    # ------------------------------------------------------------------
    # Per-file-type extraction helpers
    # ------------------------------------------------------------------

    def _extract_vmt_deps(self, node) -> set[str]:
        content = self._read_text(node.virtual_path)
        return extract_vmt_dependencies(content) if content else set()

    def _extract_mdl_deps(self, node) -> set[str]:
        if self.chain is None:
            return set()
        return extract_mdl_dependencies(self.chain, node.virtual_path)

    def _extract_nut_deps(self, node) -> set[str]:
        # Read raw bytes first — detect compiled Squirrel bytecode (0xFAFA)
        # that a mod author could ship inside a .nut file.
        raw = self._read_bytes(node.virtual_path)
        if raw is None:
            return set()
        if raw[:2] == b"\xfa\xfa":
            logger.debug(
                "Squirrel bytecode (.cnut) in %s — literal extraction not supported",
                node.virtual_path,
            )
            return set()
        content = raw.decode("utf-8", errors="replace")
        return extract_nut_dependencies(content)

    def _extract_manifest_deps(self, node) -> set[str]:
        content = self._read_text(node.virtual_path)
        if content is None:
            return set()
        try:
            deps: set[str] = set()
            for line in content.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith(("//", "#")):
                    continue
                deps.add(stripped)
            return deps
        except Exception as exc:
            logger.warning("Failed to parse manifest %s: %s", node.virtual_path, exc)
            return set()

    def _extract_bsp_deps(self, node) -> set[str]:
        if self.chain is None:
            return set()
        deps = extract_bsp_dependencies(self.chain, node.virtual_path)
        if HAS_BSP_PAKFILE:
            try:
                bsp_data = self._read_bytes(node.virtual_path)
                if bsp_data:
                    script_deps = scan_bsp_scripts(bsp_data)
                    deps |= script_deps
            except Exception:
                pass
        return deps

    # ------------------------------------------------------------------
    # File reading via chain
    # ------------------------------------------------------------------

    def _read_text(self, virtual_path: str) -> str | None:
        """Read a text file through the FileSystemChain.

        Returns ``None`` if the chain is unavailable or the path is not found.
        """
        if self.chain is None:
            return None
        try:
            file_obj = self.chain[virtual_path]
            return file_obj.open_str().read()
        except Exception:
            return None

    def _read_bytes(self, virtual_path: str) -> bytes | None:
        """Read a binary file through the FileSystemChain."""
        if self.chain is None:
            return None
        try:
            file_obj = self.chain[virtual_path]
            return file_obj.open_bin().read()
        except Exception:
            return None

    # ------------------------------------------------------------------
    # New parser extraction helpers (parser-audit-fix.md sect;4.3)
    # ------------------------------------------------------------------

    def _extract_game_sounds_deps(self, node) -> set[str]:
        content = self._read_text(node.virtual_path)
        return extract_game_sounds_dependencies(content) if content else set()

    def _extract_soundscapes_deps(self, node) -> set[str]:
        content = self._read_text(node.virtual_path)
        return extract_soundscapes_dependencies(content) if content else set()

    def _extract_level_sounds_deps(self, node) -> set[str]:
        content = self._read_text(node.virtual_path)
        return extract_level_sounds_dependencies(content) if content else set()

    def _extract_population_deps(self, node) -> set[str]:
        content = self._read_text(node.virtual_path)
        return extract_population_dependencies(content) if content else set()

    def _extract_melee_deps(self, node) -> set[str]:
        content = self._read_text(node.virtual_path)
        return extract_melee_dependencies(content) if content else set()

    def _extract_missions_deps(self, node) -> set[str]:
        content = self._read_text(node.virtual_path)
        return extract_missions_dependencies(content) if content else set()

    def _extract_pcf_deps(self, node) -> set[str]:
        content = self._read_bytes(node.virtual_path)
        return extract_pcf_dependencies(content) if content else set()

    def _extract_res_deps(self, node) -> set[str]:
        content = self._read_text(node.virtual_path)
        return extract_res_dependencies(content) if content else set()

    def _extract_weapon_deps(self, node) -> set[str]:
        content = self._read_text(node.virtual_path)
        return extract_weapon_dependencies(content) if content else set()

    def _extract_texture_list_deps(self, node) -> set[str]:
        content = self._read_text(node.virtual_path)
        return extract_texture_list_dependencies(content) if content else set()

    def _extract_sound_prefetch_deps(self, node) -> set[str]:
        """Parse sound_prefetch.txt -- one sound path per line."""
        content = self._read_text(node.virtual_path)
        if not content:
            return set()
        deps: set[str] = set()
        for line in content.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith(("//", "#")):
                path = stripped.replace("\\", "/")
                if not path.lower().startswith("sound/"):
                    path = "sound/" + path
                deps.add(path)
        return deps

    def _extract_nuc_deps(self, node) -> set[str]:
        content = self._read_bytes(node.virtual_path)
        return extract_nuc_dependencies(content) if content else set()

    def _extract_ani_deps(self, node) -> set[str]:
        content = self._read_text(node.virtual_path)
        return extract_ani_dependencies(content) if content else set()

    def _extract_kv_sound_deps(self, node) -> set[str]:
        """Extract .wav / .phy references from soundmixers.txt or propdata.txt."""
        content = self._read_text(node.virtual_path)
        if not content:
            return set()
        deps: set[str] = set()
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(("//", "#", "{")):
                continue
            for token in stripped.split('"'):
                token = token.strip().replace("\\", "/")
                if token.lower().endswith((".wav", ".phy")):
                    if token.lower().endswith(".wav") and not token.lower().startswith("sound/"):
                        token = "sound/" + token
                    deps.add(token)
        return deps

    # ------------------------------------------------------------------
    # Synthetic map -> audio edges (parser-audit-fix.md sect;11.2b)
    # ------------------------------------------------------------------

    def _add_map_audio_edges(self, graph, vfs) -> None:
        """Add synthetic edges: .bsp -> _level_sounds.txt + soundscapes_<mapname>.txt.

        The engine auto-loads these files when loading a map, but the relationship
        is by filename convention, not by file content reference.
        """
        for node in vfs.get_all_active():
            if node.is_redundant:
                continue
            path = node.virtual_path
            if not path.lower().endswith(".bsp"):
                continue
            map_name = Path(path).stem
            ls_path = f"maps/{map_name}_level_sounds.txt"
            if vfs.get_active_file(ls_path):
                graph.add_edges([(path, ls_path)])
                node.dependencies.add(ls_path)
            ss_path = f"scripts/soundscapes_{map_name}.txt"
            if vfs.get_active_file(ss_path):
                graph.add_edges([(path, ss_path)])
                node.dependencies.add(ss_path)

    def _add_phy_edges(self, graph, vfs) -> None:
        """Add synthetic .mdl -> .phy edges (by naming convention)."""
        for node in vfs.get_all_active():
            if node.is_redundant:
                continue
            path = node.virtual_path
            if not path.lower().endswith(".mdl"):
                continue
            phy_path = path[:-4] + ".phy"
            if vfs.get_active_file(phy_path):
                graph.add_edges([(path, phy_path)])
                node.dependencies.add(phy_path)
