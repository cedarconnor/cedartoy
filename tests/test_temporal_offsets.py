import unittest

from cedartoy.render import temporal_offsets


class TestTemporalOffsets(unittest.TestCase):
    def test_deterministic(self):
        a = temporal_offsets(8, 10)
        b = temporal_offsets(8, 10)
        self.assertEqual(a, b)

    def test_range(self):
        o = temporal_offsets(16, 5)
        self.assertTrue(all(0.0 <= x <= 1.0 for x in o))
        self.assertEqual(len(o), 16)


if __name__ == "__main__":
    unittest.main()

