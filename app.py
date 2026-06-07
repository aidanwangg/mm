"""Mood Map — plot your whole Spotify library on a Sad↔Happy / Calm↔Energetic map.

Run:
    pip install -r requirements.txt
    python app.py                      # serves http://127.0.0.1:5002

Live mode (your real library) needs a Spotify app's credentials in the
environment; without them the app starts in **demo mode** with a synthetic
library so you can explore the UI immediately:

    export SPOTIFY_CLIENT_ID=...
    export SPOTIFY_CLIENT_SECRET=...
    export SPOTIFY_REDIRECT_URI=http://127.0.0.1:5002/callback

The browser then drives everything: pick a projection (Direct / PCA / t-SNE /
UMAP), pan & zoom the map, lasso a mood region, and turn it into a playlist.
"""

from __future__ import annotations

import os
import secrets
import uuid
from typing import Dict, List

from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

import mood
import spotify
from demo_data import generate_library

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", secrets.token_hex(16))

# How many liked songs to pull in live mode (Spotify paginates 50 at a time).
LIBRARY_LIMIT = int(os.environ.get("MOODMAP_LIBRARY_LIMIT", "500"))

# Server-side caches keyed by a per-session id. Libraries can be large and the
# audio-feature fetch is slow, so we keep the assembled dataset in memory
# rather than round-tripping it through the signed cookie.
_LIBRARIES: Dict[str, List[dict]] = {}
_TOKENS: Dict[str, dict] = {}

# A single demo library, generated once and shared across demo sessions.
_DEMO_LIBRARY = generate_library()


def _session_id() -> str:
    sid = session.get("sid")
    if not sid:
        sid = uuid.uuid4().hex
        session["sid"] = sid
    return sid


def _is_live() -> bool:
    """Live mode = configured app *and* an authenticated token for this user."""
    return spotify.is_configured() and _session_id() in _TOKENS


def _library() -> List[dict]:
    """Return the active library: the user's (live) or the shared demo set."""
    sid = _session_id()
    if sid in _LIBRARIES:
        return _LIBRARIES[sid]
    if _is_live():
        token = _TOKENS[sid]
        library = spotify.build_library(token, limit=LIBRARY_LIMIT)
        _LIBRARIES[sid] = library
        return library
    return _DEMO_LIBRARY


@app.get("/")
def index():
    return render_template(
        "index.html",
        configured=spotify.is_configured(),
    )


@app.get("/login")
def login():
    if not spotify.is_configured():
        return redirect(url_for("index"))
    state = secrets.token_urlsafe(16)
    session["oauth_state"] = state
    return redirect(spotify.login_url(state))


@app.get("/callback")
def callback():
    error = request.args.get("error")
    if error:
        return render_template("index.html", configured=True, auth_error=error)

    code = request.args.get("code")
    state = request.args.get("state")
    if not code or state != session.get("oauth_state"):
        return render_template(
            "index.html", configured=True, auth_error="Invalid OAuth state."
        )

    try:
        token = spotify.exchange_code(code)
    except spotify.SpotifyError as exc:
        return render_template("index.html", configured=True, auth_error=str(exc))

    sid = _session_id()
    _TOKENS[sid] = token
    _LIBRARIES.pop(sid, None)  # force a fresh fetch
    return redirect(url_for("index"))


@app.get("/logout")
def logout():
    sid = _session_id()
    _TOKENS.pop(sid, None)
    _LIBRARIES.pop(sid, None)
    return redirect(url_for("index"))


@app.get("/api/status")
def status():
    return jsonify(
        configured=spotify.is_configured(),
        live=_is_live(),
        mode="live" if _is_live() else "demo",
        login_url=url_for("login"),
        methods=list(mood.VALID_METHODS),
    )


@app.get("/api/tracks")
def tracks():
    method = request.args.get("method", "direct").lower()
    if method not in mood.VALID_METHODS:
        return jsonify(error=f"Unknown method '{method}'."), 400

    try:
        library = _library()
    except spotify.FeaturesUnavailable as exc:
        return jsonify(error=str(exc), features_unavailable=True), 503
    except spotify.SpotifyError as exc:
        return jsonify(error=str(exc)), 502

    if not library:
        return jsonify(
            error="No tracks with audio features were found in your library."
        ), 404

    try:
        enriched = mood.attach_coordinates(library, method)
    except RuntimeError as exc:  # e.g. UMAP not installed
        return jsonify(error=str(exc)), 503

    return jsonify(
        method=method,
        mode="live" if _is_live() else "demo",
        count=len(enriched),
        tracks=enriched,
    )


@app.post("/api/playlist")
def playlist():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "Mood Map Mix").strip()[:100]
    ids = data.get("ids") or []
    if not ids:
        return jsonify(error="No tracks selected."), 400

    library = {t["id"]: t for t in _library()}
    chosen = [library[i] for i in ids if i in library]
    if not chosen:
        return jsonify(error="Selected tracks are no longer available."), 404

    if _is_live():
        uris = [t.get("uri") for t in chosen if t.get("uri")]
        try:
            result = spotify.create_playlist(_TOKENS[_session_id()], name, uris)
        except spotify.SpotifyError as exc:
            return jsonify(error=str(exc)), 502
        return jsonify(created=True, **result)

    # Demo mode: there's no real account to write to, so return the tracklist
    # for the UI to display/export.
    return jsonify(
        created=False,
        name=name,
        track_count=len(chosen),
        tracks=[
            {"name": t["name"], "artist": t.get("artist", "")} for t in chosen
        ],
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run the Mood Map web app.")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 5002)))
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    print(f" * Mood Map on http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=True)
