"""Minimal Spotify Web API client for the Mood Map.

Implements just what we need:
  * the Authorization Code OAuth flow (login URL, code -> token exchange),
  * paged fetching of the user's saved tracks,
  * batched audio-features lookup,
  * creating a playlist from a set of track URIs.

Configuration comes from the environment:
  SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_REDIRECT_URI

If those aren't set, :func:`is_configured` returns False and the app runs in
demo mode instead.

A note on audio features: Spotify deprecated the `/audio-features` endpoint for
apps created after 2024-11-27. So by default the Mood Map sources features from
ReccoBeats instead (see ``reccobeats.py`` and ``_features_for`` below); set
MOODMAP_FEATURE_SOURCE=spotify to use Spotify's own endpoint if your app is
grandfathered in. Either way, a failure raises :class:`FeaturesUnavailable`,
which the web app surfaces cleanly.
"""

from __future__ import annotations

import base64
import os
import time
import urllib.parse
from typing import Dict, List, Optional, Sequence

import requests

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API_BASE = "https://api.spotify.com/v1"

# Scopes: read the library, create/modify playlists.
SCOPES = "user-library-read playlist-modify-public playlist-modify-private"

# The audio-features fields we care about (mirrors mood.FEATURE_COLUMNS plus a
# couple of extras kept for display).
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


class SpotifyError(RuntimeError):
    """A Spotify API request failed."""


class FeaturesUnavailable(SpotifyError):
    """The /audio-features endpoint is not accessible for this app."""


def client_id() -> Optional[str]:
    return os.environ.get("SPOTIFY_CLIENT_ID")


def client_secret() -> Optional[str]:
    return os.environ.get("SPOTIFY_CLIENT_SECRET")


def redirect_uri() -> str:
    return os.environ.get(
        "SPOTIFY_REDIRECT_URI", "http://127.0.0.1:5002/callback"
    )


def is_configured() -> bool:
    """True when client credentials are present (i.e. live mode is possible)."""
    return bool(client_id() and client_secret())


def login_url(state: str) -> str:
    params = {
        "client_id": client_id(),
        "response_type": "code",
        "redirect_uri": redirect_uri(),
        "scope": SCOPES,
        "state": state,
        "show_dialog": "false",
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


def _basic_auth_header() -> Dict[str, str]:
    raw = f"{client_id()}:{client_secret()}".encode()
    return {"Authorization": "Basic " + base64.b64encode(raw).decode()}


def exchange_code(code: str) -> dict:
    """Exchange an auth code for an access/refresh token bundle."""
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri(),
        },
        headers=_basic_auth_header(),
        timeout=15,
    )
    if resp.status_code != 200:
        raise SpotifyError(f"Token exchange failed: {resp.status_code} {resp.text}")
    token = resp.json()
    token["expires_at"] = time.time() + token.get("expires_in", 3600)
    return token


def refresh_token(token: dict) -> dict:
    """Refresh an expired access token in place (returns the updated dict)."""
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": token["refresh_token"],
        },
        headers=_basic_auth_header(),
        timeout=15,
    )
    if resp.status_code != 200:
        raise SpotifyError(f"Token refresh failed: {resp.status_code} {resp.text}")
    fresh = resp.json()
    token["access_token"] = fresh["access_token"]
    token["expires_at"] = time.time() + fresh.get("expires_in", 3600)
    if "refresh_token" in fresh:
        token["refresh_token"] = fresh["refresh_token"]
    return token


def valid_access_token(token: dict) -> str:
    """Return a non-expired access token, refreshing if needed."""
    if token.get("expires_at", 0) <= time.time() + 30:
        refresh_token(token)
    return token["access_token"]


def _auth_headers(token: dict) -> Dict[str, str]:
    return {"Authorization": f"Bearer {valid_access_token(token)}"}


def _get(token: dict, url: str, params: Optional[dict] = None) -> requests.Response:
    return requests.get(url, headers=_auth_headers(token), params=params, timeout=20)


def get_current_user(token: dict) -> dict:
    resp = _get(token, f"{API_BASE}/me")
    if resp.status_code != 200:
        raise SpotifyError(f"Could not read profile: {resp.status_code} {resp.text}")
    return resp.json()


