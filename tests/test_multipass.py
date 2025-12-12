import unittest
from pathlib import Path

from cedartoy.cli import parse_multipass


class TestMultipass(unittest.TestCase):
    def test_toposort_ignores_self_feedback(self):
        cfg = {
            "multipass": {
                "buffers": {
                    "A": {
                        "shader": "shaders/test.glsl",
                        "channels": {0: "A"},
                    },
                    "Image": {
                        "shader": "shaders/test.glsl",
                        "outputs_to_screen": True,
                        "channels": {0: "A"},
                    },
                }
            }
        }
        mp = parse_multipass(cfg, Path("shaders/test.glsl"))
        self.assertEqual(mp.execution_order[-1], "Image")
        self.assertIn("A", mp.execution_order)

    def test_requires_single_screen_buffer(self):
        cfg = {
            "multipass": {
                "buffers": {
                    "A": {"shader": "shaders/test.glsl", "outputs_to_screen": True},
                    "Image": {"shader": "shaders/test.glsl", "outputs_to_screen": True},
                }
            }
        }
        with self.assertRaises(ValueError):
            parse_multipass(cfg, Path("shaders/test.glsl"))

    def test_screen_buffer_must_be_last(self):
        cfg = {
            "multipass": {
                "buffers": {
                    "A": {"shader": "shaders/test.glsl"},
                    "Image": {"shader": "shaders/test.glsl", "outputs_to_screen": True, "channels": {0: "A"}},
                },
                "execution_order": ["Image", "A"],
            }
        }
        with self.assertRaises(ValueError):
            parse_multipass(cfg, Path("shaders/test.glsl"))


if __name__ == "__main__":
    unittest.main()

