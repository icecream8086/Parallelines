"""Oracle-free tests for parallelines.vfs.builder -- VfsBuilder.

Uses metamorphic relations (Additive, Compositional, Permutative, Differential,
Invertive, Exclusive) instead of asserting expected concrete values.
See devdocs/oracle-free-testing-prompt.md for methodology.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

from parallelines.config import AppConfig
from parallelines.vfs.builder import VfsBuilder, _parse_vpk_worker
from parallelines.vfs.filesystem import VirtualFileSystem
from parallelines.types import FileNode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_builder(
    game_root: str | Path,
    game: str = "",
    num_workers: int = 1,
) -> VfsBuilder:
    """Create a VfsBuilder with caching off and single-process mode."""
    config = AppConfig()
    config.general.game = game
    return VfsBuilder(
        game_root, config=config, use_cache=False, num_workers=num_workers
    )


def _write_addonlist(root: Path, content: str) -> Path:
    """Write *content* as addonlist.txt under *root* and return the path."""
    path = root / "addonlist.txt"
    path.write_text(content, encoding="utf-8")
    return path


# ===================================================================
# _resolve_path
# ===================================================================

class TestResolvePath:
    """Metamorphic relations for VfsBuilder._resolve_path."""

    def test_gameinfo_path_prefix_resolves(self) -> None:
        """MR-Inv: |gameinfo_path|/subdir resolves to an existing path under game_root.

        The |gameinfo_path| prefix is stripped and game_root is prepended.
        Invertive: the prefix 'inverts' a relative subpath into an absolute one.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "maps").mkdir()
            builder = _make_builder(root)

            result = builder._resolve_path("|gameinfo_path|/maps")

            # Postcondition: resolved path exists (the prefix+prepend produced a valid path)
            assert result is not None
            assert result.exists()

    def test_relative_path_resolves(self) -> None:
        """MR-Diff: relative search path resolves to an existing absolute Path.

        Differential: relative resolution is the same operation as explicit
        |gameinfo_path| resolution without the prefix.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "maps").mkdir()
            builder = _make_builder(root)

            result = builder._resolve_path("maps")

            assert result is not None
            assert result.exists()

    def test_nonexistent_returns_none(self) -> None:
        """MR-Add: nonexistent paths return None (safe degenerate).

        Adding a nonexistent path does not crash — the result is simply None.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            builder = _make_builder(root)

            result = builder._resolve_path("|gameinfo_path|/does_not_exist")

            assert result is None


# ===================================================================
# _read_addonlist
# ===================================================================

