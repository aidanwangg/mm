# 🎛️ Mood Map

Plot your **entire Spotify library** on a 2-D *feelings* plane, then pan, zoom,
explore mood regions, and turn any area into a playlist.

```
   Energetic ↑
             │   ↖ sad+energetic        ↗ happy+energetic
   Sad ──────┼────────── Happy   (x = valence)
             │   ↙ sad+calm             ↘ happy+calm
      Calm ↓                          (y = energy)
```

- **X-axis** — *valence*: Sad ↔ Happy
- **Y-axis** — *energy*: Calm ↔ Energetic

## What it does

1. **Collects audio features** for every song in your library from the Spotify
   Web API (valence, energy, danceability, acousticness, tempo, …).
2. **Maps them to 2-D** with one of four projections you can switch live:
   - **Direct** — valence × energy straight up; the most interpretable map.
   - **PCA / t-SNE / UMAP** — reduce *all* the audio features to two
     dimensions, then rotate/scale the embedding so the axes still read as
     Sad↔Happy / Calm↔Energetic.
3. **Lets you explore** — pan, zoom, hover any dot for the track, and
   **Shift-drag** a rectangle to grab a mood region.
4. **Generates a playlist** from the selected region — saved straight to your
   Spotify account in live mode.

## Quick start (demo mode — no setup)

```bash
pip install -r requirements.txt
python app.py            # http://127.0.0.1:5002
```

With no credentials the app boots a **synthetic library** of ~420 tracks spread
across the mood plane, so you can play with every feature immediately.

## Live mode (your real library)

Create a Spotify app at <https://developer.spotify.com/dashboard>, add a
redirect URI, and export:

```bash
export SPOTIFY_CLIENT_ID=...
export SPOTIFY_CLIENT_SECRET=...
export SPOTIFY_REDIRECT_URI=http://127.0.0.1:5002/callback
python app.py
```

Click **Connect Spotify**, approve access, and your liked songs appear on the
map. Selecting a region and hitting **Generate playlist** writes a real
playlist to your account.

> **Heads-up on audio features.** Spotify deprecated the `/audio-features`
> endpoint for apps created after **2024-11-27**. Older apps still work; newer
> ones get a 403, which the app reports cleanly and suggests demo mode. This is
> a Spotify platform change, not a bug here.

## How the mapping works

`mood.py` is the pure-NumPy/scikit-learn core (no Flask/Spotify), so it's easy
to test:

- `feature_matrix()` assembles and normalises the feature columns (loudness and
  tempo are rescaled onto ~0–1).
- `direct_coords()` maps valence/energy onto a centred [-1, 1] plane.
- For PCA/t-SNE/UMAP, the embedding is **oriented to the mood axes** by fitting
  the best 2×2 linear map (rotation + scale + reflection) from the embedding to
  the direct mood coordinates via least squares. You keep the reduction's
  neighbourhoods while the plot stays interpretable.
- Everything is normalised to fill [-1, 1] (99th-percentile clip) for display.

## Project layout

```
moodmap/
  app.py               # Flask backend: OAuth, library fetch, mapping, playlists
  spotify.py           # Spotify Web API client (OAuth, library, features, playlist)
  mood.py              # mapping core: direct + PCA/t-SNE/UMAP, axis orientation
  demo_data.py         # synthetic library for no-credentials demo mode
  requirements.txt
  templates/index.html # the page
  static/
    app.js             # interactive canvas scatter (pan/zoom/hover/lasso)
    style.css
  tests/test_mood.py   # unit tests for the mapping core
```

## Run the tests

```bash
python -m unittest discover -s tests -v
```

The tests cover feature normalisation, the four quadrants of the direct map,
coordinate ranges for every method, and — importantly — that reduced
embeddings stay correlated with valence/energy after orientation.

## Notes & limitations

- UMAP is optional (`umap-learn`); without it the UMAP button reports it's
  missing while the other three projections keep working.
- t-SNE/UMAP recompute the layout on each request; for very large libraries
  you'd cache embeddings, but at a few hundred–thousand tracks it's snappy.
- Live mode pulls up to `MOODMAP_LIBRARY_LIMIT` (default 500) liked songs.
