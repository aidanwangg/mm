"""Audio-features fallback via ReccoBeats.

Spotify deprecated its ``/audio-features`` endpoint for apps created after
2024-11-27, so a freshly created app gets a 403 and the mood map has nothing to
plot. `ReccoBeats <https://reccobeats.com>`_ exposes a drop-in replacement keyed
by Spotify track id, returning the same descriptors (valence, energy, …). We use
it to keep live mode working with a real library.

Endpoint (confirmed against the public API):
    GET https://api.reccobeats.com/v1/audio-features?ids=<comma-separated ids>
accepting up to 40 Spotify track ids per request.
"""

from __future__ import annotations

import re
import time
from typing import Dict, List, Optional, Sequence

import requests

API_BASE = "https://api.reccobeats.com/v1"
BATCH = 40  # ReccoBeats accepts up to 40 ids per request.

# Feature fields the app cares about (ReccoBeats mirrors Spotify's names).
# mode/key aren't always present; mood.py supplies safe defaults if missing.
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

_SPOTIFY_ID_RE = re.compile(r"/track/([A-Za-z0-9]+)")


class ReccoBeatsError(RuntimeError):
    """A ReccoBeats request failed."""


def _items(payload) -> List[dict]:
    """Normalise the response into a list of feature objects.

    ReccoBeats has returned results either as a bare list or wrapped under a
    ``content``/``data`` key depending on the endpoint, so accept both.
    """
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("content", "audio_features", "data", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _spotify_id_from(item: dict) -> Optional[str]:
    """Recover the Spotify track id an item refers to, via its ``href``."""
    href = item.get("href") or ""
    match = _SPOTIFY_ID_RE.search(href)
    if match:
        return match.group(1)
    # Some payloads echo the queried id under a dedicated field.
    return item.get("spotifyId") or item.get("trackId")


def get_audio_features(track_ids: Sequence[str]) -> Dict[str, dict]:
    """Return ``{spotify_id: features}`` from ReccoBeats for the given ids."""
    ids = [t for t in track_ids if t]
    out: Dict[str, dict] = {}

    for start in range(0, len(ids), BATCH):
        batch = ids[start : start + BATCH]
        try:
            resp = requests.get(
                f"{API_BASE}/audio-features",
                params={"ids": ",".join(batch)},
                timeout=20,
            )
        except requests.RequestException as exc:
            raise ReccoBeatsError(f"ReccoBeats request failed: {exc}") from exc
        if resp.status_code != 200:
            raise ReccoBeatsError(
                f"ReccoBeats audio-features failed: "
                f"{resp.status_code} {resp.text[:200]}"
            )

        items = _items(resp.json())
        for idx, item in enumerate(items):
            # Prefer the href mapping; fall back to request order if the batch
            # came back 1:1 without identifying fields.
            sid = _spotify_id_from(item)
            if not sid and len(items) == len(batch):
                sid = batch[idx]
            if not sid:
                continue
            out[sid] = {k: item.get(k) for k in _FEATURE_KEYS}

        time.sleep(0.1)  # stay under the rate limit on large libraries

    return out
