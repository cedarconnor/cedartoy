import unittest
from pathlib import Path

from cedartoy.render import subpixel_jitter, temporal_offsets

ROOT = Path(__file__).parent.parent


class TestTemporalOffsets(unittest.TestCase):
    def test_deterministic(self):
        a = temporal_offsets(8, 10)
        b = temporal_offsets(8, 10)
        self.assertEqual(a, b)

    def test_range(self):
        o = temporal_offsets(16, 5)
        self.assertTrue(all(0.0 <= x <= 1.0 for x in o))
        self.assertEqual(len(o), 16)

    def test_single_temporal_sample_is_centered(self):
        for frame_index in range(10):
            self.assertEqual(temporal_offsets(1, frame_index), [0.5])


class TestSubpixelJitter(unittest.TestCase):
    def test_single_temporal_sample_has_no_jitter(self):
        for frame_index in range(10):
            self.assertEqual(subpixel_jitter(0, frame_index, 1), (0.0, 0.0))


class TestTemporalArtifactGuards(unittest.TestCase):
    def test_bumped_warp_does_not_use_discontinuous_animated_hash_jitter(self):
        shader_paths = [
            ROOT / "shaders" / "4l2XWK_bumped_warp.glsl",
            ROOT / "shaders" / "bumped_warp" / "image.glsl",
            ROOT / "shaders" / "bumped_warp" / "noise.glsl",
        ]
        bad_patterns = [
            "fract(sin(p+vec2(13, 7))*5e5)",
            "hash(uv * 100.0 + iTime * 0.1)",
        ]

        offenders = []
        for shader_path in shader_paths:
            text = shader_path.read_text(encoding="utf-8")
            for pattern in bad_patterns:
                if pattern in text:
                    offenders.append(f"{shader_path.name}: {pattern}")

        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