class TestReadAddonlist:
    """Metamorphic relations for VfsBuilder._read_addonlist."""

    def test_no_file_returns_empty(self) -> None:
        """MR-Add: missing addonlist.txt → empty dict."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            builder = _make_builder(root)
            result = builder._read_addonlist()
            assert len(result) == 0

    def test_empty_file_returns_empty(self) -> None:
        """MR-Add: empty addonlist.txt → empty dict."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_addonlist(root, "")
            builder = _make_builder(root)
            result = builder._read_addonlist()
            assert len(result) == 0

    def test_enabled_entry_maps_to_true(self) -> None:
        """MR-Inv: "name.vpk" TAB "1" → entry with enabled=True."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_addonlist(root, '"test.vpk"\t"1"')
            builder = _make_builder(root)

            result = builder._read_addonlist()

            assert "test.vpk" in result
            enabled, order = result["test.vpk"]
            assert enabled is True
            # First entry should have order 0
            assert order == 0

    def test_disabled_entry_maps_to_false(self) -> None:
        """MR-Inv: "name.vpk" TAB "0" → entry with enabled=False."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_addonlist(root, '"test.vpk"\t"0"')
            builder = _make_builder(root)

            result = builder._read_addonlist()

            assert "test.vpk" in result
            enabled, _ = result["test.vpk"]
            assert enabled is False

    def test_blank_lines_and_spaces_preserve_entries(self) -> None:
        """MR-Add: blank lines and extra whitespace do not change parsed names or state.

        Additive MR: adding noise (blank lines, trailing spaces) to the input produces
        the same parsed result.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_addonlist(
                root,
                '\n\n"a.vpk"\t"1"\n\n"b.vpk"\t"0"\n\n',
            )
            builder = _make_builder(root)

            result = builder._read_addonlist()

            assert len(result) == 2
            assert result["a.vpk"][0] is True
            assert result["b.vpk"][0] is False

    def test_bom_does_not_affect_entries(self) -> None:
        """MR-Perm: UTF-8 BOM prefix does not change parsed result.

        Permutative: adding a BOM prefix before the content is a permutation
        of the byte stream that the parser normalises away.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            content = '"a.vpk"\t"1"'

            # With BOM
            _write_addonlist(root, "﻿" + content)
            builder = _make_builder(root)
            result_with_bom = builder._read_addonlist()

            # Without BOM
            _write_addonlist(root, content)
            result_clean = builder._read_addonlist()

            # MR-Perm: BOM presence should not change keys or enabled state
            assert set(result_with_bom.keys()) == set(result_clean.keys())
            for k in result_with_bom:
                assert result_with_bom[k][0] == result_clean[k][0]

    def test_order_increases_strictly(self) -> None:
        """MR-Perm: entries are assigned strictly increasing order values.

        Permutative: the declaration order in the file is preserved as
        monotonically increasing order numbers.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_addonlist(
                root,
                '"first.vpk"\t"1"\n"second.vpk"\t"1"\n"third.vpk"\t"0"',
            )
            builder = _make_builder(root)

            result = builder._read_addonlist()

            assert len(result) == 3
            orders = [
                result["first.vpk"][1],
                result["second.vpk"][1],
                result["third.vpk"][1],
            ]
            assert orders == [0, 1, 2]


# ===================================================================
# _scan_directory
# ===================================================================

class TestScanDirectory:
    """Metamorphic relations for VfsBuilder._scan_directory."""

    @staticmethod
    def _create_and_scan(
        tmp_root: str,
        file_map: dict[str, str | None],
    ) -> tuple[VfsBuilder, VirtualFileSystem, Path]:
        """Create files per *file_map* and scan the directory.

        Keys are relative paths; values are content (or None for directories).
        Returns (builder, vfs, root).
        """
        root = Path(tmp_root)
        for relpath, content in file_map.items():
            full = root / relpath
            full.parent.mkdir(parents=True, exist_ok=True)
            if content is not None:
                full.write_text(content, encoding="utf-8")
            else:
                full.mkdir(parents=True, exist_ok=True)
        builder = _make_builder(root)
        vfs = VirtualFileSystem()
        builder._scan_directory(vfs, root, root, 100)
        return builder, vfs, root

    def test_single_file_adds_one_node(self) -> None:
        """MR-Mult: scanning a dir with 1 loose file → 1 FileNode in VFS."""
        with tempfile.TemporaryDirectory() as tmp:
            _, vfs, _ = self._create_and_scan(tmp, {"single.txt": "content"})
            assert len(vfs.get_all_files()) == 1

    def test_nested_files_create_nested_nodes(self) -> None:
        """MR-Compositional: scanning the root adds files in subdirs too.

        Compositional: scanning a parent directory is equivalent to scanning
        each child directory and merging the results.
        """
        with tempfile.TemporaryDirectory() as tmp:
            _, vfs, _ = self._create_and_scan(
                tmp,
                {
                    "root.txt": "",
                    "sub/a.txt": "",
                    "sub/deep/b.txt": "",
                },
            )
            paths = {n.virtual_path for n in vfs.get_all_files()}
            assert "root.txt" in paths
            assert "sub/a.txt" in paths
            assert "sub/deep/b.txt" in paths

    def test_skips_git_and_bin_dirs(self) -> None:
        """MR-Exclusive: .git and bin directories are excluded from scanning.

        Exclusive: files inside these directories are never added, regardless
        of their content.
        """
        with tempfile.TemporaryDirectory() as tmp:
            _, vfs, _ = self._create_and_scan(
                tmp,
                {
                    "keep.txt": "",
                    ".git/HEAD": "ref: main",
                    "bin/tool.exe": b"binary".decode("latin-1"),
                },
            )
            paths = {n.virtual_path for n in vfs.get_all_files()}
            assert "keep.txt" in paths
            assert ".git/HEAD" not in paths
            assert "bin/tool.exe" not in paths

    def test_add_file_then_rescan_increases_count(self) -> None:
        """MR-Add: adding a file on disk increases the scanned node count by 1.

        Additive: the delta in file count matches the delta in nodes, when
        each scan uses a fresh VFS (since _scan_directory does not deduplicate).
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("")
            builder = _make_builder(root)

            vfs1 = VirtualFileSystem()
            builder._scan_directory(vfs1, root, root, 100)
            count1 = len(vfs1.get_all_files())

            (root / "b.txt").write_text("")

            vfs2 = VirtualFileSystem()
            builder._scan_directory(vfs2, root, root, 100)
            count2 = len(vfs2.get_all_files())

            assert count2 - count1 == 1


