"""Generate Graphviz .dot files for dependency graph visualization."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from parallelines.graph.deps import DependencyGraph

logger = logging.getLogger(__name__)

# Colour map by file extension for node grouping
_EXT_COLORS: dict[str, str] = {
    ".vmt": "lightblue",
    ".vtf": "lightgreen",
    ".mdl": "orange",
    ".bsp": "pink",
}

_DEFAULT_COLOR = "lightgrey"


def _node_color(node_id: str) -> str:
    """Return a Graphviz fill colour based on the file extension of *node_id*."""
    for ext, color in _EXT_COLORS.items():
        if node_id.endswith(ext):
            return color
    return _DEFAULT_COLOR


def generate_dot(
    graph: DependencyGraph,
    output_path: str | Path,
    max_nodes: int = 500,
) -> Path:
    """Generate a Graphviz ``.dot`` file from a DependencyGraph.

    The output ``digraph`` uses ``rankdir=LR`` (left-to-right layout) and
    ``concentrate=true`` to merge parallel edges.  Nodes are colour-coded
    by file extension.

    If the graph contains more than *max_nodes* nodes, the top *max_nodes*
    by degree centrality are selected to keep the output manageable.

    Args:
        graph: :class:`~parallelines.graph.deps.DependencyGraph` instance.
        output_path: Destination for the ``.dot`` file.
        max_nodes: Maximum number of nodes to include (default 500).

    Returns:
        Resolved ``Path`` to the generated ``.dot`` file.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    nx_graph = graph.graph
    all_nodes = list(nx_graph.nodes)

    if len(all_nodes) > max_nodes:
        logger.info(
            "Graph has %d nodes, limiting to top %d by degree centrality",
            len(all_nodes),
            max_nodes,
        )
        try:
            import networkx as nx  # type: ignore[import-untyped]

            centrality = nx.degree_centrality(nx_graph)
            sorted_nodes = sorted(
                all_nodes, key=lambda n: centrality.get(n, 0), reverse=True
            )
            selected = set(sorted_nodes[:max_nodes])
        except Exception:
            selected = set(all_nodes[:max_nodes])

        # Build a subgraph view
        sub = nx_graph.subgraph(selected)
        edges = list(sub.edges)
        nodes = selected
    else:
        edges = list(nx_graph.edges)
        nodes = set(all_nodes)

    lines: list[str] = [
        "digraph G {",
        "  rankdir=LR;",
        "  concentrate=true;",
        "  node [style=filled, fontsize=10];",
        "  edge [arrowsize=0.7];",
        "",
    ]

    # Node declarations with colours
    for node in sorted(nodes):
        color = _node_color(node)
        # Escape special characters in node IDs
        safe_id = _escape_dot_id(node)
        lines.append(f'  {safe_id} [fillcolor="{color}"];')

    lines.append("")

    # Edge declarations
    for src, tgt in edges:
        if src in nodes and tgt in nodes:
            safe_src = _escape_dot_id(src)
            safe_tgt = _escape_dot_id(tgt)
            lines.append(f"  {safe_src} -> {safe_tgt};")

    lines.append("}")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info(
        "Graphviz .dot saved to %s (%d nodes, %d edges)",
        output_path,
        len(nodes),
        len(edges),
    )
    return output_path.resolve()


def _escape_dot_id(name: str) -> str:
    """Escape a node name for use as a Graphviz ID.

    Graphviz IDs containing characters other than ``[_a-zA-Z0-9]`` must be
    quoted.  Internal double-quotes are backslash-escaped.
    """
    if not name:
        return '""'
    if name.isidentifier() and not name[0].isdigit():
        return name
    escaped = name.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def render_dot_to_png(dot_path: str | Path, output_path: str | Path) -> Path | None:
    """Render a ``.dot`` file to PNG using the ``dot`` command (if installed).

    Args:
        dot_path: Path to the input ``.dot`` file.
        output_path: Destination path for the rendered PNG.

    Returns:
        Resolved ``Path`` to the PNG, or ``None`` if ``dot`` is not available
        or rendering fails.
    """
    dot_path = Path(dot_path)
    output_path = Path(output_path)

    if not shutil.which("dot"):
        logger.warning("Graphviz 'dot' command not found; skipping PNG rendering")
        return None

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["dot", "-Tpng", str(dot_path), "-o", str(output_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        logger.info("PNG rendered to %s", output_path)
        return output_path.resolve()
    except subprocess.CalledProcessError as exc:
        logger.warning("dot rendering failed (stderr): %s", exc.stderr)
        return None
    except FileNotFoundError:
        logger.warning("Graphviz 'dot' command not found; skipping PNG rendering")
        return None
