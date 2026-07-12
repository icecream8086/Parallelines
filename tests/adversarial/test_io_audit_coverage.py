"""Oracle-Free Tests — 覆盖 io.py、atomic_write、H2/H4 缺口、pure_whitelist bug。

所有测试使用 FileReader/FileWriter 自身——不绕过抽象（解决 #8）。
依赖的是行为验证，而非源码 lint。
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from parallelines.analysis.pure_whitelist import (
    filter_vfs_by_whitelist,
    load_pure_whitelist,
    match_whitelist,
)
from parallelines.graph.builder import GraphBuilder
from parallelines.io import CONFIG_FILE_ENCODING, FileReader, FileWriter
from parallelines.types import FileNode


# ═══════════════════════════════════════════════════════════════
# §1 — io.py：FileReader / FileWriter 蜕变测试（#1, #8）
# ═══════════════════════════════════════════════════════════════


class TestFileReaderWriter:
    """io.py 的蜕变测试。全部使用 io.py 自身，不绕过抽象。"""

    # ── MR-Roundtrip (Invertive): 写后读内容不变 ────────────

    def test_mr_roundtrip_write_read_text(self, tmp_path):
        content = "Hello, 世界! \n  line2\n  line3"
        path = tmp_path / "test.txt"
        FileWriter.write_text(path, content)
        read_back = FileReader.read_text(path)
        assert read_back == content

    def test_mr_roundtrip_write_read_json(self, tmp_path):
        data = {"key": "value", "nested": {"a": 1, "b": [1, 2, 3]}, "unicode": "中文"}
        path = tmp_path / "test.json"
        FileWriter.write_json(path, data)
        read_back = FileReader.read_json(path)
        assert read_back == data

    def test_mr_roundtrip_atomic_write_read(self, tmp_path):
        content = "Atomic content \n with \n newlines"
        path = tmp_path / "atomic.txt"
        FileWriter.atomic_write_text(path, content)
        read_back = FileReader.read_text(path)
        assert read_back == content

    # ── MR-Atomic: 写入后无 .tmp 残留（#2） ────────────────

    def test_mr_atomic_no_tempfile_leftover(self, tmp_path):
        path = tmp_path / "clean.txt"
        FileWriter.atomic_write_text(path, "clean write")
        leftovers = list(tmp_path.glob("*.tmp"))
        assert len(leftovers) == 0

    # ── MR-Encoding: UTF-8 编码一致性 ───────────────────────

    def test_mr_encoding_game_text_no_replacement_chars(self, tmp_path):
        """Non-UTF-8 bytes decoded via latin-1 fallback, no U+FFFD chars."""
        bad_bytes = b"valid ascii + \xff\xfe\x00 invalid utf-8"
        path = tmp_path / "gameinfo.txt"
        path.write_bytes(bad_bytes)

        result = FileReader.read_game_text(path)
        # Fix: \xff\xfe decoded as ÿþ (latin-1), not U+FFFD replacement chars
        assert "�" not in result, (
            f"Unexpected U+FFFD replacement char after fix, "
            f"got: {result!r}"
        )
        assert "valid ascii" in result
        assert "ÿ" in result  # \xff maps to ÿ in latin-1

    def test_mr_encoding_strict_text_rejects_bad_bytes(self, tmp_path):
        """read_text（严格模式）对非法 UTF-8 字节应崩溃——这是预期行为。"""
        bad_bytes = b"valid ascii + \xff\xfe\x00 invalid utf-8"
        path = tmp_path / "config.toml"
        path.write_bytes(bad_bytes)

        with pytest.raises(UnicodeDecodeError):
            FileReader.read_text(path)

    # ── MR-Binary: 二进制读写 ──────────────────────────────

    @pytest.mark.parametrize("data", [
        b"",
        b"\x00\x01\x02",
        bytes(range(256)),
        b"Hello\x00World",
    ])
    def test_mr_binary_roundtrip(self, tmp_path, data):
        path = tmp_path / "binary.bin"
        path.write_bytes(data)
        read_back = FileReader.read_binary(path)
        assert read_back == data

    def test_mr_read_binary_missing_file(self, tmp_path):
        """read_binary 对不存在的文件应抛出 FileNotFoundError。"""
        path = tmp_path / "does_not_exist.bin"
        with pytest.raises(FileNotFoundError):
            FileReader.read_binary(path)

    # ── MR-ParentDir: write_text 自动创建父目录 ────────────

    def test_mr_parentdir_auto_creation(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c" / "d" / "file.txt"
        FileWriter.write_text(nested, "nested content")
        assert nested.exists()
        assert FileReader.read_text(nested) == "nested content"

    # ── H2: FileWriter write_text/atomic_write_text + surrogate ──

    def test_h2_surrogate_roundtrip_with_explicit_errors(self, tmp_path):
        """H2: FileWriter (errors=surrogateescape) → FileReader (errors=surrogateescape)
        对 U+DC80..U+DCFF 范围应完整往返。

        注意：Python surrogateescape 只编码 U+DC80–U+DCFF (低 surrogate)，
        U+D800–U+DBFF (高 surrogate) 即使传 errors=surrogateescape 也会崩溃。
        """
        content = "path with " + chr(0xDC80) + chr(0xDC81) + " raw bytes"
        path = tmp_path / "h2_surrogate.txt"
        FileWriter.write_text(path, content, errors="surrogateescape")
        read_back = FileReader.read_text(path, errors="surrogateescape")
        assert read_back == content

    def test_h2_atomic_surrogate_roundtrip(self, tmp_path):
        """H2: atomic_write_text 同样支持 surrogateescape 往返。"""
        content = "surrogate " + chr(0xDC80) + " here"
        path = tmp_path / "h2_atomic_surrogate.txt"
        FileWriter.atomic_write_text(path, content, errors="surrogateescape")
        read_back = FileReader.read_text(path, errors="surrogateescape")
        assert read_back == content


# ═══════════════════════════════════════════════════════════════
# §2 — VFS 路径 A/B 一致性: 真正测试 _read_text 与 Path.read_text（M1）
# ═══════════════════════════════════════════════════════════════


class TestVFSConsistency:
    """真正验证 VFS 路径 A vs 路径 B 的一致性（修复 #1 空测试问题）。"""

    def test_mr_vfs_chain_vs_direct_consistency(self, tmp_path):
        """MR-Consistency: 通过 mock FileSystemChain 验证 _read_text 与直接读取一致。

        路径 A: FileReader.read_text(path) 直接读取
        路径 B: GraphBuilder._read_text(vpath) 通过链读取

        如果两者不一致，说明 VFS 读路径有 bug（审计 M1）。
        """
        content = "Hello from the test file!\nLine 2\n"
        real_path = tmp_path / "test.txt"
        FileWriter.write_text(real_path, content)

        # 使用 io.StringIO 而非 open()，避免资源泄漏（Bug 3 修复）
        class MockFileObj:
            def open_str(self):
                return io.StringIO(content)

        class MockChain:
            def __getitem__(self, vpath):
                return MockFileObj()

        builder = GraphBuilder(MockChain(), MagicMock(), debug=False)

        vfs_result = builder._read_text("maps/test.bsp")
        direct_result = FileReader.read_text(real_path)

        assert vfs_result is not None
        assert vfs_result == direct_result == content

    def test_mr_vfs_chain_vs_direct_bytes_consistency(self, tmp_path):
        """MR-Consistency: _read_bytes 也应保持一致。"""
        data = bytes(range(256))
        real_path = tmp_path / "test.bin"
        real_path.write_bytes(data)

        class MockFileObj:
            def open_bin(self):
                return io.BytesIO(data)

        class MockChain:
            def __getitem__(self, vpath):
                return MockFileObj()

        builder = GraphBuilder(MockChain(), MagicMock(), debug=False)

        vfs_result = builder._read_bytes("maps/test.bsp")
        direct_result = FileReader.read_binary(real_path)

        assert vfs_result is not None
        assert vfs_result == direct_result == data

    def test_mr_vfs_chain_none_no_crash(self):
        """chain=None 时 _read_text 返回 None 不崩溃。"""
        builder = GraphBuilder(None, MagicMock(), debug=False)
        assert builder._read_text("any/path.txt") is None
        assert builder._read_bytes("any/path.bin") is None