# ===================================================================
# _add_vpk_entries
# ===================================================================

class TestAddVpkEntries:
    """Metamorphic relations for VfsBuilder._add_vpk_entries."""

    def test_single_entry_adds_one_node(self) -> None:
        """MR-Mult: 1 entry → 1 FileNode added to VFS."""
        with tempfile.TemporaryDirectory() as tmp:
            builder = _make_builder(tmp)
            vfs = VirtualFileSystem()
            entries: list[dict[str, Any]] = [
                {"virtual_path": "a.txt", "file_size": 1, "crc": "x"},
            ]
            before = len(vfs.get_all_files())
            builder._add_vpk_entries(vfs, "test.vpk", 100, entries)
            assert len(vfs.get_all_files()) - before == 1

    def test_n_entries_add_n_nodes(self) -> None:
        """MR-Mult: N entries → exactly N FileNodes added."""
        with tempfile.TemporaryDirectory() as tmp:
            builder = _make_builder(tmp)
            vfs = VirtualFileSystem()
            n = 5
            entries = [
                {"virtual_path": f"{i}.txt", "file_size": i, "crc": str(i)}
                for i in range(n)
            ]
            before = len(vfs.get_all_files())
            builder._add_vpk_entries(vfs, "multi.vpk", 100, entries)
            assert len(vfs.get_all_files()) - before == n

    def test_disabled_addon_flag_propagates(self) -> None:
        """MR-Add: is_disabled_addon=True propagates to every created FileNode."""
        with tempfile.TemporaryDirectory() as tmp:
            builder = _make_builder(tmp)
            vfs = VirtualFileSystem()
            entries = [
                {"virtual_path": "a.txt", "file_size": 1, "crc": "x"},
                {"virtual_path": "b.txt", "file_size": 2, "crc": "y"},
            ]
            builder._add_vpk_entries(
                vfs, "test.vpk", 100, entries, is_disabled_addon=True
            )
            for node in vfs.get_all_files():
                assert node.is_disabled_addon is True

    def test_entry_fields_preserved_in_node(self) -> None:
        """MR-Inv: entry dict fields are preserved in the constructed FileNode.

        Invertive: serialising to an entry dict and deserialising back to a
        FileNode (via _add_vpk_entries) preserves all fields.
        """
        with tempfile.TemporaryDirectory() as tmp:
            builder = _make_builder(tmp)
            vfs = VirtualFileSystem()
            entry: dict[str, Any] = {
                "virtual_path": "materials/test.vtf",
                "file_size": 1024,
                "crc": "abc123",
            }
            builder._add_vpk_entries(vfs, "src.vpk", 50, [entry])
            node = vfs.get_all_files()[0]
            assert node.virtual_path == entry["virtual_path"]
            assert node.file_size == entry["file_size"]
            assert node.file_hash == entry["crc"]
            assert node.source_name == "src.vpk"
            assert node.source_type == "vpk"
            assert node.priority == 50


# ===================================================================
# save_edges / invalidate_cache / cache_size
# ===================================================================

class TestCacheFallback:
    """No-pandas / empty-cache behaviour: all cache ops degrade gracefully."""

    def test_save_edges_empty_vfs(self) -> None:
        """MR-Diff: save_edges on an empty VFS does not raise.

        Differential: with no edges (empty VFS) the method takes the
        empty-DataFrame branch, which should not crash.
        """
        with tempfile.TemporaryDirectory() as tmp:
            builder = _make_builder(tmp)
            vfs = VirtualFileSystem()
            builder.save_edges(vfs)

    def test_invalidate_cache_empty(self) -> None:
        """MR-Add: invalidate on empty cache does not raise (safe degenerate)."""
        with tempfile.TemporaryDirectory() as tmp:
            builder = _make_builder(tmp)
            builder.invalidate_cache()

    def test_cache_size_returns_str(self) -> None:
        """MR-Exclusive: cache_size always returns a non-empty string.

        The return type is a type invariant — regardless of cache state,
        the method never returns None or raises.
        """
        with tempfile.TemporaryDirectory() as tmp:
            builder = _make_builder(tmp)
            size = builder.cache_size()
            assert isinstance(size, str)
            assert len(size) > 0


