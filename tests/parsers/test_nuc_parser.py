"""Tests for :mod:`parallelines.parsers.nuc_parser` — ICE decrypt + deps."""

from __future__ import annotations

from pathlib import Path

import pytest

from parallelines.parsers.nuc_parser import extract_nuc_dependencies

# Path to ncrk ICE reference test data (real L4D2 .nuc files)
_NCRK_L4D2_DIR = Path(__file__).parent.parent.parent / "bin" / "ncrk" / "build" / "l4d2_nuc"


@pytest.mark.skipif(not _NCRK_L4D2_DIR.is_dir(), reason="ncrk L4D2 .nuc fixtures not available")
class TestNucParserIntegration:
    """Integration tests using real L4D2 .nuc files from the ncrk build tree."""

    def test_director_base_decrypts_to_squirrel_source(self) -> None:
        data = (_NCRK_L4D2_DIR / "director_base.nuc").read_bytes()
        deps = extract_nuc_dependencies(data)
        assert isinstance(deps, set)

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

    def test_all_gallery_files_decrypt(self) -> None:
        for name in self.GALLERY_FILES:
            data = (_NCRK_L4D2_DIR / name).read_bytes()
            deps = extract_nuc_dependencies(data)
            assert isinstance(deps, set), f"{name}: expected set, got {type(deps)}"
