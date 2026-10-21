"""Client Spotify : OAuth, jetons et récupération des artistes.

Le jeton est stocké côté serveur dans SQLite (table spotify_sessions),
jamais dans le cookie de session Flask.
"""

import os
import time
from urllib.parse import urlencode

import requests

import db
from . import villes

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API_URL = "https://api.spotify.com/v1"
SCOPES = "user-read-private user-top-read user-read-recently-played"


class SpotifyError(Exception):
    pass


class SpotifyAuthError(SpotifyError):
    pass


def config():
    return {
        "client_id": (os.getenv("SPOTIFY_CLIENT_ID") or "").strip(),
        "client_secret": (os.getenv("SPOTIFY_CLIENT_SECRET") or "").strip(),
        "redirect_uri": (os.getenv("REDIRECT_URI") or "").strip(),
    }


def configure():
    cfg = config()
    return bool(cfg["client_id"] and cfg["client_secret"] and cfg["redirect_uri"])


def authorize_url(state):
    cfg = config()
    if not configure():
        raise SpotifyError(
            "Spotify n'est pas configuré : renseigne SPOTIFY_CLIENT_ID, "
            "SPOTIFY_CLIENT_SECRET et REDIRECT_URI dans .env."
        )
    params = {
        "response_type": "code",
        "client_id": cfg["client_id"],
        "scope": SCOPES,
        "redirect_uri": cfg["redirect_uri"],
        "state": state,
        "show_dialog": "true",
    }
    return AUTH_URL + "?" + urlencode(params)


def _token_request(data):
    cfg = config()
    if not configure():
        raise SpotifyError(
            "Spotify n'est pas configuré : renseigne SPOTIFY_CLIENT_ID, "
            "SPOTIFY_CLIENT_SECRET et REDIRECT_URI dans .env."
        )
    data = dict(data)
    data["client_id"] = cfg["client_id"]
    data["client_secret"] = cfg["client_secret"]
    try:
        response = requests.post(TOKEN_URL, data=data, timeout=20)
    except requests.RequestException as exc:
        raise SpotifyError("Spotify injoignable : " + str(exc)) from exc

    if response.status_code >= 400:
        detail = response.text[:300].replace("\n", " ")
        raise SpotifyAuthError(f"Spotify a refusé la connexion (HTTP {response.status_code}) : {detail}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise SpotifyError("Réponse Spotify illisible.") from exc

    if not payload.get("access_token"):
        raise SpotifyAuthError("Spotify n'a pas renvoyé de jeton d'accès.")
    return payload


def exchange_code(code):
    cfg = config()
    return _token_request({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": cfg["redirect_uri"],
    })


def refresh_access_token(refresh_token):
    if not refresh_token:
        raise SpotifyAuthError("Aucun refresh token Spotify.")
    return _token_request({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    })


def api_get(path, access_token, params=None, timeout=20):
    if not access_token:
        raise SpotifyAuthError("Connecte-toi avec Spotify pour continuer.")
    try:
        response = requests.get(
            API_URL + path,
            headers={"Authorization": "Bearer " + access_token},
            params=params or {},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise SpotifyError("Spotify injoignable : " + str(exc)) from exc

    if response.status_code == 401:
        raise SpotifyAuthError("La session Spotify a expiré. Reconnecte-toi.")
    if response.status_code == 403:
        raise SpotifyAuthError(
            "Spotify refuse l'accès à ces données. Vérifie que ton compte est autorisé "
            "dans le dashboard Spotify (mode développement : 5 comptes maximum)."
        )
    if response.status_code == 429:
        raise SpotifyError("Quota Spotify dépassé, réessaie dans quelques secondes.")
    if response.status_code >= 400:
        raise SpotifyError(f"Spotify a renvoyé HTTP {response.status_code}.")

    try:
        return response.json()
    except ValueError as exc:
        raise SpotifyError("Réponse Spotify illisible.") from exc


def get_profile(access_token):
    data = api_get("/me", access_token, timeout=12)
    images = data.get("images") or []
    return {
        "id": data.get("id") or "",
        "display_name": data.get("display_name") or data.get("id") or "Compte Spotify",
        "email": data.get("email") or "",
        "image": (images[0] or {}).get("url", "") if images else "",
        "country": data.get("country") or "",
        "followers": ((data.get("followers") or {}).get("total") or 0),
    }


def get_top_artists(access_token, limit=20):
    limit = max(1, min(int(limit or 20), 50))
    data = api_get(
        "/me/top/artists",
        access_token,
        params={"limit": limit, "time_range": "medium_term"},
        timeout=15,
    )
    artists = []
    for item in data.get("items") or []:
        name = (item.get("name") or "").strip()
        if not name:
            continue
        images = item.get("images") or []
        artists.append({
            "name": name,
            "popularity": item.get("popularity"),
            "genres": (item.get("genres") or [])[:3],
            "image": (images[0] or {}).get("url", "") if images else "",
        })
    return artists


def get_recent_artists(access_token, limit=50):
    data = api_get(
        "/me/player/recently-played",
        access_token,
        params={"limit": max(1, min(int(limit or 50), 50))},
        timeout=15,
    )
    names = []
    for item in data.get("items") or []:
        track = item.get("track") or {}
        for artist in track.get("artists") or []:
            name = (artist.get("name") or "").strip()
            if name:
                names.append(name)
    return names


def get_artist_names(access_token, limit=30):
    """Top artistes + écoutes récentes, dédupliqués, dans l'ordre."""
    limit = max(1, min(int(limit or 30), 60))
    names = []
    try:
        top = get_top_artists(access_token, limit=min(limit, 20))
        names.extend(a["name"] for a in top)
    except SpotifyAuthError:
        raise
    except SpotifyError:
        pass

    try:
        recent = get_recent_artists(access_token)
        names.extend(recent)
    except SpotifyAuthError:
        raise
    except SpotifyError:
        pass

    out = []
    seen = set()
    for name in names:
        key = villes.norm(name)
        if not key or key in seen or key == "various artists":
            continue
        seen.add(key)
        out.append(name)
        if len(out) >= limit:
            break
    return out


def get_valid_token(session_id):
    record = db.get_spotify_session(session_id)
    if not record:
        return None

    if int(record.get("expires_at") or 0) > int(time.time()) + 60:
        return record["access_token"]

    refresh_token = record.get("refresh_token") or ""
    if not refresh_token:
        db.clear_spotify_session(session_id)
        return None

    try:
        payload = refresh_access_token(refresh_token)
    except SpotifyError:
        db.clear_spotify_session(session_id)
        raise

    expires_at = int(time.time()) + int(payload.get("expires_in") or 3600)
    db.save_spotify_session(
        session_id,
        payload["access_token"],
        payload.get("refresh_token") or refresh_token,
        expires_at,
        profile=record.get("profile") or {},
    )
    return payload["access_token"]


def import_artists(session_id, limit=30):
    token = get_valid_token(session_id)
    names = get_artist_names(token, limit=limit)
    added = [name for name in names if db.add_artiste(name)]
    if added:
        message = f"{len(added)} nouvel(aux) artiste(s) importé(s) depuis Spotify."
    else:
        message = "Aucun nouvel artiste : tes tops Spotify sont déjà dans ta liste."
    return {
        "ok": True,
        "total": len(names),
        "added": added,
        "artistes": db.list_artistes(),
        "message": message,
    }


def status(session_id):
    record = db.get_spotify_session(session_id)
    profile = (record or {}).get("profile") or {}
    return {
        "configured": configure(),
        "connected": bool(record and record.get("access_token")),
        "profile": profile if record else None,
    }
