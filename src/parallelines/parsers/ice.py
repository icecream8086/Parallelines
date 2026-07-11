"""Pure Python implementation of the ICE (Information Concealment Engine) cipher.

Port of ValveSoftware/source-sdk-2013 → src/mathlib/IceKey.cpp.
Matthew Kwan, July 1996. Public domain.

Used by L4D2 (and other Source Engine games) to encrypt .nuc Squirrel scripts.
"""

from __future__ import annotations

# Modulo values for S-box GF(2^3) exponentiation
_SMOD: list[list[int]] = [
    [333, 313, 505, 369],
    [379, 375, 319, 391],
    [361, 445, 451, 397],
    [397, 425, 395, 505],
]

# XOR values for the S-boxes
_SXOR: list[list[int]] = [
    [0x83, 0x85, 0x9B, 0xCD],
    [0xCC, 0xA7, 0xAD, 0x41],
    [0x4B, 0x2E, 0xD4, 0x33],
    [0xEA, 0xCB, 0x2E, 0x04],
]

# P-box permutation table
# If input bit b is set, OR _PBOX[b] into output
_PBOX: list[int] = [
    0x00000001, 0x00000080, 0x00000400, 0x00002000,
    0x00080000, 0x00200000, 0x01000000, 0x40000000,
    0x00000008, 0x00000020, 0x00000100, 0x00004000,
    0x00010000, 0x00800000, 0x04000000, 0x20000000,
    0x00000004, 0x00000010, 0x00000200, 0x00008000,
    0x00020000, 0x00400000, 0x08000000, 0x10000000,
    0x00000002, 0x00000040, 0x00000800, 0x00001000,
    0x00040000, 0x00100000, 0x02000000, 0x80000000,
]

# Key rotation schedule
_KEYROT: list[int] = [
    0, 1, 2, 3, 2, 1, 3, 0,
    1, 3, 2, 0, 3, 1, 0, 2,
]


