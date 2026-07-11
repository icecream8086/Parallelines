"""AddonPrioritizer: handles addon VPK priority sorting and assignment.

This module extracts the priority allocation logic from ``VfsBuilder`` into
a standalone, testable class. It does not perform any I/O and has no
dependency on ``VfsBuilder``.
"""

from __future__ import annotations

from pathlib import Path


class AddonPrioritizer:
    """Allocates priorities to addon VPK entries based on addonlist ordering
    and the configured priority direction.

    The Source engine mounts addon VPKs alphabetically by name. Entries listed
    in ``addonlist.txt`` take precedence over unlisted entries. Within each
    group the sorting follows the configured direction (ascending/descending).

    This class is a pure computation unit -- it does not perform any I/O,
    does not depend on ``VfsBuilder``, and can be tested in isolation.
    """

    def __init__(
        self,
        priority_direction: str,
        addonlist: dict[str, tuple[bool, int]] | None = None,
    ) -> None:
        """Initialize the prioritizer.

        Args:
            priority_direction: ``"ascending"`` or ``"descending"``.
            addonlist: Mapping of ``vpk_name -> (is_enabled, line_order)``
                as returned by ``VfsBuilder._read_addonlist()``.
        """
        self.priority_direction = priority_direction
        self.addonlist: dict[str, tuple[bool, int]] = (
            addonlist if addonlist is not None else {}
        )

    def sort_and_assign(
        self,
        addon_vpks: list[tuple[Path, bool, bool, int | None]],
    ) -> list[tuple[str, str, int, bool]]:
        """Sort addon VPK entries and assign numeric priorities.

        Separates entries into two groups -- those with an explicit addonlist
        order and those without -- sorts each group according to the configured
        direction, then assigns monotonically increasing (or decreasing)
        numeric priorities.

        Args:
            addon_vpks: List of ``(path, is_disabled, from_workshop,
                addonlist_order)`` tuples collected from addon directories.

        Returns:
            List of ``(path_str, name, priority, is_disabled)`` tuples ready
            for VPK ingestion.
        """
        # Separate into addonlist and non-addonlist groups
        addonlist_items = [x for x in addon_vpks if x[3] is not None]
        non_items = [x for x in addon_vpks if x[3] is None]

        # Sort addonlist items by line order (ascending = higher priority)
        addonlist_items.sort(key=lambda x: x[3])  # type: ignore[arg-type]

        # Sort non-items alphabetically; direction determines which end
        # of the sorted list receives the highest priority.
        if self.priority_direction == "descending":
            non_items.sort(key=lambda x: x[0].name.lower(), reverse=True)
        else:
            non_items.sort(key=lambda x: x[0].name.lower())

        addon_vpks_sorted = addonlist_items + non_items

        result: list[tuple[str, str, int, bool]] = []
        if self.priority_direction == "descending":
            total = len(addon_vpks_sorted)
            for idx, (vpk_path, is_disabled, _from_ws, _order) in enumerate(
                addon_vpks_sorted
            ):
                priority = 1000 + (total - idx)
                result.append((str(vpk_path), vpk_path.name, priority, is_disabled))
        else:
            priority = 1000
            for vpk_path, is_disabled, _from_ws, _order in addon_vpks_sorted:
                result.append((str(vpk_path), vpk_path.name, priority, is_disabled))
                priority -= 1

        return result