# ═══════════════════════════════════════════════════════════════
# §3 — 行为式错误处理测试（修复 #2 lint伪装测试）
# ═══════════════════════════════════════════════════════════════


class TestErrorHandlingBehavior:
    """行为验证：触发真实错误场景验证处理方式，而非 lint 源码。"""

    def test_f1_cache_write_failure_logged(self, tmp_path, caplog):
        """CacheManager.save 写入失败时应记录 warning 而非静默吞异常。

        通过 mock 让 files_df.to_parquet 抛出真实 I/O 错误，
        模拟磁盘满/权限不足的生产场景。
        """
        pytest.importorskip("pandas")
        from unittest.mock import patch

        from parallelines.cache.manager import CacheManager

        cm = CacheManager(tmp_path)
        caplog.set_level("WARNING")

        import pandas as pd
        real_df = pd.DataFrame({"col": [1, 2, 3]})
        with patch.object(real_df, "to_parquet", side_effect=PermissionError("disk full")):
            cm.save(files_df=real_df, meta={"test": 1})

        assert any("Cache" in r.message and "failed" in r.message for r in caplog.records), (
            "§F gap: no cache write failure warning in log. "
            f"Records: {[r.message for r in caplog.records]}"
        )

    def test_f2_parse_error_ca_properly_raised(self, tmp_path):
        """ParseError 应正确传播而不被静默吞掉。"""
        from parallelines.exceptions import ParseError
        from parallelines.parsers.vpk_parser import parse_vpk_index

        # 传入非法 VPK 文件触发解析错误
        bad_file = tmp_path / "not_a.vpk"
        bad_file.write_bytes(b"\x00\x01NOT A VPK\x02\x03")
        with pytest.raises(ParseError):
            parse_vpk_index(str(bad_file))