# ===================================================================
# get_chain
# ===================================================================

class TestGetChain:
    """Metamorphic relations for VfsBuilder.get_chain."""

    def test_no_srctools_returns_none(self) -> None:
        """MR-Diff: without srctools.filesys, get_chain returns None.

        Differential: the presence of srctools changes the return type from
        None to a FileSystemChain.  When srctools is absent (simulated here
        by injecting mock modules without the expected classes), the method
        degrades to None.
        """
        import types

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            builder = _make_builder(root)

            # Insert mock modules that lack FileSystemChain / VPKFileSystem
            mock_srctools = types.ModuleType("srctools")
            mock_srctools_filesys = types.ModuleType("srctools.filesys")

            with patch.dict(
                sys.modules,
                {
                    "srctools": mock_srctools,
                    "srctools.filesys": mock_srctools_filesys,
                },
            ):
                result = builder.get_chain()

            assert result is None


# ===================================================================
# build
# ===================================================================

class TestBuild:
    """Metamorphic relations for VfsBuilder.build."""

    def test_no_gameinfo_returns_empty_vfs(self) -> None:
        """MR-Add: game_root without gameinfo.txt yields an empty VFS.

        Additive: adding a gameinfo.txt file to the root changes the result
        from empty to potentially non-empty.  Without it the method exits
        early.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            builder = _make_builder(root)
            vfs = builder.build()
            assert len(vfs.get_all_files()) == 0

    def test_gameinfo_present_returns_vfs(self) -> None:
        """MR-Add: adding a minimal gameinfo.txt takes a different code path.

        The method passes the "gameinfo exists" guard and attempts parsing.
        Even if the content is insufficient for a full build, a VirtualFileSystem
        object is always returned (never None, never an exception).
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "gameinfo.txt").write_text(
                '"GameInfo"\n{\n\t"SearchPaths"\n\t{\n\t}\n}\n',
                encoding="utf-8",
            )
            builder = _make_builder(root)
            vfs = builder.build()
            # The VFS may be empty (no VPKs found) but must be a valid object
            _ = vfs.get_all_files()
            _ = vfs.get_all_active()


# ===================================================================
# _parse_vpk_worker (standalone function)
# ===================================================================

class TestParseVpkWorker:
    """Metamorphic relations for the module-level _parse_vpk_worker."""

    def test_nonexistent_path_returns_error(self) -> None:
        """MR-Exclusive: nonexistent VPK path yields an error tuple."""
        result = _parse_vpk_worker(
            ("/nonexistent/test.vpk", "test.vpk", 100, False)
        )
        assert len(result) == 6
        path_str, name, priority, entries, error, is_disabled = result
        assert path_str == "/nonexistent/test.vpk"
        assert name == "test.vpk"
        assert priority == 100
        assert isinstance(entries, list)
        assert len(entries) == 0
        assert isinstance(error, str)
        assert is_disabled is False

    def test_missing_path_valid_args(self) -> None:
        """MR-Exclusive: valid args with absent file → error tuple."""
        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "nonexistent.vpk")
            result = _parse_vpk_worker((missing, "missing.vpk", 50, True))
            assert len(result) == 6
            path_str, name, priority, entries, error, is_disabled = result
            assert path_str == missing
            assert name == "missing.vpk"
            assert priority == 50
            assert len(entries) == 0
            assert isinstance(error, str)
            assert is_disabled is True

    def test_tuple_shape_preserved(self) -> None:
        """MR-Inv: returned tuple always follows (path_str, name, priority, entries, error, is_disabled).

        The 6-tuple shape is an invariant regardless of success or failure.
        """
        result_ok = _parse_vpk_worker(
            ("/nonexistent/a.vpk", "a.vpk", 10, False)
        )
        result_disabled = _parse_vpk_worker(
            ("/nonexistent/b.vpk", "b.vpk", 20, True)
        )
        for r in (result_ok, result_disabled):
            assert len(r) == 6
            assert isinstance(r[0], str)  # path_str
            assert isinstance(r[1], str)  # name
            assert isinstance(r[2], int)  # priority
            assert isinstance(r[3], list)  # entries
            assert isinstance(r[4], str)  # error (both fail here)
            assert isinstance(r[5], bool)  # is_disabled