class IceKey:
    """ICE 64-bit block cipher.

    Level 0 (Thin-ICE): 8 rounds, 8-byte key.
    Level N: 16*N rounds, 8*N byte key.
    """

    _sbox: list[list[int]] = [[0] * 1024 for _ in range(4)]
    _sboxes_initialised: bool = False

    def __init__(self, level: int = 0) -> None:
        if not IceKey._sboxes_initialised:
            IceKey._init_sboxes()
        self._rounds: int = 8 if level < 1 else level * 16
        self._size: int = 1 if level < 1 else level
        # _keysched[round][0..2] — three 32-bit subkey words per round
        self._keysched: list[list[int]] = [[0, 0, 0] for _ in range(self._rounds)]

    # ------------------------------------------------------------------
    # GF(2^3) arithmetic helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _gf_mult(a: int, b: int, m: int) -> int:
        """8-bit Galois Field multiplication of a by b, modulo m."""
        res = 0
        while b:
            if b & 1:
                res ^= a
            a <<= 1
            b >>= 1
            if a >= 256:
                a ^= m
        return res

    @staticmethod
    def _gf_exp7(b: int, m: int) -> int:
        """Galois Field exponentiation — compute b^7 modulo m."""
        if b == 0:
            return 0
        x = IceKey._gf_mult(b, b, m)      # b^2
        x = IceKey._gf_mult(b, x, m)      # b^3
        x = IceKey._gf_mult(x, x, m)      # b^6
        return IceKey._gf_mult(b, x, m)   # b^7

    # ------------------------------------------------------------------
    # P-box permutation
    # ------------------------------------------------------------------

    @staticmethod
    def _perm32(x: int) -> int:
        """32-bit P-box permutation — same as Valve SDK ice_perm32."""
        res = 0
        pbox_idx = 0
        while x:
            if x & 1:
                res |= _PBOX[pbox_idx]
            pbox_idx += 1
            x >>= 1
        return res

    # ------------------------------------------------------------------
    # S-box initialisation
    # ------------------------------------------------------------------

    @staticmethod
    def _init_sboxes() -> None:
        """Initialise the 4 ICE S/P-boxes (1024 entries each)."""
        for i in range(1024):
            col = (i >> 1) & 0xFF
            row = (i & 0x1) | ((i & 0x200) >> 8)

            for box in range(4):
                val = IceKey._gf_exp7(col ^ _SXOR[box][row], _SMOD[box][row])
                IceKey._sbox[box][i] = IceKey._perm32(val << (24 - box * 8))

        IceKey._sboxes_initialised = True

    # ------------------------------------------------------------------
    # Round function
    # ------------------------------------------------------------------

    @staticmethod
    def _ice_f(p: int, sk: list[int]) -> int:
        """Single-round ICE f-function.

        Args:
            p: 32-bit input value.
            sk: Three 32-bit subkey words [sk0, sk1, sk2].

        Returns:
            32-bit output after S-box lookup and permutation.
        """
        # Expand 32-bit p into two 20-bit values
        tl = ((p >> 16) & 0x3FF) | (((p >> 14) | (p << 18)) & 0xFFC00)
        tr = (p & 0x3FF) | ((p << 2) & 0xFFC00)

        # Salt permutation (sk[2] is the salt)
        al = sk[2] & (tl ^ tr)
        ar = al ^ tr
        al ^= tl

        # XOR with subkey material
        al ^= sk[0]
        ar ^= sk[1]

        # S-box lookup and combine
        return (
            IceKey._sbox[0][al >> 10]
            | IceKey._sbox[1][al & 0x3FF]
            | IceKey._sbox[2][ar >> 10]
            | IceKey._sbox[3][ar & 0x3FF]
        )

    # ------------------------------------------------------------------
    # Key schedule
    # ------------------------------------------------------------------

    def _schedule_build(self, kb: list[int], n: int, keyrot: list[int]) -> None:
        """Set 8 rounds [n, n+7] of the key schedule."""
        for i in range(8):
            kr = keyrot[i]
            isk = [0, 0, 0]

            for j in range(15):
                curr_sk_idx = j % 3
                for k in range(4):
                    curr_kb_idx = (kr + k) & 3
                    bit = kb[curr_kb_idx] & 1
                    isk[curr_sk_idx] = (isk[curr_sk_idx] << 1) | bit
                    kb[curr_kb_idx] = (kb[curr_kb_idx] >> 1) | ((bit ^ 1) << 15)

            self._keysched[n + i] = isk

    def set(self, key: bytes) -> None:
        """Set the key schedule from an 8-byte (or multi-level) key.

        Args:
            key: Key bytes. Must be ``self._size * 8`` bytes.
        """
        if self._rounds == 8:
            kb = [0] * 4
            for i in range(4):
                kb[3 - i] = (key[i * 2] << 8) | key[i * 2 + 1]
            self._schedule_build(kb, 0, _KEYROT)
        else:
            for i in range(self._size):
                kb = [0] * 4
                for j in range(4):
                    kb[3 - j] = (key[i * 8 + j * 2] << 8) | key[i * 8 + j * 2 + 1]
                self._schedule_build(kb, i * 8, _KEYROT)
                self._schedule_build(kb, self._rounds - 8 - i * 8, _KEYROT[8:])

    # ------------------------------------------------------------------
    # Encrypt / Decrypt (single 8-byte block)
    # ------------------------------------------------------------------

    def encrypt(self, block: bytes | bytearray) -> bytearray:
        """Encrypt a single 8-byte block. Returns 8 bytes."""
        l_ = (block[0] << 24) | (block[1] << 16) | (block[2] << 8) | block[3]
        r = (block[4] << 24) | (block[5] << 16) | (block[6] << 8) | block[7]

        for i in range(0, self._rounds, 2):
            l_ ^= IceKey._ice_f(r, self._keysched[i])
            r ^= IceKey._ice_f(l_, self._keysched[i + 1])

        out = bytearray(8)
        for i in range(4):
            out[3 - i] = r & 0xFF
            out[7 - i] = l_ & 0xFF
            r >>= 8
            l_ >>= 8
        return out

    def decrypt(self, block: bytes | bytearray) -> bytearray:
        """Decrypt a single 8-byte block. Returns 8 bytes."""
        l_ = (block[0] << 24) | (block[1] << 16) | (block[2] << 8) | block[3]
        r = (block[4] << 24) | (block[5] << 16) | (block[6] << 8) | block[7]

        for i in range(self._rounds - 1, 0, -2):
            l_ ^= IceKey._ice_f(r, self._keysched[i])
            r ^= IceKey._ice_f(l_, self._keysched[i - 1])

        out = bytearray(8)
        for i in range(4):
            out[3 - i] = r & 0xFF
            out[7 - i] = l_ & 0xFF
            r >>= 8
            l_ >>= 8
        return out

    # ------------------------------------------------------------------
    # Static convenience: ECB decrypt an entire buffer (Valve DecodeICE)
    # ------------------------------------------------------------------

    @staticmethod
    def decrypt_buffer(data: bytes, key: bytes) -> bytes:
        """ECB-decrypt an ICE-encrypted buffer in place (full blocks only).

        Partial final block (less than 8 bytes) is left untouched, matching
        Valve SDK's ``DecodeICE`` behaviour.

        Args:
            data: Encrypted bytes.
            key: 8-byte ICE key.

        Returns:
            Decrypted bytes. Same length as *data*.
        """
        ice = IceKey(0)
        ice.set(key)
        result = bytearray(data)
        for offset in range(0, len(data) - 7, 8):
            decrypted = ice.decrypt(data[offset : offset + 8])
            result[offset : offset + 8] = decrypted
        return bytes(result)
