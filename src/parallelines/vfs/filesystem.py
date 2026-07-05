"""Virtual file system — overlay resolution and priority stacking."""

from __future__ import annotations

from parallelines.types import FileNode


class VirtualFileSystem:
    """Manages a pool of FileNode objects and resolves active files by priority.

    Multiple FileNodes can share the same virtual_path (from different sources),
    but only the highest-priority enabled one becomes "active". All other nodes
    for the same path are marked as redundant.
    """

    def __init__(self) -> None:
        self._files: dict[str, list[FileNode]] = {}
        self._active: dict[str, FileNode] = {}

    def add_file(self, node: FileNode) -> None:
        """Add a FileNode to the pool.

        The node is stored under its virtual_path. It will be considered during
        the next call to :meth:`resolve`.
        """
        self._files.setdefault(node.virtual_path, []).append(node)

    def resolve(self) -> None:
        """For each virtual_path, pick the enabled FileNode with highest priority.

        The winner is stored in :attr:`_active`; all other FileNodes for the same
        virtual_path are marked with ``is_redundant=True``.

        Paths with no enabled FileNodes are omitted from the active set.
        """
        self._active.clear()
        for virtual_path, nodes in self._files.items():
            enabled = [n for n in nodes if n.is_enabled and not n.is_dead]
            if not enabled:
                continue

            # Pick the node with the highest priority value.
            # In case of a tie the first-encountered node wins.
            winner = max(enabled, key=lambda n: n.priority)

            for n in nodes:
                n.is_redundant = n is not winner

            self._active[virtual_path] = winner

    def get_active_file(self, virtual_path: str) -> FileNode | None:
        """Return the active FileNode for a virtual path, or None if no active file exists."""
        return self._active.get(virtual_path)

    def get_all_active(self) -> list[FileNode]:
        """Return all active (resolved winner) FileNodes."""
        return list(self._active.values())

    def get_all_files(self) -> list[FileNode]:
        """Return all FileNodes in the pool, regardless of active / redundant status."""
        result: list[FileNode] = []
        for nodes in self._files.values():
            result.extend(nodes)
        return result
