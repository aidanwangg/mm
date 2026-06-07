"""Mood mapping: turn Spotify audio features into 2-D coordinates.

Two families of projection are supported (the web UI lets you switch between
them live):

  * **Direct** — the most interpretable map. The X-axis is *valence*
    (Sad ↔ Happy) and the Y-axis is *energy* (Calm ↔ Energetic). These are
    Spotify audio features designed for exactly this, so no learning needed.

  * **Reduced** — squeeze *all* the audio features down to two dimensions with
    PCA, t-SNE or UMAP, then rotate/scale that embedding so it lines up with
    the mood axes above. You keep the "Sad↔Happy / Calm↔Energetic" reading of
    the plot while letting the full feature space decide who sits near whom.

Everything here is pure NumPy / scikit-learn and has no Flask or Spotify
dependency, so it is easy to unit-test in isolation.
"""

from __future__ import annotations

from typing import Iterable, List, Sequence

import numpy as np

# Audio features fed into the dimensionality reduction. Order matters: it
# defines the columns of the feature matrix.
FEATURE_COLUMNS: List[str] = [
    "valence",
    "energy",
    "danceability",
    "acousticness",
    "instrumentalness",
    "liveness",
    "speechiness",
    "loudness",   # dB, normalised below
    "tempo",      # BPM, normalised below
    "mode",       # 0 = minor, 1 = major
]

# The two features that *define* the mood axes, used to orient reduced
# embeddings so the plot stays interpretable.
X_FEATURE = "valence"   # Sad ↔ Happy
Y_FEATURE = "energy"    # Calm ↔ Energetic

VALID_METHODS = ("direct", "pca", "tsne", "umap")


def _get(track: dict, key: str, default: float = 0.0) -> float:
    value = track.get(key, default)
    if value is None:
        return default
    return float(value)


def feature_matrix(tracks: Sequence[dict]) -> np.ndarray:
    """Build an (n_tracks, n_features) matrix from raw Spotify feature dicts.

    Loudness and tempo are rescaled onto roughly 0..1 so every column lives on
    a comparable range before standardisation; the rest already do.
    """
    rows = []
    for t in tracks:
        row = []
        for col in FEATURE_COLUMNS:
            v = _get(t, col)
            if col == "loudness":
                # Spotify loudness is roughly -60..0 dB.
                v = np.clip((v + 60.0) / 60.0, 0.0, 1.0)
            elif col == "tempo":
                # Most music sits between ~50 and ~200 BPM.
                v = np.clip((v - 50.0) / 150.0, 0.0, 1.0)
            row.append(v)
        rows.append(row)
    return np.asarray(rows, dtype=float)


def _standardize(matrix: np.ndarray) -> np.ndarray:
    mean = matrix.mean(axis=0)
    std = matrix.std(axis=0)
    std[std == 0] = 1.0
    return (matrix - mean) / std


def direct_coords(tracks: Sequence[dict]) -> np.ndarray:
    """Map valence/energy (0..1) onto a centred [-1, 1] mood plane."""
    valence = np.array([_get(t, X_FEATURE, 0.5) for t in tracks])
    energy = np.array([_get(t, Y_FEATURE, 0.5) for t in tracks])
    return np.column_stack([valence * 2.0 - 1.0, energy * 2.0 - 1.0])


def _orient_to_mood(embedding: np.ndarray, tracks: Sequence[dict]) -> np.ndarray:
    """Rotate/scale a 2-D embedding so it aligns with the mood axes.

    We fit the best linear map (a 2x2 transform allowing rotation, scaling and
    reflection) from the embedding to the *direct* mood coordinates via least
    squares. This keeps neighbourhoods from the reduction intact while making
    the X-axis read as Sad↔Happy and the Y-axis as Calm↔Energetic.
    """
    target = direct_coords(tracks)
    emb = embedding - embedding.mean(axis=0)
    tgt = target - target.mean(axis=0)
    # Solve emb @ A ≈ tgt for the 2x2 matrix A.
    a, *_ = np.linalg.lstsq(emb, tgt, rcond=None)
    return emb @ a


def _normalize_fill(coords: np.ndarray, pct: float = 99.0) -> np.ndarray:
    """Scale coordinates so they fill [-1, 1], clipping extreme outliers."""
    coords = coords - np.median(coords, axis=0)
    scale = np.percentile(np.abs(coords), pct, axis=0)
    scale[scale == 0] = 1.0
    return np.clip(coords / scale, -1.0, 1.0)


def _reduce(matrix: np.ndarray, method: str, seed: int = 42) -> np.ndarray:
    n = matrix.shape[0]
    data = _standardize(matrix)

    if method == "pca":
        from sklearn.decomposition import PCA

        return PCA(n_components=2, random_state=seed).fit_transform(data)

    if method == "tsne":
        from sklearn.manifold import TSNE

        # Perplexity must be < n_samples; keep it sane for small libraries.
        perplexity = float(max(5, min(30, (n - 1) // 3)))
        tsne = TSNE(
            n_components=2,
            random_state=seed,
            perplexity=perplexity,
            init="pca",
        )
        return tsne.fit_transform(data)

    if method == "umap":
        try:
            import umap  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "UMAP is not installed. Run `pip install umap-learn` or pick "
                "another projection (PCA / t-SNE / Direct)."
            ) from exc

        n_neighbors = int(max(2, min(15, n - 1)))
        reducer = umap.UMAP(
            n_components=2,
            random_state=seed,
            n_neighbors=n_neighbors,
            min_dist=0.1,
        )
        return reducer.fit_transform(data)

    raise ValueError(f"Unknown reduction method: {method!r}")


def mood_coordinates(tracks: Sequence[dict], method: str = "direct") -> np.ndarray:
    """Return (n_tracks, 2) mood coordinates in [-1, 1] for the given method.

    ``direct`` uses valence/energy straight; ``pca``/``tsne``/``umap`` reduce
    the full feature matrix and orient the result onto the mood axes.
    """
    method = method.lower()
    if method not in VALID_METHODS:
        raise ValueError(f"method must be one of {VALID_METHODS}, got {method!r}")

    if not tracks:
        return np.zeros((0, 2))

    if method == "direct" or len(tracks) < 4:
        # Too few points to learn a meaningful embedding; fall back to direct.
        return _normalize_fill(direct_coords(tracks))

    embedding = _reduce(feature_matrix(tracks), method)
    oriented = _orient_to_mood(embedding, tracks)
    return _normalize_fill(oriented)


def attach_coordinates(
    tracks: Sequence[dict], method: str = "direct"
) -> List[dict]:
    """Return copies of ``tracks`` with ``x``/``y`` mood coordinates added."""
    coords = mood_coordinates(tracks, method)
    out = []
    for track, (x, y) in zip(tracks, coords):
        enriched = dict(track)
        enriched["x"] = round(float(x), 4)
        enriched["y"] = round(float(y), 4)
        out.append(enriched)
    return out


def select_region(
    tracks: Iterable[dict],
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
) -> List[dict]:
    """Return tracks whose mood coordinates fall inside the given box."""
    lo_x, hi_x = sorted((x_min, x_max))
    lo_y, hi_y = sorted((y_min, y_max))
    selected = []
    for t in tracks:
        x, y = t.get("x"), t.get("y")
        if x is None or y is None:
            continue
        if lo_x <= x <= hi_x and lo_y <= y <= hi_y:
            selected.append(t)
    return selected
