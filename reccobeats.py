"""ReccoBeats audio-features client — a drop-in for Spotify's deprecated endpoint.

Spotify turned off `/audio-features` for apps created after 2024-11-27, so we
source the same metrics (valence, energy, danceability, …) from ReccoBeats,
a free service keyed on the very same Spotify track IDs.

It's a two-step lookup (both endpoints batch up to 40 IDs at a time):

  1. GET /v1/track?ids=<spotify_ids>        -> ReccoBeats track objects, each
                                               with its own `id` and an `href`
                                               back to the Spotify track.
  2. GET /v1/audio-features?ids=<recco_ids> -> the audio features per track.

`get_audio_features()` ties them together and returns `{spotify_id: features}`,
matching the shape of `spotify.get_audio_features()` so it's interchangeable.
"""

from __future__ import annotations

import re
from typing import Dict, List, Sequence

import requests

API_BASE = "https://api.reccobeats.com/v1"
BATCH = 40  # ReccoBeats returns at most 40 items per request
TIMEOUT = 25
_HEADERS = {"Accept": "application/json", "User-Agent": "MoodMap/1.0"}

# Spotify-compatible feature fields (same names mood.py expects).
_FEATURE_KEYS = (
    "valence",
    "energy",
    "danceability",
    "acousticness",
    "instrumentalness",
    "liveness",
    "speechiness",
    "loudness",
    "tempo",
    "mode",
    "key",
)

_SPOTIFY_ID_RE = re.compile(r"track[/:]([A-Za-z0-9]{22})")


class ReccoBeatsError(RuntimeError):
    """A ReccoBeats request failed or returned no usable data."""


def _chunks(seq: Sequence[str], size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def _spotify_id_from_item(item: dict) -> str | None:
    """Recover the original Spotify track id from a ReccoBeats track object."""
    for key in ("href", "url", "spotifyUrl", "externalUrl"):
        val = item.get(key)
        if isinstance(val, str):
            m = _SPOTIFY_ID_RE.search(val)
            if m:
                return m.group(1)
    # last resort: scan any string field for a Spotify track link
    for val in item.values():
        if isinstance(val, str):
            m = _SPOTIFY_ID_RE.search(val)
            if m:
                return m.group(1)
    return None


def _get(url: str, ids: Sequence[str]) -> List[dict]:
    try:
        resp = requests.get(
            url, params={"ids": ",".join(ids)}, headers=_HEADERS, timeout=TIMEOUT
        )
    except requests.RequestException as exc:
        raise ReccoBeatsError(f"Could not reach ReccoBeats: {exc}") from exc
    if resp.status_code != 200:
        raise ReccoBeatsError(
            f"ReccoBeats returned {resp.status_code}: {resp.text[:200]}"
        )
    try:
        payload = resp.json()
    except ValueError as exc:
        raise ReccoBeatsError("ReccoBeats returned invalid JSON.") from exc
    # Responses wrap their list in a `content` array.
    if isinstance(payload, dict):
        return payload.get("content") or []
    return payload if isinstance(payload, list) else []


def get_audio_features(spotify_ids: Sequence[str]) -> Dict[str, dict]:
    """Return ``{spotify_id: features}`` for the given Spotify track ids."""
    spotify_ids = [s for s in spotify_ids if s]
    if not spotify_ids:
        return {}

    # Step 1: Spotify id -> ReccoBeats id (via the returned Spotify href).
    recco_to_spotify: Dict[str, str] = {}
    for batch in _chunks(spotify_ids, BATCH):
        for item in _get(f"{API_BASE}/track", batch):
            recco_id = item.get("id")
            spotify_id = _spotify_id_from_item(item)
            if recco_id and spotify_id:
                recco_to_spotify[recco_id] = spotify_id

    if not recco_to_spotify:
        raise ReccoBeatsError(
            "ReccoBeats had no matching tracks for this library. Its catalogue "
            "may not cover these songs."
        )

    # Step 2: ReccoBeats ids -> audio features, remapped onto Spotify ids.
    out: Dict[str, dict] = {}
    recco_ids = list(recco_to_spotify)
    for batch in _chunks(recco_ids, BATCH):
        for feat in _get(f"{API_BASE}/audio-features", batch):
            spotify_id = recco_to_spotify.get(feat.get("id"))
            if spotify_id:
                out[spotify_id] = {k: feat.get(k) for k in _FEATURE_KEYS}
    return out