# ═══════════════════════════════════════════════════════════════
# §4 — Cross-platform 编码测试（修复 #5 缺失项）
# ═══════════════════════════════════════════════════════════════


class TestCrossPlatformEncoding:
    """跨平台编码测试：cp936 / cp1252 场景。"""

    def test_h1_cp936_json_read_crash(self, tmp_path):
        """H1 Bug Proof: cp936 编码的 meta.json 在 UTF-8 下读取会崩溃。

        审计文档标记为严重：
        Windows cp936 写入的 JSON 在 Linux UTF-8 下读取 → 崩。
        FileReader.read_json 固定使用 encoding='utf-8'，这恰好回避了问题——但
        说明了修复前的风险：open() 无 encoding 参数将使用平台默认编码。
        """
        cp936_data = "中文内容".encode("cp936")
        path = tmp_path / "meta_cp936.json"
        path.write_bytes(cp936_data)

        # 当前 FileReader.read_json 强制 UTF-8，所以 cp936 数据会崩溃
        with pytest.raises(UnicodeDecodeError):
            FileReader.read_json(path)

    def test_mr_surrogateescape_roundtrip(self, tmp_path):
        """surrogateescape round-trip: undecodable bytes preserved."""
        path = tmp_path / "surrogate_roundtrip.txt"
        content = "text with " + chr(0xDC80) + chr(0xDC81) + " raw bytes"

        FileWriter.write_text(path, content, errors="surrogateescape")
        read_back = FileReader.read_text(path, errors="surrogateescape")

        assert read_back == content, (
            f"surrogateescape round-trip failed:\n"
            f"  wrote: {content!r}\n"
            f"  read:  {read_back!r}"
        )


# ═══════════════════════════════════════════════════════════════
# §5 — pure_whitelist.py（#3）：模式匹配 + iterator bug 修复验证
# ═══════════════════════════════════════════════════════════════


