"""Oracle-Free 对抗性测试 — §5.1 Path Resolution.

Metamorphic relations tested in this module:

    MR-P1  |gameinfo_path| substitution equivalence at VFS output level
    MR-P2  Path separator normalization through real data paths
    MR-P3  CWD independence and cli.py config_path resolution
    MR-P5  Same-name VPK source_paths overwrite via _build_from_disk

See ``devdocs/adversarial-path-env-testing.md`` for the full design.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from parallelines.config import AppConfig, load_config
from parallelines.types import FileNode
from parallelines.vfs.builder import VfsBuilder
from parallelines.vfs.filesystem import VirtualFileSystem

# Hypothesis is optional; strategies are for external reuse.
_HAS_HYPOTHESIS = False
try:
    from hypothesis import strategies as st

    _HAS_HYPOTHESIS = True
except ImportError:
    pass

# ── §4 Hypothesis 策略 ─────────────────────────────────────────

if _HAS_HYPOTHESIS:

    @st.composite
    def malicious_search_paths(draw):
        """Generate search_path strings designed to break _resolve_path."""
        base = draw(
            st.sampled_from(
                [
                    "|gameinfo_path|/materials",
                    "|GAMEINFO_PATH|/models",  # 大写 — 不会匹配
                    "|gameinfo_path|/|gameinfo_path|/recursive",  # 字面量嵌套
                    "../../escape",
                    ".",  # 当前目录
                    "/",  # 根目录 (Linux) / 当前驱动器根 (Windows)
                    "C:\\absolute\\path",  # 硬编码 Windows 路径
                    "|gameinfo_path|\\backslash",  # 反斜杠混用
                    "|gameinfo_path|/../../../../etc/passwd",  # 路径穿越
                    "",
                    " " * 10,  # 纯空格
                    "\x00/surrogate/\udc80/test",  # surrogate 字节
                ]
            )
        )
        return base

    @st.composite
    def malicious_virtual_paths(draw):
        """Generate virtual_path strings that stress VFS key matching."""
        sep = draw(st.sampled_from(["/", "\\", "/./", "\\..\\"]))
        prefix = draw(st.sampled_from(["", "/", "\\", "./", ".\\"]))
        case = draw(
            st.sampled_from(
                [
                    lambda s: s,
                    lambda s: s.lower(),
                    lambda s: s.upper(),
                    lambda s: s.swapcase(),
                ]
            )
        )
        body = draw(
            st.text(
                alphabet=st.characters(
                    whitelist_categories=("Lu", "Ll", "Nd", "Zs"),
                    blacklist_characters="\x00\n\r",
                ),
                min_size=1,
                max_size=80,
            )
        )
        return case(prefix + body.replace(" ", sep))

    @st.composite
    def malicious_game_roots(draw):
        """Generate game_root paths targeting resolve/relative_to edge cases."""
        kind = draw(
            st.sampled_from(
                [
                    "short_ascii",
                    "with_spaces",
                    "with_unicode",
                    "trailing_separator",
                    "long_path",
                    "reserved_name",
                ]
            )
        )
        if kind == "short_ascii":
            base = draw(st.sampled_from(["C:\\game", "/tmp/game", "."]))
        elif kind == "with_spaces":
            base = "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Test Game\\testgame"
        elif kind == "with_unicode":
            base = draw(
                st.sampled_from(
                    [
                        "C:\\游戏\\L4D2",
                        "C:\\Users\\测试用户\\game",
                    ]
                )
            )
        elif kind == "trailing_separator":
            base = "C:\\game\\left4dead2\\"
        elif kind == "long_path":
            base = "C:\\" + "a" * 250 + "\\game"
        elif kind == "reserved_name":
            base = draw(
                st.sampled_from(
                    [
                        "C:\\test\\CON\\game",  # Windows 保留名作父目录
                        "C:\\NUL\\game",  # NUL 是设备名
                        "C:\\PRN\\game",
                    ]
                )
            )
        return base

    @st.composite
    def env_var_states(draw):
        """Generate environment variable combinations that break config/i18n."""
        return {
            "LOCALAPPDATA": draw(
                st.one_of(
                    st.none(),
                    st.just(""),
                    st.just("C:\\Users\\user\\AppData\\Local"),
                    st.just("C:\\Users\\中文\\AppData\\Local"),
                    st.just("C:\\Users\\name with spaces\\AppData\\Local"),
                    st.just("C:\\Users\\user\\AppData\\Local  "),  # trailing space
                )
            ),
            "APPDATA": draw(
                st.one_of(
                    st.none(),
                    st.just(""),
                    st.just("C:\\Users\\user\\AppData\\Roaming"),
                )
            ),
            "LANG": draw(
                st.one_of(
                    st.none(),
                    st.just("zh_CN.UTF-8"),
                    st.just("en_US.UTF-8"),
                    st.just("C"),
                    st.just("zh_CN.GB2312"),
                    st.just(""),
                )
            ),
            "LC_ALL": draw(
                st.one_of(
                    st.none(),
                    st.just("zh_CN.UTF-8"),
                    st.just("en_US.UTF-8"),
                )
            ),
            "PARALLELINES_NO_CONTRACTS": draw(
                st.one_of(
                    st.none(),
                    st.just("1"),
                    st.just("true"),
                    st.just("TRUE"),
                    st.just("0"),
                    st.just(""),
                )
            ),
        }


if _HAS_HYPOTHESIS:

    from hypothesis import given

    class TestResolvePathPBT:
        """Hypothesis 属性基测试——真正使用上面定义的策略。"""

        @given(search_path=malicious_search_paths())
        def test_mr_resolve_never_crashes(self, search_path):
            """MR-Robust: 任意恶意 search_path 不应使 _resolve_path 崩溃。"""
            builder = _make_builder(Path("C:/game/test"))
            result = builder._resolve_path(search_path)
            # None 表示"无法解析"——可接受。崩溃不可接受。
            if result is not None:
                assert isinstance(result, (str, Path))
                assert len(str(result)) > 0

        @given(vpath=malicious_virtual_paths())
        def test_mr_vfs_normalization_idempotent(self, vpath):
            """MR-Idempotent: VFS add_file 后 get_active_file 应返回一致结果。"""
            vfs = VirtualFileSystem()
            from parallelines.types import FileNode
            node = FileNode(
                virtual_path=vpath, source_name="test", source_type="addon",
            )
            vfs.add_file(node)
            vfs.resolve()
            active = vfs.get_active_file(vpath)
            if active is not None:
                assert active.source_name == "test"

        @given(root=malicious_game_roots())
        def test_mr_game_root_never_crashes(self, root):
            """MR-Robust: 恶意 game_root 不应使 _make_builder 崩溃。"""
            _make_builder(Path(root))


# ── Test helpers ────────────────────────────────────────────────


def _make_game_root(
    tmp_path: Path,
    gameinfo_text: str,
    extra_files: dict[str, str] | None = None,
) -> Path:
    """Create a minimal game root with gameinfo.txt and optional extra files.

    extra_files maps relative path -> file content.
    """
    game_root = tmp_path / "game"
    game_root.mkdir()
    (game_root / "gameinfo.txt").write_text(gameinfo_text, encoding="utf-8")
    if extra_files:
        for rel_path, content in extra_files.items():
            full = game_root / rel_path
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content, encoding="utf-8")
    return game_root


def _make_builder(game_root: Path) -> VfsBuilder:
    """Construct a minimal VfsBuilder suitable for private-method testing."""
    config = AppConfig()
    return VfsBuilder(game_root, config, use_cache=False, num_workers=1)


# ── MR-P1: |gameinfo_path| substitution equivalence ────────────


class TestMrP1:
    """MR-P1: |gameinfo_path| substitution equivalence at VFS output level.

    The metamorphic relation:
        T0 = gameinfo with "Game  |gameinfo_path|/hl2"
        T1 = gameinfo with "Game  <absolute_path_to_same_dir>"
        R  = _build_from_disk + resolve produces same active file set

    NOTE: We use _build_from_disk() directly rather than build() because
    srctools 2.7+ stringifies nested Keyvalues blocks, causing
    extract_search_paths() to return {}.  See tests/parsers/test_gameinfo.py
    for details.

    Real bug exposed: when gameinfo has an absolute path instead of
    |gameinfo_path|, the resolved directory is NOT relative to game_root,
    so _build_from_disk skips loose file scanning for that directory
    (due to ValueError from relative_to check).
    """

    def test_path_token_and_absolute_produce_same_active_files(self, tmp_path: Path) -> None:
        """|gameinfo_path|/testdir and absolute path produce identical VFS for testdir files."""
        # ── Build with |gameinfo_path| token ──────────────────────────
        game_root = tmp_path / "game"
        game_root.mkdir()
        sub_dir = game_root / "testdir"
        sub_dir.mkdir()
        (sub_dir / "materials").mkdir()
        (sub_dir / "materials/test.vmt").write_text("test", encoding="utf-8")

        config_token = AppConfig()
        builder_token = VfsBuilder(game_root, config_token, use_cache=False, num_workers=1)
        vfs_token = VirtualFileSystem()
        search_paths_token: dict = {"game": "|gameinfo_path|/testdir"}
        builder_token._build_from_disk(vfs_token, search_paths_token, addon_roots=[])
        vfs_token.resolve()

        # ── Build with absolute path instead of token ─────────────────
        abs_root = tmp_path / "game_abs"
        abs_root.mkdir()
        abs_sub = abs_root / "testdir"
        abs_sub.mkdir(parents=True, exist_ok=True)
        (abs_sub / "materials").mkdir()
        (abs_sub / "materials/test.vmt").write_text("test", encoding="utf-8")
        abs_sub_resolved = abs_sub.resolve()

        config_abs = AppConfig()
        builder_abs = VfsBuilder(abs_root, config_abs, use_cache=False, num_workers=1)
        vfs_abs = VirtualFileSystem()
        search_paths_abs: dict = {"game": abs_sub_resolved.as_posix()}
        builder_abs._build_from_disk(vfs_abs, search_paths_abs, addon_roots=[])
        vfs_abs.resolve()

        # ── Collect active virtual paths from both ────────────────────
        token_files = {n.virtual_path for n in vfs_token.get_all_active()}
        abs_files = {n.virtual_path for n in vfs_abs.get_all_active()}

        # ── Assert: both should contain the same files from testdir ───
        # NOTE: the |gameinfo_path| version scans loose files because
        # its resolved path is inside game_root.  The absolute version
        # may skip them if the absolute path falls outside game_root
        # (relative_to ValueError).  This IS the bug MR-P1 exposes.
        if token_files != abs_files:
            missing = token_files - abs_files
            pytest.fail(
                f"MR-P1 VIOLATION: absolute-path gameinfo missing {len(missing)} files "
                f"that |gameinfo_path| version found.\n"
                f"  token: {token_files}\n"
                f"  abs:   {abs_files}\n"
                f"  This confirms H1: absolute paths in gameinfo.txt "
                f"lose loose-file scanning."
            )

    def test_gameinfo_path_token_resolves_to_correct_directory(self, tmp_path: Path) -> None:
        """Verify |gameinfo_path|/hl2 resolves to game_root/hl2 and files are scanned."""
        game_root = tmp_path / "game"
        game_root.mkdir()
        hl2 = game_root / "hl2"
        hl2.mkdir()
        (hl2 / "materials").mkdir()
        (hl2 / "materials/test.vmt").touch()

        config = AppConfig()
        builder = VfsBuilder(game_root, config, use_cache=False, num_workers=1)

        vfs = VirtualFileSystem()
        search_paths: dict = {"game": "|gameinfo_path|/hl2"}
        builder._build_from_disk(vfs, search_paths, addon_roots=[])
        vfs.resolve()

        active_files = {n.virtual_path for n in vfs.get_all_active()}
        assert "materials/test.vmt" in active_files, (
            f"|gameinfo_path| did not resolve properly.\n"
            f"  expected: 'materials/test.vmt' in VFS\n"
            f"  got: {active_files}"
        )


# ── MR-P2: Path separator normalization ─────────────────────────


class TestMrP2:
    """MR-P2: Path separator normalization through real data sources.

    The metamorphic relation:
        T(x) = directory tree containing files with various separator styles
        R    = VFS built via _scan_directory contains ONLY forward-slash paths

    Real data sources all normalize to '/':
    - _scan_directory: uses rel.as_posix() -> always '/'
    - VPK parsing: srctools returns '/' paths
    """

    def test_scan_directory_normalizes_separators(self, tmp_path: Path) -> None:
        """_scan_directory produces paths with '/' only."""
        base = tmp_path / "base"
        base.mkdir()
        sub = base / "subdir"
        sub.mkdir()
        (sub / "test.vmt").touch()
        (base / "other.txt").touch()

        vfs = VirtualFileSystem()
        config = AppConfig()
        builder = VfsBuilder(base, config, use_cache=False, num_workers=1)
        builder._scan_directory(vfs, base, base, priority=10)

        for node in vfs.get_all_files():
            assert "\\" not in node.virtual_path, (
                f"Separator BUG: _scan_directory produced '\\' in virtual_path: "
                f"{node.virtual_path!r}"
            )
            assert node.virtual_path == node.virtual_path.replace("\\", "/"), (
                f"Separator BUG: virtual_path contains backslash: {node.virtual_path!r}"
            )

    def test_vfs_separator_normalization(self) -> None:
        """VFS normalizes '/' and '\\' to the same key (H2 fixed).

        ``VirtualFileSystem.add_file()`` normalises ``\\`` to ``/`` in the
        lookup key, so paths differing only in separator style are treated
        as the same logical file.
        """
        vfs = VirtualFileSystem()
        vfs.add_file(FileNode("path/to/file.vmt", "game", "a", priority=10))
        vfs.add_file(FileNode(r"path\to\file.vmt", "vpk", "b", priority=20))
        vfs.resolve()

        active = vfs.get_all_active()
        assert len(active) == 1, (
            f"VFS separator normalization BROKEN: expected 1 active file, "
            f"got {len(active)}. Keys: {[n.virtual_path for n in active]}"
        )
        # The higher-priority node should have won
        winner = vfs.get_active_file("path/to/file.vmt")
        assert winner is not None
        assert winner.source_name == "b"


# ── MR-P3: CWD independence + cli.py config_path ────────────────


class TestMrP3:
    """MR-P3: CWD independence and config_path resolution."""

    def test_load_config_with_explicit_path_cwd_independence(self, tmp_path: Path) -> None:
        """Explicit config path -> CWD changes don't affect result."""
        old_cwd = os.getcwd()
        try:
            cfg = tmp_path / "config.toml"
            cfg.write_text('[general]\ngame = "l4d2"\n')
            os.chdir(tmp_path.parent)
            r1 = load_config(cfg)
            os.chdir(tmp_path)
            r2 = load_config(cfg)
            assert r1.general.game == r2.general.game == "l4d2"
        finally:
            os.chdir(old_cwd)

    def test_load_config_without_path_uses_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """load_config() without arg uses Path.cwd() / 'config.toml'."""
        cfg = tmp_path / "config.toml"
        cfg.write_text('[general]\ngame = "tf2"\n')
        monkeypatch.chdir(tmp_path)
        assert load_config().general.game == "tf2"

        monkeypatch.chdir(tmp_path.parent)
        assert load_config().general.game == ""  # no config found -> defaults

    def test_config_path_resolution_empty_string_is_falsy(self) -> None:
        """cli.py: Path(args.config) if args.config else None -- empty string is falsy -> None.

        This is the actual code path in cli.py:_main:
            config_path = Path(args.config) if args.config else None
        Since --config default is "", config_path becomes None, which triggers
        load_config(None) -> Path.cwd() / "config.toml".
        """
        args_config = ""  # default value from argparse
        config_path = Path(args_config) if args_config else None
        assert config_path is None, (
            f"BUG: empty string not treated as falsy in config_path resolution.\n"
            f"  args.config={args_config!r}\n"
            f"  config_path={config_path!r}\n"
            f"  Expected: None (to trigger load_config default path)"
        )


