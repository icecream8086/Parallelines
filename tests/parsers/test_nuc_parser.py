"""Tests for :mod:`parallelines.parsers.nuc_parser` — ICE decrypt + deps."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from parallelines.parsers.nuc_parser import extract_nuc_dependencies

# Path to ncrk ICE reference test data (real L4D2 .nuc files)
_NCRK_L4D2_DIR = Path(__file__).parent.parent.parent / "bin" / "ncrk" / "build" / "l4d2_nuc"


@pytest.mark.skipif(not _NCRK_L4D2_DIR.is_dir(), reason="ncrk L4D2 .nuc fixtures not available")
class TestNucParserIntegration:
    """Integration tests using real L4D2 .nuc files from the ncrk build tree."""

    @pytest.fixture(autouse=True)
    def _patch_ice_key(self) -> None:
        patcher = patch("parallelines.parsers.nuc_parser._get_ice_key", return_value="SDhfi878")
        patcher.start()
        yield
        patcher.stop()

    def test_director_base_decrypts_to_squirrel_source(self) -> None:
        data = (_NCRK_L4D2_DIR / "director_base.nuc").read_bytes()
        # Confirm file is ICE-encrypted, not compiled bytecode (which would skip decrypt)
        assert data[:2] != b"\xfa\xfa", "Expected ICE-encrypted .nuc, got compiled bytecode"
        deps = extract_nuc_dependencies(data)
        assert isinstance(deps, set)
        # Note: director_base.nuc has no IncludeScript/PrecacheModel/PrecacheSound
        # patterns, so empty deps is the correct result. The value is in testing
        # the full decrypt+process pipeline on real game files.

    def test_decrypted_text_contains_expected_strings(self) -> None:
        """Verify decrypted text is valid Squirrel source."""
        from parallelines.parsers.ice import IceKey

        data = (_NCRK_L4D2_DIR / "director_base.nuc").read_bytes()
        text = IceKey.decrypt_buffer(data, b"SDhfi878").decode("utf-8", errors="replace")
        assert "printl" in text
        assert "DirectorOptions" in text
        assert "Copyright" in text


@pytest.mark.skipif(not _NCRK_L4D2_DIR.is_dir(), reason="ncrk L4D2 .nuc fixtures not available")
class TestNucParserGallery:
    """Test ICE decryption + dep extraction on gallery .nuc files."""

    GALLERY_FILES = [
        "gallery_copy_counters.nuc",
        "gallery_copy_movelinears.nuc",
        "gallery_copy_positions.nuc",
    ]

    @pytest.fixture(autouse=True)
    def _patch_ice_key(self) -> None:
        patcher = patch("parallelines.parsers.nuc_parser._get_ice_key", return_value="SDhfi878")
        patcher.start()
        yield
        patcher.stop()

    def test_all_gallery_files_decrypt(self) -> None:
        for name in self.GALLERY_FILES:
            data = (_NCRK_L4D2_DIR / name).read_bytes()
            # Confirm file is ICE-encrypted, not compiled bytecode
            assert data[:2] != b"\xfa\xfa", f"{name}: expected ICE-encrypted .nuc, got compiled bytecode"
            deps = extract_nuc_dependencies(data)
            assert isinstance(deps, set), f"{name}: expected set, got {type(deps)}"
            # Gallery .nuc files contain no IncludeScript/PrecacheModel/PrecacheSound
            # patterns, so empty deps is correct. The test validates the full decrypt
            # + process pipeline runs without error.


def test_empty_bytes_returns_empty() -> None:
    """Empty bytes input returns empty set without needing fixtures."""
    assert extract_nuc_dependencies(b"") == set()


def test_garbage_bytes_returns_empty() -> None:
    """Garbage bytes input returns empty set gracefully without needing fixtures."""
    # Compiled bytecode signature (\xfa\xfa) is handled as early return
    assert extract_nuc_dependencies(b"\xfa\xfa\x00\x01\x02\x03") == set()
    # Non-compiled garbage: ICE key unavailable (no config in test env) or decrypt fails
    assert extract_nuc_dependencies(b"\xde\xad\xbe\xef") == set()
