"""Oracle-Free Tests for MDL binary sound event extraction.

根据 oracle-free-testing-prompt.md 设计。测试的目的是发现 bug，而非证明无 bug。

适用方法 (sect;3.1 决策树):
  f = extract_sounds_binary(bytes) → set[str]
  ├─ 有独立实现 srctools.Model？YES → 异构差分 f_binary == f_srctools
  ├─ 可定义蜕变关系？YES → Additive (注入事件 → 输出扩大)
  └─ 可 PBT？YES → 合成噪声策略搜索反例
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest
from hypothesis import given, assume, settings
from hypothesis import strategies as st

# ═══════════════════════════════════════════════════════════════
# 被测函数
# ═══════════════════════════════════════════════════════════════

_HDR_SEQ_OFF = 188
_SEQ_FMT = '<8i3f3f116x2i32x'
_SEQ_SIZE = 212
_EVT_SIZE = 80
_SOUND_EVENT_IDS = frozenset({14, 15, 5004})


def extract_sounds_binary(raw: bytes) -> set[tuple[str, float, str]]:
    if len(raw) < 200 or raw[:4] != b'IDST':
        return set()
    seq_count, seq_offset = struct.unpack_from('<2I', raw, _HDR_SEQ_OFF)
    if seq_count == 0 or seq_count > 500:
        return set()
    results: set[tuple[str, float, str]] = set()
    for si in range(seq_count):
        so = seq_offset + si * _SEQ_SIZE
        if so + _SEQ_SIZE > len(raw):
            continue
        seq = struct.unpack_from(_SEQ_FMT, raw, so)
        num_events, evt_rel_off = seq[6], seq[7]
        label = _read_nullstr(raw, so + seq[1])
        for ej in range(num_events):
            ea = so + evt_rel_off + ej * _EVT_SIZE
            if ea + _EVT_SIZE > len(raw):
                break
            cycle, event_idx, flags = struct.unpack_from('<fii', raw, ea)
            opts_raw = raw[ea + 12: ea + 76]
            if not (flags & 0x400) and event_idx in _SOUND_EVENT_IDS:
                path = opts_raw.split(b'\0')[0].decode('ascii', errors='replace')
                path = path.strip().replace('\\', '/')
                if path:
                    results.add((label, round(cycle, 4), path))
    return results


def _read_nullstr(data: bytes, offset: int) -> str:
    end = data.find(b'\0', offset)
    return data[offset:end].decode('ascii', errors='replace') if end > offset else ''


# ═══════════════════════════════════════════════════════════════
# 合成 MDL 构建器
# ═══════════════════════════════════════════════════════════════

def _build_mdl(
    seq_label: str = "test",
    *,
    events: list[tuple[float, int, int, str]] = None,
) -> bytes:
    """Build minimal MDL bytes with event array.

    Args:
        events: list of (cycle, event_id, flags, options_string)
    """
    events = events or []
    SEQ_ABS = 0xC4
    EVT_ABS = SEQ_ABS + _SEQ_SIZE

    name_bytes = seq_label.encode('ascii').ljust(64, b'\0')
    header = (
        b'IDST'
        + struct.pack('<i 4s 64s i', 48, b'\0' * 4, name_bytes, EVT_ABS + len(events) * _EVT_SIZE)
        + b'\0' * 72 + b'\0' * 36
        + struct.pack('<2I', 1, SEQ_ABS)
    )

    label_pad = seq_label.encode('ascii') + b'\0'
    seq_desc = struct.pack(_SEQ_FMT, 0, 56, 0, 0, 0, 0, len(events), _SEQ_SIZE,
                           0, 0, 0, 0, 0, 0, 0, 0)
    seq_desc = seq_desc[:56] + label_pad.ljust(116, b'\0') + seq_desc[172:]

    evt_data = bytearray()
    for cycle, eid, flags, opts in events:
        opts_b = opts.encode('ascii')[:63].ljust(64, b'\0')
        evt_data += struct.pack('<fii', cycle, eid, flags) + opts_b + struct.pack('<i', 0)

    return bytes(header + seq_desc + evt_data)


# ═══════════════════════════════════════════════════════════════
# Layer 0 — 契约式设计
# ═══════════════════════════════════════════════════════════════

class TestContract:
    """二元不变式：空/损坏的输入 → 空输出。"""

    def test_empty_bytes(self) -> None:
        assert extract_sounds_binary(b'') == set()

    def test_no_idst_magic(self) -> None:
        assert extract_sounds_binary(b'\x00' * 200) == set()

    def test_zero_seq(self) -> None:
        raw = b'IDST' + b'\x00' * 184 + struct.pack('<2I', 0, 0)
        assert extract_sounds_binary(raw) == set()

    def test_truncated_seq(self) -> None:
        raw = b'IDST' + b'\x00' * 184 + struct.pack('<2I', 1, 0)  # seq at 0, too short
        assert extract_sounds_binary(raw) == set()

    def test_layout_constants(self) -> None:
        assert struct.calcsize(_SEQ_FMT) == _SEQ_SIZE
        assert struct.calcsize('<fii64si') == _EVT_SIZE


# ═══════════════════════════════════════════════════════════════
# Layer 1 — 属性基测试（Hypothesis）：合成噪声 → 搜索反例
# ═══════════════════════════════════════════════════════════════

# ASCII 可见字符策略（MDL format 使用 ASCII）
_ascii_text = st.text(
    min_size=1, max_size=40,
    alphabet=st.characters(whitelist_categories=('L', 'N', 'P'), whitelist_characters='./_-'),
    # L=letter, N=digit, P=punctuation → exclude control/space
)
# 单个 mstudioevent_t 的策略
_event_strategy = st.tuples(
    st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    st.sampled_from([14, 15, 5004]),
    st.integers(min_value=0, max_value=0xFFF),
    st.text(min_size=1, max_size=40, alphabet='abcdefghijklmnopqrstuvwxyz./_0123456789'),
)


class TestPropertyBased:
    """Hypothesis 属性基测试：随机合成事件 → 验证提取正确性。

    目标：找到被测代码中以下类型的 bug：
    - 对某些 event_id 过滤器不正确（漏掉 14/15/5004）
    - options 短于 64 字节时的 null 终止处理错误
    - cycle 为 0.0 或 1.0 时边界值处理
    - 路径包含 './' 或 '_' 时规范化错误
    """

    @given(st.lists(_event_strategy, min_size=1, max_size=10))
    @settings(max_examples=200)
    def test_all_events_extracted(self, events):
        """Property: 对旧系统事件 (flag & 0x400 == 0)，解析器应全部提取。

        如果这里出现反例，说明被测代码的过滤逻辑有 bug
        （遗漏了某个应有的 event_id，或 options 解析有缺陷）。
        """
        # 强制所有事件为旧系统
        events_clean = [(c, eid, 0, o) for c, eid, _, o in events]
        raw = _build_mdl("test", events=events_clean)
        result = extract_sounds_binary(raw)

        expected = set()
        for cycle, eid, flags, opts in events_clean:
            path = opts.strip().replace('\\', '/')
            if path:
                expected.add(("test", round(cycle, 4), path))

        assert result == expected, (
            f"事件丢失！\n"
            f"  输入:     {events_clean}\n"
            f"  期望:     {expected}\n"
            f"  实际:     {result}\n"
            f"  丢失:     {expected - result}\n"
            f"  误增:     {result - expected}"
        )

    @given(st.lists(_event_strategy, min_size=1, max_size=10))
    @settings(max_examples=100)
    def test_new_system_events_filtered(self, events):
        """Property: 新系统事件 (flag & 0x400) 应被过滤。

        如果这里出现反例，说明被测代码错误地把新系统事件当作
        AE_CL_PLAYSOUND 提取了 → 假阳性 bug。
        """
        # 强制所有事件为新系统
        events_new = [(c, eid, 0x400, o) for c, eid, _, o in events]
        raw = _build_mdl("test", events=events_new)
        result = extract_sounds_binary(raw)
        assert result == set(), (
            f"新系统事件未被过滤！\n"
            f"  输入 events: {events_new}\n"
            f"  误提取:      {result}"
        )

    @given(st.lists(_event_strategy, min_size=1, max_size=10))
    @settings(max_examples=100)
    def test_non_sound_event_ids_filtered(self, events):
        """Property: 非音效 event_id（如 0、31 等）不应被提取。

        如果这里出现反例，说明被测代码对 event_id 的过滤有 bug。
        """
        # 把 event_id 改成不在 _SOUND_EVENT_IDS 里的值
        events_noise = [(c, 31 if eid in {14, 15, 5004} else eid, 0, o)
                        for c, eid, _, o in events]
        raw = _build_mdl("test", events=events_noise)
        result = extract_sounds_binary(raw)
        assert result == set(), (
            f"非音效事件被误提取！\n"
            f"  输入 events: {events_noise}\n"
            f"  误提取:      {result}"
        )

    @given(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=50)
    def test_cycle_value_preserved(self, cycle):
        """Property: cycle 值应原样提取（四舍五入到 4 位小数）。

        边界值：0.0, 0.001, 0.9999, 1.0
        """
        events = [(cycle, 14, 0, "sound/test.wav")]
        raw = _build_mdl("test", events=events)
        result = extract_sounds_binary(raw)
        expected_cycle = round(cycle, 4)
        assert ("test", expected_cycle, "sound/test.wav") in result, (
            f"cycle={cycle} 提取错误！\n"
            f"  期望 cycle: {expected_cycle}\n"
            f"  实际结果:   {result}"
        )


# ═══════════════════════════════════════════════════════════════
# Layer 2 — 蜕变测试
# ═══════════════════════════════════════════════════════════════

class TestMetamorphic:
    """蜕变关系：对 MDL 字节做已知变换 → 验证输出按预期变化。

    MR1 (Additive): 注入一个事件 → output size +1
    MR2 (Additive): 注入 N 个事件 → output size +N
    MR3 (Permutative): 重排事件 → output 也重排（集合相等）
    """

    def test_mr1_additive_one_event(self):
        """MR1: 空 MDL → inject event → output 增加 1 条。"""
        bare = _build_mdl("seq", events=[])
        assert len(extract_sounds_binary(bare)) == 0

        modified = _build_mdl("seq", events=[(0.5, 14, 0, "sound/hit.wav")])
        result = extract_sounds_binary(modified)
        assert ("seq", 0.5, "sound/hit.wav") in result
        assert len(result) == 1

    def test_mr2_additive_multiple_events(self):
        """MR2: 注入 N 个事件 → output size = N。"""
        n = 5
        events = [(i / n, 14, 0, f"sound/{i}.wav") for i in range(n)]
        raw = _build_mdl("seq", events=events)
        result = extract_sounds_binary(raw)
        assert len(result) == n

    def test_mr3_permutative_reorder(self):
        """MR3: 重排事件顺序 → output 作为集合应相同。"""
        events = [(0.1, 14, 0, "sound/a.wav"), (0.5, 15, 0, "sound/b.wav"),
                  (0.9, 5004, 0, "sound/c.wav")]
        raw = _build_mdl("seq", events=events)
        result = extract_sounds_binary(raw)

        events_rev = list(reversed(events))
        raw_rev = _build_mdl("seq", events=events_rev)
        result_rev = extract_sounds_binary(raw_rev)

        assert result == result_rev, (
            f"重排事件后集合不等！\n"
            f"  原序: {result}\n"
            f"  逆序: {result_rev}"
        )


# ═══════════════════════════════════════════════════════════════
# Layer 3 — 异构差分测试（条件性）
# ═══════════════════════════════════════════════════════════════

_HAS_L4D2 = Path(
    r"C:\Program Files (x86)\Steam\steamapps\common\Left 4 Dead 2\left4dead2\pak01_dir.vpk"
).exists()


@pytest.mark.skipif(not _HAS_L4D2, reason="L4D2 VPK not available")
class TestDifferential:
    """异构差分：binary struct parser vs srctools.Model。

    两个独立实现解析同一二进制数据。结果不一致 → 至少一个实现有 bug。
    这是最强的 oracle-free 方法 (sect;3.2 Layer 3)。
    """

    L4D2 = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Left 4 Dead 2")
    VPK_DIRS = [
        L4D2 / "left4dead2" / "pak01_dir.vpk",
        L4D2 / "left4dead2_dlc1" / "pak01_dir.vpk",
        L4D2 / "left4dead2_dlc2" / "pak01_dir.vpk",
        L4D2 / "left4dead2_dlc3" / "pak01_dir.vpk",
    ]

    def _read_mdl(self, path: str) -> tuple[bytes, object]:
        """Read MDL bytes + srctools VPK from the appropriate VPK."""
        from srctools.filesys import VPKFileSystem

        for vpk_path in self.VPK_DIRS:
            if not vpk_path.exists():
                continue
            vpk = VPKFileSystem(str(vpk_path))
            try:
                raw = vpk[path].open_bin().read()
                return raw, vpk
            except Exception:
                continue
        pytest.skip(f"{path} not found in any VPK")

    @pytest.mark.parametrize("mdl_path", [
        "models/infected/hunter.mdl",
        "models/infected/boomer.mdl",
        "models/infected/smoker.mdl",
        "models/infected/tank.mdl",
        "models/infected/witch.mdl",
        "models/survivors/survivor_gambler.mdl",
        "models/survivors/survivor_coach.mdl",
        "models/weapons/v_pistol.mdl",
        "models/weapons/melee/w_katana.mdl",
        "models/weapons/melee/w_fireaxe.mdl",
    ])
    def test_differential_consistency(self, mdl_path: str):
        """差分断言: binary 和 srctools 的输出完全一致。

        L4D2 中没有 AE_CL_PLAYSOUND 事件（见 coverage-audit.md 验证结果），
        所以两边都应返回空集。这个测试在以下场景发现 bug：
        - binary parser 错误地提取了 event_id != 14/15/5004 的事件 → 假阳性
        - srctools 改变了事件解析方式 → 与 binary parser 不一致
        - 如果 L4D2 VPK 升级新增了音效事件，两边同时报 → 双向确认
        """
        from srctools.mdl import Model, AnimEvents

        raw, vpk = self._read_mdl(mdl_path)

        # 被测: binary 解析
        bin_result = extract_sounds_binary(raw)

        # 参考: srctools.Model
        _SET = frozenset({AnimEvents.AE_CL_PLAYSOUND,
                          AnimEvents.AE_SV_PLAYSOUND,
                          AnimEvents.CL_EVENT_SOUND})
        file_obj = vpk[mdl_path]
        model = Model(vpk, file_obj)
        st_result: set[tuple[str, float, str]] = set()
        for seq in model.sequences:
            for evt in seq.events:
                if isinstance(evt.type, AnimEvents) and evt.type in _SET:
                    st_result.add((seq.label, round(evt.cycle, 4), evt.options))

        assert bin_result == st_result, (
            f"差分不一致: {mdl_path}\n"
            f"  binary:   {bin_result}\n"
            f"  srctools: {st_result}"
        )
