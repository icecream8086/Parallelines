"""Tests for the pure-Python ICE cipher implementation."""

from __future__ import annotations

import os

from parallelines.parsers.ice import IceKey


class TestIceKeyRoundTrip:
    """Encrypt → decrypt returns the original plaintext."""

    def test_zero_key_zero_block(self) -> None:
        ice = IceKey(0)
        ice.set(b"\x00" * 8)
        pt = bytearray(8)
        ct = ice.encrypt(pt)
        dec = ice.decrypt(ct)
        assert bytes(dec) == bytes(pt)

    def test_sdhfi878_key(self) -> None:
        ice = IceKey(0)
        ice.set(b"SDhfi878")
        pt = bytearray(range(8))
        ct = ice.encrypt(pt)
        dec = ice.decrypt(ct)
        assert bytes(dec) == bytes(pt)

    def test_all_keys_same_plaintext(self) -> None:
        for _ in range(50):
            key = os.urandom(8)
            pt = os.urandom(8)
            ice = IceKey(0)
            ice.set(key)
            ct = ice.encrypt(pt)
            dec = ice.decrypt(ct)
            assert bytes(dec) == bytes(pt)

    def test_encrypt_changes_data(self) -> None:
        ice = IceKey(0)
        ice.set(b"\x00" * 8)
        pt = bytearray(b"\x01\x02\x03\x04\x05\x06\x07\x08")
        ct = ice.encrypt(pt)
        assert bytes(ct) != bytes(pt)


class TestIceKeyBuffer:
    """ECB buffer encrypt/decrypt matching Valve SDK DecodeICE."""

    def test_exact_multiple_of_block_size(self) -> None:
        data = bytes(range(16))
        ice = IceKey(0)
        ice.set(b"\x00" * 8)
        enc = ice.encrypt(data[:8]) + ice.encrypt(data[8:])
        dec = IceKey.decrypt_buffer(bytes(enc), b"\x00" * 8)
        assert dec == data

    def test_partial_final_block(self) -> None:
        data = bytes([0xFA, 0xFA, 0x00, 0x01, 0x02])  # 5 bytes (< 8)
        result = IceKey.decrypt_buffer(data, b"SDhfi878")
        assert result == data  # no full block to decrypt

    def test_mixed_full_and_partial(self) -> None:
        data = bytes(range(9))  # 1 full block + 1 byte
        enc = IceKey.decrypt_buffer(data, b"\x00" * 8)
        assert len(enc) == 9
        assert enc[-1] == 0x08  # partial final byte untouched

    def test_random_buffers(self) -> None:
        for _ in range(50):
            key = os.urandom(8)
            pt = os.urandom(os.urandom(1)[0] + 1)  # 1..256 bytes
            # ECB encrypt using single-block encrypt
            ice = IceKey(0)
            ice.set(key)
            ct = bytearray(len(pt))
            for off in range(0, len(pt) - 7, 8):
                ct[off : off + 8] = ice.encrypt(pt[off : off + 8])
            # ECB decrypt using decrypt_buffer
            dec = IceKey.decrypt_buffer(bytes(ct), key)
            assert bytes(dec[: len(pt) - (len(pt) % 8)]) == bytes(
                pt[: len(pt) - (len(pt) % 8)]
            )


class TestIceKeyKnownVector:
    """Known-answer test against ncrk C++ ICE reference."""

    def test_ncrk_vector(self) -> None:
        """Reference from ncrk ice_test.exe:

        Key: SDhfi878
        Data: FA FA 00 01 02 03 04 05  10 20 30 40 50 60 70 80
        Encrypted: BC 45 D9 8A 4C E0 A6 BE  25 F0 15 DB 71 BE 77 E1
        """
        key = b"SDhfi878"
        data = bytes([
            0xFA, 0xFA, 0x00, 0x01, 0x02, 0x03, 0x04, 0x05,
            0x10, 0x20, 0x30, 0x40, 0x50, 0x60, 0x70, 0x80,
        ])
        expected = bytes([
            0xBC, 0x45, 0xD9, 0x8A, 0x4C, 0xE0, 0xA6, 0xBE,
            0x25, 0xF0, 0x15, 0xDB, 0x71, 0xBE, 0x77, 0xE1,
        ])

        ice = IceKey(0)
        ice.set(key)
        ct = ice.encrypt(data[:8]) + ice.encrypt(data[8:])
        assert bytes(ct) == expected
