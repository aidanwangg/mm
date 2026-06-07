"""Synthetic-but-plausible library for the no-credentials demo mode.

Real Spotify audio features can't be fetched in an environment without OAuth
credentials (and Spotify deprecated the `/audio-features` endpoint for newly
created apps in late 2024). To keep the project runnable and reviewable
anywhere, we generate a believable library: a few mood *archetypes* scattered
across the Sad↔Happy / Calm↔Energetic plane, each with its own feature
distribution and procedurally-named tracks.

The data is deterministic (fixed seed) so the map looks the same every run.
"""

from __future__ import annotations

from typing import List

import numpy as np

# Each archetype anchors a region of the mood plane and a musical "feel".
# Values are means for the audio features; spread is added per track.
_ARCHETYPES = [
    # name, valence, energy, danceability, acousticness, instrumentalness, tempo, mode, genre
    ("Melancholy Ballads", 0.18, 0.20, 0.32, 0.82, 0.10, 72, 0, "singer-songwriter"),
    ("Rainy-Day Indie", 0.30, 0.38, 0.45, 0.55, 0.18, 96, 0, "indie"),
    ("Late-Night Lo-Fi", 0.40, 0.30, 0.58, 0.48, 0.62, 84, 1, "lo-fi"),
    ("Ambient Drift", 0.35, 0.16, 0.22, 0.70, 0.88, 70, 1, "ambient"),
    ("Feel-Good Pop", 0.82, 0.74, 0.74, 0.18, 0.02, 118, 1, "pop"),
    ("Summer Dance", 0.88, 0.88, 0.82, 0.08, 0.05, 124, 1, "dance"),
    ("Stadium Rock", 0.62, 0.90, 0.52, 0.10, 0.06, 140, 1, "rock"),
    ("Hype Hip-Hop", 0.55, 0.80, 0.85, 0.12, 0.01, 100, 0, "hip-hop"),
    ("Angsty Punk", 0.30, 0.92, 0.46, 0.06, 0.04, 168, 0, "punk"),
    ("Golden-Hour Funk", 0.78, 0.66, 0.86, 0.20, 0.03, 110, 1, "funk"),
    ("Coffeehouse Acoustic", 0.60, 0.34, 0.50, 0.86, 0.05, 92, 1, "acoustic"),
    ("Cinematic Epic", 0.45, 0.62, 0.30, 0.40, 0.80, 95, 1, "soundtrack"),
]

_ADJECTIVES = [
    "Velvet", "Neon", "Paper", "Golden", "Midnight", "Crystal", "Electric",
    "Hollow", "Silver", "Wild", "Quiet", "Restless", "Distant", "Bright",
    "Faded", "Lonely", "Endless", "Burning", "Frozen", "Crimson", "Gentle",
    "Glass", "Hazy", "Tender", "Reckless",
]
_NOUNS = [
    "Skyline", "Heartbeat", "Echo", "Horizon", "Daydream", "Cathedral",
    "Riverbank", "Static", "Lantern", "Avenue", "Mirage", "Tide", "Ember",
    "Halo", "Static", "Compass", "Meadow", "Satellite", "Anchor", "Pulse",
    "Wildfire", "Lullaby", "Gravity", "Sunrise", "Afterglow",
]
_ARTIST_FIRST = [
    "The", "Saint", "Young", "Little", "Holy", "Cosmic", "Velvet", "Paper",
    "Northern", "Lunar", "Wax", "Blue",
]
_ARTIST_SECOND = [
    "Foxes", "Arrows", "Tigers", "Ghosts", "Waves", "Lions", "Embers",
    "Saints", "Rivers", "Echoes", "Kids", "Hearts", "Coast", "Machines",
]


def _name(rng: np.random.Generator) -> str:
    return f"{rng.choice(_ADJECTIVES)} {rng.choice(_NOUNS)}"


def _artist(rng: np.random.Generator) -> str:
    if rng.random() < 0.5:
        return f"{rng.choice(_ARTIST_FIRST)} {rng.choice(_ARTIST_SECOND)}"
    return f"{rng.choice(_NOUNS)} {rng.choice(_ARTIST_SECOND)}"


def _clip01(x: float) -> float:
    return float(np.clip(x, 0.0, 1.0))


def generate_library(n_tracks: int = 420, seed: int = 7) -> List[dict]:
    """Return a list of synthetic track dicts shaped like Spotify data."""
    rng = np.random.default_rng(seed)
    tracks: List[dict] = []
    per = max(1, n_tracks // len(_ARCHETYPES))

    track_id = 0
    for (name, val, eng, dance, acoust, instr, tempo, mode, genre) in _ARCHETYPES:
        for _ in range(per):
            track_id += 1
            year = int(rng.integers(1995, 2025))
            tracks.append(
                {
                    "id": f"demo{track_id:04d}",
                    "name": _name(rng),
                    "artist": _artist(rng),
                    "album": f"{name}",
                    "genre": genre,
                    "year": year,
                    "popularity": int(np.clip(rng.normal(55, 22), 1, 100)),
                    "valence": _clip01(rng.normal(val, 0.08)),
                    "energy": _clip01(rng.normal(eng, 0.08)),
                    "danceability": _clip01(rng.normal(dance, 0.10)),
                    "acousticness": _clip01(rng.normal(acoust, 0.12)),
                    "instrumentalness": _clip01(rng.normal(instr, 0.10)),
                    "liveness": _clip01(rng.normal(0.16, 0.10)),
                    "speechiness": _clip01(rng.normal(0.08, 0.05)),
                    "loudness": float(np.clip(rng.normal(-8 + eng * 6, 2.5), -30, 0)),
                    "tempo": float(np.clip(rng.normal(tempo, 8), 50, 200)),
                    "mode": int(mode if rng.random() < 0.8 else 1 - mode),
                    "key": int(rng.integers(0, 12)),
                }
            )

    rng.shuffle(tracks)
    return tracks


if __name__ == "__main__":  # pragma: no cover - manual sanity check
    lib = generate_library()
    print(f"Generated {len(lib)} demo tracks. First entry:")
    for k, v in lib[0].items():
        print(f"  {k}: {v}")
