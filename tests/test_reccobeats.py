"""Unit tests for the ReccoBeats feature client (HTTP mocked — no network)."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import reccobeats


class SpotifyIdParsingTests(unittest.TestCase):
    def test_from_href(self):
        item = {"id": "recco-1", "href": "https://open.spotify.com/track/0VjIjW4GlUZAMYd2vXMi3b"}
        self.assertEqual(reccobeats._spotify_id_from_item(item), "0VjIjW4GlUZAMYd2vXMi3b")

    def test_from_uri_style(self):
        item = {"id": "r", "url": "spotify:track:3n3Ppam7vgaVa1iaRUc9Lp"}
        self.assertEqual(reccobeats._spotify_id_from_item(item), "3n3Ppam7vgaVa1iaRUc9Lp")

    def test_none_when_absent(self):
        self.assertIsNone(reccobeats._spotify_id_from_item({"id": "r", "name": "x"}))


class GetAudioFeaturesTests(unittest.TestCase):
    def test_two_step_lookup_and_remap(self):
        sid = "0VjIjW4GlUZAMYd2vXMi3b"
        track_payload = {"content": [
            {"id": "recco-xyz", "href": f"https://open.spotify.com/track/{sid}"},
        ]}
        feat_payload = {"content": [
            {"id": "recco-xyz", "valence": 0.5, "energy": 0.8, "danceability": 0.7,
             "acousticness": 0.1, "instrumentalness": 0.0, "liveness": 0.2,
             "speechiness": 0.05, "loudness": -6.0, "tempo": 120.0, "mode": 1, "key": 5},
        ]}

        def fake_get(url, ids):
            return track_payload["content"] if url.endswith("/track") else feat_payload["content"]

        with mock.patch.object(reccobeats, "_get", side_effect=fake_get):
            out = reccobeats.get_audio_features([sid])

        self.assertIn(sid, out)
        self.assertEqual(out[sid]["valence"], 0.5)
        self.assertEqual(out[sid]["energy"], 0.8)
        # keyed by Spotify id, not the ReccoBeats id
        self.assertNotIn("recco-xyz", out)

    def test_empty_input(self):
        self.assertEqual(reccobeats.get_audio_features([]), {})

    def test_no_matches_raises(self):
        with mock.patch.object(reccobeats, "_get", return_value=[]):
            with self.assertRaises(reccobeats.ReccoBeatsError):
                reccobeats.get_audio_features(["someid"])


if __name__ == "__main__":
    unittest.main()
