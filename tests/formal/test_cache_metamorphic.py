"""Layer 2 — 蜕变测试：缓存层。

缓存序列化/反序列化的蜕变关系：save→load→save 应保持语义不变。
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from parallelines.cache.manager import CacheManager
from parallelines.cache.strategies import HashStrategy, MtimeStrategy


class TestCacheMetamorphic:
    """CacheManager 蜕变关系。"""

    # ── 蜕变 1：save → load 往返保持文件数量 ─────────────────────────────

    def test_save_load_roundtrip_preserves_count(self) -> None:
        """save() → load_files() → 行数不变。"""
        import pandas as pd

        with tempfile.TemporaryDirectory() as tmpdir:
            cm = CacheManager(tmpdir)
            df = pd.DataFrame(
                {
                    "virtual_path": ["a.txt", "b.txt", "c.txt"],
                    "source_name": ["src1", "src1", "src2"],
                    "priority": [10, 5, 3],
                }
            )
            cm.save(df, {"entries": {"test": {"mtime": 100, "size": 200}}})

            loaded = cm.load_files()
            assert len(loaded) == len(df), (
                f"往返后文件数不一致：原始 {len(df)}，加载 {len(loaded)}"
            )

    # ── 蜕变 2：save → load 往返保持 active 集合不变 ─────────────────────

    def test_save_load_roundtrip_preserves_data(self) -> None:
        """save() → load_files() → 数据内容一致。"""
        import pandas as pd

        with tempfile.TemporaryDirectory() as tmpdir:
            cm = CacheManager(tmpdir)
            df = pd.DataFrame(
                {
                    "virtual_path": ["a.txt", "b.txt"],
                    "source_name": ["src1", "src2"],
                    "priority": [10, 5],
                }
            )
            cm.save(df, {"entries": {"test": {"mtime": 100, "size": 200}}})
            cm.save_edges(df)  # also save edges

            loaded_files = cm.load_files()
            loaded_edges = cm.load_edges()

            assert len(loaded_files) == 2
            assert len(loaded_edges) == 2

            # 验证数据值
            for col in df.columns:
                assert list(loaded_files[col]) == list(df[col]), (
                    f"列 '{col}' 往返后值不一致"
                )

    # ── 蜕变 3：save → load 往返保持 meta 信息 ───────────────────────────

    def test_save_load_roundtrip_meta(self) -> None:
        """meta.json 的 save → load → save → load 幂等。"""
        import pandas as pd

        with tempfile.TemporaryDirectory() as tmpdir:
            cm = CacheManager(tmpdir)
            df = pd.DataFrame({"virtual_path": [], "source_name": []})
            meta = {"entries": {"a": {"mtime": 100, "size": 200}}}

            cm.save(df, meta)
            meta_path = Path(tmpdir) / "meta.json"
            assert meta_path.exists()
            loaded_meta = json.loads(meta_path.read_text())
            assert loaded_meta == meta, (
                f"meta 不一致：预期 {meta}，实际 {loaded_meta}"
            )

    # ── 蜕变 4：增量更新 save = 全量重建 save ────────────────────────────

    def test_incremental_save_equals_full_rebuild(self) -> None:
        """增量更新（添加新数据后 save）结果应 = 全量重建后 save 的结果。"""
        import pandas as pd

        with tempfile.TemporaryDirectory() as tmpdir:
            cm = CacheManager(tmpdir)

            # 第一次 save
            df1 = pd.DataFrame(
                {
                    "virtual_path": ["a.txt"],
                    "source_name": ["src1"],
                    "priority": [10],
                }
            )
            cm.save(df1, meta={"entries": {"a": {"mtime": 100}}})

            # 增量：添加新文件 + 更新 meta
            df2 = pd.DataFrame(
                {
                    "virtual_path": ["a.txt", "b.txt"],
                    "source_name": ["src1", "src2"],
                    "priority": [10, 5],
                }
            )
            cm.save(df2, meta={"entries": {"a": {"mtime": 100}, "b": {"mtime": 200}}})

            incremental_files = cm.load_files()
            incremental_meta = json.loads(
                (Path(tmpdir) / "meta.json").read_text()
            )

        # 全量重建：直接把所有数据一次性 save
        with tempfile.TemporaryDirectory() as tmpdir2:
            cm2 = CacheManager(tmpdir2)
            cm2.save(df2, meta={"entries": {"a": {"mtime": 100}, "b": {"mtime": 200}}})

            full_files = cm2.load_files()
            full_meta = json.loads(
                (Path(tmpdir2) / "meta.json").read_text()
            )

        assert len(incremental_files) == len(full_files), (
            f"增量与全量长度不一致：{len(incremental_files)} vs {len(full_files)}"
        )
        assert incremental_meta == full_meta, (
            f"增量与全量 meta 不一致"
        )

    # ── 蜕变 5：无效化后 load 返回空 ──────────────────────────────────────

    def test_invalidate_empties_cache(self) -> None:
        """invalidate() 后 load_files() 返回空。"""
        import pandas as pd

        with tempfile.TemporaryDirectory() as tmpdir:
            cm = CacheManager(tmpdir)
            df = pd.DataFrame({"virtual_path": ["a.txt"], "source_name": ["s1"]})
            cm.save(df, {"entries": {}})

            cm.invalidate()

            loaded = cm.load_files()
            assert len(loaded) == 0, (
                f"invalidate 后仍返回 {len(loaded)} 行"
            )

    # ── 蜕变 6：HashStrategy 和 MtimeStrategy 在无变化时一致 ────────────

    def test_strategies_agree_when_no_changes(self) -> None:
        """文件未变化时，HashStrategy 和 MtimeStrategy 的 is_valid 一致。"""
        cache_meta = {
            "a.vpk": {"mtime": 100, "size": 200, "sha256": "abc"},
            "b.vpk": {"mtime": 150, "size": 300, "sha256": "def"},
        }
        current_state = {
            "a.vpk": {"mtime": 100, "size": 200, "sha256": "abc"},
            "b.vpk": {"mtime": 150, "size": 300, "sha256": "def"},
        }

        mtime = MtimeStrategy()
        hsh = HashStrategy()

        assert mtime.is_valid(cache_meta, current_state) == hsh.is_valid(
            cache_meta, current_state
        ), "无变化时两种策略结果应一致"

    # ── 蜕变 7：HashStrategy 对任何变化都敏感 ────────────────────────────

    def test_hash_strategy_detects_any_change(self) -> None:
        """hash 变化 → HashStrategy.is_valid() = False。"""
        cache_meta = {"a.vpk": {"sha256": "abc"}}
        current_state = {"a.vpk": {"sha256": "xyz"}}

        hsh = HashStrategy()
        assert not hsh.is_valid(cache_meta, current_state), (
            "HashStrategy 应检测到 hash 变化"
        )

    # ── 蜕变 8：MtimeStrategy 对 size 变化敏感 ───────────────────────────

    def test_mtime_strategy_detects_size_change(self) -> None:
        """size 变化 → MtimeStrategy.is_valid() = False。"""
        cache_meta = {"a.vpk": {"mtime": 100, "size": 200}}
        current_state = {"a.vpk": {"mtime": 100, "size": 999}}

        mtime = MtimeStrategy()
        assert not mtime.is_valid(cache_meta, current_state), (
            "MtimeStrategy 应检测到 size 变化"
        )