class TestPureWhitelist:
    """pure_whitelist.py 的行为测试。"""

    def test_mr_whitelist_pattern_exact_match(self):
        assert match_whitelist("maps/c1m1_hotel.bsp", {"maps/c1m1_hotel.bsp"})

    def test_mr_whitelist_pattern_wildcard(self):
        assert match_whitelist("maps/c1m1_hotel.bsp", {"maps/*.bsp"})

    def test_mr_whitelist_pattern_no_match(self):
        assert not match_whitelist("sound/test.wav", {"maps/*.bsp"})

    def test_mr_whitelist_star_star_matches_all(self):
        assert match_whitelist("any/path/anyfile.xyz", {"**"})

    def test_mr_whitelist_empty_patterns(self):
        assert not match_whitelist("maps/test.bsp", set())

    def test_filter_with_generator_preserves_count(self, caplog):
        """Fix Verify: filter_vfs_by_whitelist 传入生成器时，logger 的 total 应为 3（非 0）。

        之前 len(list(files)) 在 for 循环后调用 → 生成器耗尽 → log 显示 total=0。
        修复后 files_list = list(files) 在 for 之前调用，确保 log 正确。
        """
        import logging
        caplog.set_level(logging.DEBUG)
        gen = (FileNode(virtual_path=vp, source_name="src", source_type="vpk")
               for vp in ["maps/a.bsp", "maps/b.bsp", "materials/c.vtf"])
        result = filter_vfs_by_whitelist(gen, {"maps/*.bsp"})
        assert len(result) == 2

        # 验证 logger 输出中 total=3 而非 0（生成器被耗尽后的错误值）
        assert any(
            "Whitelist filter" in r.message and " / 3 files" in r.message
            for r in caplog.records
        ), (
            f"Logger expected 'Whitelist filter: ... / 3 files', "
            f"got: {[r.message for r in caplog.records]}"
        )

    def test_load_whitelist_comment_stripping(self, tmp_path):
        """注释行不应出现在 patterns 中。"""
        content = (
            "// This is a comment\n"
            "# Also a comment\n"
            "maps/*.bsp\n"
            "  maps/*.txt  # inline comment\n"
        )
        path = tmp_path / "whitelist.txt"
        FileWriter.write_text(path, content)
        patterns = load_pure_whitelist(path)

        for pat in patterns:
            assert not pat.startswith(("//", "#")), f"Comment leaked: {pat}"
        assert "maps/*.bsp" in patterns


# ═══════════════════════════════════════════════════════════════
# §6 — H3: atomic_write_text 从未被任何生产代码调用
# ═══════════════════════════════════════════════════════════════


class TestH3AtomicWriteNeverUsed:
    """H3：atomic_write_text 存在但零调用点。审计标记为严重。"""

    @pytest.mark.xfail(
        strict=False,
        reason="H3 unfixed: atomic_write_text has 0 callers outside io.py — "
               "all production writes use write_text, crash-mid-write corrupts output. "
               "Fix: replace write_text(path, ...) with atomic_write_text(path, ...) "
               "in report/generators.py and cache/manager.py.",
    )
    def test_h3_atomic_write_never_called(self):
        """H3: 验证至少一个生产模块调用 atomic_write_text。

        使用 ast.parse 检测实际调用（非字符串 grep），避免注释/docstring 误报。
        """
        import ast
        import os

        src_root = Path(__file__).resolve().parent.parent.parent / "src" / "parallelines"
        callers = []
        for root, _dirs, files in os.walk(src_root):
            for f in files:
                if not f.endswith(".py") or f in ("io.py", "__init__.py"):
                    continue
                filepath = Path(root, f)
                try:
                    tree = ast.parse(filepath.read_text(encoding="utf-8"))
                except SyntaxError:
                    continue
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        func = node.func
                        if (isinstance(func, ast.Attribute)
                                and func.attr == "atomic_write_text"):
                            callers.append(f"{f}:{node.lineno}")
                        elif (isinstance(func, ast.Name)
                              and func.id == "atomic_write_text"):
                            callers.append(f"{f}:{node.lineno}")
        assert len(callers) >= 1, (
            f"atomic_write_text callers found in source: {callers}"
        )


# ═══════════════════════════════════════════════════════════════
# §7 — 反模式检查：测试自身质量
# ═══════════════════════════════════════════════════════════════

# 注意：本文件所有断言是蜕变关系或行为验证，不使用自验证反模式（AP1）。
# 无需显式测试——反模式的存在性通过代码审查保证。