def get_saved_tracks(token: dict, limit: int = 500) -> List[dict]:
    """Fetch the user's saved (liked) tracks, up to ``limit`` items."""
    tracks: List[dict] = []
    url = f"{API_BASE}/me/tracks"
    params = {"limit": 50, "offset": 0}
    while url and len(tracks) < limit:
        resp = _get(token, url, params=params)
        if resp.status_code != 200:
            raise SpotifyError(
                f"Could not read library: {resp.status_code} {resp.text}"
            )
        data = resp.json()
        for item in data.get("items", []):
            track = item.get("track") or {}
            if not track.get("id"):
                continue
            tracks.append(
                {
                    "id": track["id"],
                    "uri": track.get("uri"),
                    "name": track.get("name", "Unknown"),
                    "artist": ", ".join(
                        a.get("name", "") for a in track.get("artists", [])
                    ),
                    "album": (track.get("album") or {}).get("name", ""),
                    "popularity": track.get("popularity", 0),
                    "year": _year_from_album(track.get("album") or {}),
                }
            )
        url = data.get("next")
        params = None  # `next` already encodes pagination
    return tracks[:limit]


def _year_from_album(album: dict) -> Optional[int]:
    date = album.get("release_date", "")
    if date[:4].isdigit():
        return int(date[:4])
    return None


def get_audio_features(token: dict, track_ids: Sequence[str]) -> Dict[str, dict]:
    """Return ``{track_id: features}`` for the given ids (batched by 100)."""
    out: Dict[str, dict] = {}
    for start in range(0, len(track_ids), 100):
        batch = [tid for tid in track_ids[start : start + 100] if tid]
        if not batch:
            continue
        resp = _get(
            token,
            f"{API_BASE}/audio-features",
            params={"ids": ",".join(batch)},
        )
        if resp.status_code in (401, 403):
            raise FeaturesUnavailable(
                "Spotify denied access to /audio-features. This endpoint is "
                "deprecated for apps created after 2024-11-27. Try demo mode."
            )
        if resp.status_code != 200:
            raise SpotifyError(
                f"Audio features failed: {resp.status_code} {resp.text}"
            )
        for feat in resp.json().get("audio_features", []) or []:
            if feat and feat.get("id"):
                out[feat["id"]] = {k: feat.get(k) for k in _FEATURE_KEYS}
    return out


def _features_for(token: dict, track_ids: List[str]) -> Dict[str, dict]:
    """Fetch audio features from the configured source.

    MOODMAP_FEATURE_SOURCE selects the provider:
      * "reccobeats" (default) — free replacement for Spotify's dead endpoint,
      * "spotify"              — Spotify's own /audio-features (only works for
                                 apps grandfathered in before 2024-11-27).
    """
    source = os.environ.get("MOODMAP_FEATURE_SOURCE", "reccobeats").lower()
    if source == "spotify":
        return get_audio_features(token, track_ids)

    import reccobeats

    try:
        return reccobeats.get_audio_features(track_ids)
    except reccobeats.ReccoBeatsError as exc:
        # Surface it through the same error the app already handles.
        raise FeaturesUnavailable(str(exc)) from exc


def build_library(token: dict, limit: int = 500) -> List[dict]:
    """Fetch saved tracks and merge in their audio features."""
    tracks = get_saved_tracks(token, limit=limit)
    features = _features_for(token, [t["id"] for t in tracks])
    merged = []
    for t in tracks:
        feat = features.get(t["id"])
        if not feat:
            continue  # no features -> can't place it on the map
        merged.append({**t, **feat})
    return merged


def create_playlist(
    token: dict, name: str, track_uris: Sequence[str], public: bool = False
) -> dict:
    """Create a playlist for the current user and add the given track URIs."""
    user = get_current_user(token)
    resp = requests.post(
        f"{API_BASE}/users/{user['id']}/playlists",
        headers={**_auth_headers(token), "Content-Type": "application/json"},
        json={
            "name": name,
            "public": public,
            "description": "Generated from a Mood Map region.",
        },
        timeout=20,
    )
    if resp.status_code not in (200, 201):
        raise SpotifyError(f"Could not create playlist: {resp.status_code} {resp.text}")
    playlist = resp.json()

    uris = [u for u in track_uris if u]
    for start in range(0, len(uris), 100):
        batch = uris[start : start + 100]
        add = requests.post(
            f"{API_BASE}/playlists/{playlist['id']}/tracks",
            headers={**_auth_headers(token), "Content-Type": "application/json"},
            json={"uris": batch},
            timeout=20,
        )
        if add.status_code not in (200, 201):
            raise SpotifyError(
                f"Could not add tracks: {add.status_code} {add.text}"
            )
    return {
        "id": playlist["id"],
        "name": playlist["name"],
        "url": playlist.get("external_urls", {}).get("spotify", ""),
        "track_count": len(uris),
    }