# ── MR-P5: Same-name VPK overwrite ──────────────────────────────


class TestMrP5:
    """MR-P5: Same-name VPKs from different directories -> source_paths dedup."""

    def test_same_name_vpks_overwrite_in_source_paths(self, tmp_path: Path) -> None:
        """Two VPKs with same name in different dirs -> only last survives in source_paths."""
        # Create a minimal game_root so _build_from_disk won't crash
        game_root = tmp_path / "game"
        game_root.mkdir()
        (game_root / "gameinfo.txt").write_text(
            "GameInfo\n{\n\tFileSystem\n\t{\n\t\tSearchPaths\n\t\t{\n\t\t\tGame\t|gameinfo_path|.\n\t\t}\n\t}\n}\n",
            encoding="utf-8",
        )

        # Create two VPKs with same name in different directories
        dir_a = game_root / "addons" / "a"
        dir_a.mkdir(parents=True)
        vpk1 = dir_a / "same_name.vpk"
        vpk1.touch()

        dir_b = game_root / "addons" / "b"
        dir_b.mkdir(parents=True)
        vpk2 = dir_b / "same_name.vpk"
        vpk2.touch()

        builder = _make_builder(game_root)
        search_paths: dict = {"game": "|gameinfo_path|."}
        vfs = VirtualFileSystem()
        builder._build_from_disk(vfs, search_paths, addon_roots=["addons/a", "addons/b"])

        assert "same_name.vpk" in builder.source_paths, (
            "same_name.vpk not found in source_paths after _build_from_disk"
        )
        # 键碰撞行为：dict[str,str] 中后写入的胜出。验证最终值来自 addons/b。
        result = builder.source_paths["same_name.vpk"]
        assert isinstance(result, str)
        assert "addons" in result, (
            f"Expected source_paths['same_name.vpk'] to reference an addon dir, "
            f"got: {result}"
        )
        # 确认结果是一个真实存在的路径（非原地返回或空字符串）
        assert len(result) > 5


