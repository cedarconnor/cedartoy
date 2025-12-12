import unittest
from pathlib import Path

from cedartoy.naming import resolve_output_path


class TestNaming(unittest.TestCase):
    def test_python_pattern(self):
        p = resolve_output_path(Path("out"), "frame_{frame:04d}.{ext}", 12, "png")
        self.assertEqual(p.as_posix(), "out/frame_0012.png")

    def test_hash_pattern(self):
        p = resolve_output_path(Path("out"), "img.####.{ext}", 7, "exr")
        self.assertEqual(p.as_posix(), "out/img.0007.exr")

    def test_static_pattern(self):
        p = resolve_output_path(Path("out"), "render", 3, "png")
        self.assertEqual(p.as_posix(), "out/render_00003.png")


if __name__ == "__main__":
    unittest.main()

