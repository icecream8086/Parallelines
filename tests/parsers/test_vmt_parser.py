"""Tests for parallelines.parsers.vmt_parser — VMT material dependency extraction."""

from __future__ import annotations

import unittest

from parallelines.parsers.vmt_parser import extract_vmt_dependencies, extract_vmt_texture_path


class TestVmtParser(unittest.TestCase):
    """Verify VMT content parsing and texture path extraction."""

    def test_extract_basetexture(self) -> None:
        """Parse $basetexture from VMT content."""
        content = (
            'VertexLitGeneric\n'
            '{\n'
            '    $basetexture "brick"\n'
            '}\n'
        )
        deps = extract_vmt_dependencies(content)
        self.assertIn("materials/brick.vtf", deps)

    def test_extract_bumpmap(self) -> None:
        """Parse $bumpmap from VMT content."""
        content = (
            'VertexLitGeneric\n'
            '{\n'
            '    $bumpmap "brick_normal"\n'
            '}\n'
        )
        deps = extract_vmt_dependencies(content)
        self.assertIn("materials/brick_normal.vtf", deps)

    def test_extract_normalmap(self) -> None:
        """Parse $normalmap from VMT content."""
        content = (
            'VertexLitGeneric\n'
            '{\n'
            '    $normalmap "metal_normal"\n'
            '}\n'
        )
        deps = extract_vmt_dependencies(content)
        self.assertIn("materials/metal_normal.vtf", deps)

    def test_missing_keys(self) -> None:
        """Content without recognised texture keys returns empty set."""
        content = (
            'UnlitGeneric\n'
            '{\n'
            '    $color "{255 255 255}"\n'
            '    $alpha 0.5\n'
            '}\n'
        )
        deps = extract_vmt_dependencies(content)
        self.assertEqual(deps, set())

    def test_path_normalisation(self) -> None:
        """Verify normalisation appends .vtf and prepends materials/."""
        content = (
            'VertexLitGeneric\n'
            '{\n'
            '    $basetexture "materials/brick"\n'
            '}\n'
        )
        deps = extract_vmt_dependencies(content)
        # Already has materials/ prefix and no extension → .vtf appended
        self.assertIn("materials/brick.vtf", deps)

    def test_path_with_extension_preserved(self) -> None:
        """If the path already has an extension, it should not be changed."""
        content = (
            'VertexLitGeneric\n'
            '{\n'
            '    $basetexture "custom/texture.tga"\n'
            '}\n'
        )
        deps = extract_vmt_dependencies(content)
        self.assertIn("materials/custom/texture.tga", deps)

    def test_path_backslashes_normalised(self) -> None:
        """Backslashes in paths are normalised to forward slashes."""
        content = (
            'VertexLitGeneric\n'
            '{\n'
            '    $basetexture "custom\\texture"\n'
            '}\n'
        )
        deps = extract_vmt_dependencies(content)
        # After normalisation: backslash → /, .vtf appended, materials/ prepended
        self.assertIn("materials/custom/texture.vtf", deps)

    def test_all_three_keys_at_once(self) -> None:
        """A VMT with basetexture, bumpmap, and normalmap should extract all three."""
        content = (
            'VertexLitGeneric\n'
            '{\n'
            '    $basetexture "metal"\n'
            '    $bumpmap "metal_normal"\n'
            '    $normalmap "metal_normal"\n'
            '}\n'
        )
        deps = extract_vmt_dependencies(content)
        self.assertIn("materials/metal.vtf", deps)
        self.assertIn("materials/metal_normal.vtf", deps)
        self.assertEqual(len(deps), 2)  # bumpmap and normalmap may share same value

    def test_extract_vmt_texture_path(self) -> None:
        """extract_vmt_texture_path returns all $-key values."""
        content = (
            'VertexLitGeneric\n'
            '{\n'
            '    $basetexture "brick"\n'
            '    $bumpmap "brick_normal"\n'
            '}\n'
        )
        values = extract_vmt_texture_path(content)
        self.assertIn("brick", values)
        self.assertIn("brick_normal", values)
        self.assertEqual(len(values), 2)

    def test_extract_vmt_texture_path_no_matches(self) -> None:
        """extract_vmt_texture_path on content without $key returns empty set."""
        values = extract_vmt_texture_path("just some text without dollar keys\n")
        self.assertEqual(values, set())

    def test_empty_content(self) -> None:
        """Empty string should produce empty set."""
        deps = extract_vmt_dependencies("")
        self.assertEqual(deps, set())

    def test_case_insensitivity(self) -> None:
        """$basetexture keys should be matched case-insensitively."""
        content = (
            'VertexLitGeneric\n'
            '{\n'
            '    $BASETEXTURE "floor"\n'
            '}\n'
        )
        deps = extract_vmt_dependencies(content)
        self.assertIn("materials/floor.vtf", deps)


if __name__ == "__main__":
    unittest.main()