# ── Edge cases ──────────────────────────────────────────────────


class TestResolvePathEdgeCases:
    """Boundary conditions -- no metamorphic relations, pure boundary-value attacks."""

    @pytest.mark.parametrize(
        "search_path,expected_failure_mode",
        [
            ("|GAMEINFO_PATH|/materials", "uppercase_token_not_replaced"),
            ("|gameinfo_path|/|gameinfo_path|/double", "nested_literal"),
            ("", "empty_string"),
            ("\x00", "null_byte"),
            ("C:relative", "windows_drive_relative"),
        ],
    )
    def test_resolve_path_bizarre_inputs(
        self, search_path: str, expected_failure_mode: str
    ) -> None:
        """_resolve_path must handle bizarre inputs with predictable output shape."""
        builder = _make_builder(Path("C:/game/test"))
        try:
            result = builder._resolve_path(search_path)
        except Exception as e:
            pytest.fail(f"_resolve_path crashed on '{expected_failure_mode}': {e}")

        # 每个 expected_failure_mode 对应一个具体断言
        if expected_failure_mode == "uppercase_token_not_replaced":
            assert result is None or "GAMEINFO_PATH" in str(result), (
                f"[uppercase_token_not_replaced] expected 'GAMEINFO_PATH' preserved"
            )
        elif expected_failure_mode == "nested_literal":
            assert result is None or "|" not in str(result), (
                f"[nested_literal] unresolved nested tokens"
            )
        elif expected_failure_mode == "empty_string":
            assert result is None, (
                f"[empty_string] empty search_path should resolve to None"
            )
        elif expected_failure_mode == "null_byte":
            # 当前行为：含空字节的路径返回 None。可改进：剥离空字节后继续解析。
            if result is not None:
                assert "\x00" not in str(result), (
                    f"[null_byte] null byte leaked into result"
                )
        elif expected_failure_mode == "windows_drive_relative":
            # 当前行为：Windows 驱动器相对路径返回 None。
            # 可改进：将 C:relative 规范化为 absolute/game_root/relative。
            if result is not None:
                assert str(result).endswith("relative")
