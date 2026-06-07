"""Unit tests for the mood-mapping core (no Flask / Spotify needed)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

import mood
from demo_data import generate_library


class FeatureMatrixTests(unittest.TestCase):
    def test_shape_and_normalization(self):
        tracks = [
            {"valence": 0.5, "energy": 0.5, "loudness": -30, "tempo": 125},
            {"valence": 0.1, "energy": 0.9, "loudness": 0, "tempo": 200},
        ]
        m = mood.feature_matrix(tracks)
        self.assertEqual(m.shape, (2, len(mood.FEATURE_COLUMNS)))
        # loudness -30 dB -> 0.5; tempo 125 BPM -> 0.5
        loud_idx = mood.FEATURE_COLUMNS.index("loudness")
        tempo_idx = mood.FEATURE_COLUMNS.index("tempo")
        self.assertAlmostEqual(m[0, loud_idx], 0.5, places=6)
        self.assertAlmostEqual(m[0, tempo_idx], 0.5, places=6)
        # extremes clip into [0, 1]
        self.assertTrue((m >= 0).all() and (m <= 1).all())

    def test_missing_values_default(self):
        m = mood.feature_matrix([{}])
        self.assertEqual(m.shape, (1, len(mood.FEATURE_COLUMNS)))
        self.assertFalse(np.isnan(m).any())


class DirectMapTests(unittest.TestCase):
    def test_quadrants(self):
        tracks = [
            {"valence": 0.9, "energy": 0.9},  # happy + energetic
            {"valence": 0.1, "energy": 0.1},  # sad + calm
        ]
        c = mood.direct_coords(tracks)
        self.assertGreater(c[0, 0], 0)  # happy -> x > 0
        self.assertGreater(c[0, 1], 0)  # energetic -> y > 0
        self.assertLess(c[1, 0], 0)
        self.assertLess(c[1, 1], 0)


class CoordinateTests(unittest.TestCase):
    def setUp(self):
        self.lib = generate_library(n_tracks=120, seed=1)

    def test_all_methods_in_range(self):
        for method in ("direct", "pca", "tsne"):
            coords = mood.mood_coordinates(self.lib, method)
            self.assertEqual(coords.shape, (len(self.lib), 2))
            self.assertTrue((coords >= -1.0001).all())
            self.assertTrue((coords <= 1.0001).all())

    def test_reduced_axes_align_with_mood(self):
        # After orientation, x should correlate with valence and y with energy.
        valence = np.array([t["valence"] for t in self.lib])
        energy = np.array([t["energy"] for t in self.lib])
        coords = mood.mood_coordinates(self.lib, "pca")
        self.assertGreater(np.corrcoef(coords[:, 0], valence)[0, 1], 0.3)
        self.assertGreater(np.corrcoef(coords[:, 1], energy)[0, 1], 0.3)

    def test_attach_coordinates_adds_xy(self):
        out = mood.attach_coordinates(self.lib[:10], "direct")
        self.assertTrue(all("x" in t and "y" in t for t in out))
        # original dicts untouched
        self.assertNotIn("x", self.lib[0])

    def test_small_library_falls_back_to_direct(self):
        coords = mood.mood_coordinates(self.lib[:2], "tsne")
        self.assertEqual(coords.shape, (2, 2))

    def test_select_region(self):
        out = mood.attach_coordinates(self.lib, "direct")
        sel = mood.select_region(out, 0, 1, 0, 1)  # happy+energetic quadrant
        self.assertTrue(all(t["x"] >= 0 and t["y"] >= 0 for t in sel))
        self.assertLess(len(sel), len(out))


if __name__ == "__main__":
    unittest.main()
