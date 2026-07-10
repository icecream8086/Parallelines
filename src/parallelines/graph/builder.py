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

# File extensions whose content we actually read to extract deps.
_TEXT_EXTENSIONS: frozenset[str] = frozenset({".vmt", ".txt", ".nut", ".mdl", ".bsp"})


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
            elif ext == ".txt" and is_manifest_path(node.virtual_path):
                deps = self._extract_manifest_deps(node)
            elif ext == ".bsp" and HAS_BSP:
                deps = self._extract_bsp_deps(node)
            else:
                continue

            if deps:
                node.dependencies.update(deps)
                edges = [(node.virtual_path, dep) for dep in deps]
                graph.add_edges(edges)

        elapsed = time.perf_counter() - t0
        logger.debug(
            "Graph built in %.2fs: %d nodes, %d edges",
            elapsed,
            graph.node_count,
            graph.edge_count,
        )
        return graph

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
        content = self._read_text(node.virtual_path)
        return extract_nut_dependencies(content) if content else set()

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
        return extract_bsp_dependencies(self.chain, node.virtual_path)

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
