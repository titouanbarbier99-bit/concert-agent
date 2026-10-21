"""Concert Agent : serveur Flask, API et interface.

L'agent (LLM + tools + SQLite) vit dans le dossier agent/.
"""

import os
import secrets
import time
import uuid
from datetime import date
from urllib.parse import quote

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session

load_dotenv()

import db  # noqa: E402
from agent import spotify, villes  # noqa: E402
from agent.llm import etat_llm  # noqa: E402
from agent.loop import run_agent  # noqa: E402
from agent.tools import TOOL_MAP  # noqa: E402

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "concert-agent-dev-secret")
app.json.ensure_ascii = False

db.init_db()


@app.before_request
def ensure_session():
    if not app.config.get("TESTING") and request.host.startswith("localhost:"):
        port = request.host.split(":", 1)[1]
        target = "http://127.0.0.1:" + port + request.path
        if request.query_string:
            target += "?" + request.query_string.decode("utf-8")
        return redirect(target)

    if "sid" not in session:
        session["sid"] = uuid.uuid4().hex


def sid():
    return session["sid"]


def wants_json():
    return request.path.startswith("/api/")


@app.get("/")
def index():
    return render_template("index.html")


# ------------------------------------------------------------------- spotify

@app.get("/login")
def spotify_login():
    try:
        state = secrets.token_urlsafe(24)
        session["spotify_state"] = state
        return redirect(spotify.authorize_url(state))
    except spotify.SpotifyError as exc:
        app.logger.warning("Spotify login indisponible : %s", exc)
        return redirect("/?spotify=config")


@app.get("/callback")
def spotify_callback():
    error = request.args.get("error")
    if error:
        return redirect("/?spotify=error&reason=" + quote(error))

    expected = session.pop("spotify_state", None)
    state = request.args.get("state") or ""
    if not expected or not secrets.compare_digest(state, expected):
        return redirect("/?spotify=state")

    code = request.args.get("code")
    if not code:
        return redirect("/?spotify=error&reason=" + quote("Code Spotify manquant."))

    try:
        token = spotify.exchange_code(code)
        profile = spotify.get_profile(token["access_token"])
        expires_at = int(time.time()) + int(token.get("expires_in") or 3600)
        db.save_spotify_session(
            sid(),
            token["access_token"],
            token.get("refresh_token") or "",
            expires_at,
            profile,
        )
    except spotify.SpotifyError as exc:
        app.logger.warning("Spotify callback : %s", exc)
        return redirect("/?spotify=error&reason=" + quote(str(exc)[:160]))

    imported = 0
    try:
        imported = len(spotify.import_artists(sid(), limit=30)["added"])
    except spotify.SpotifyError as exc:
        app.logger.warning("Import Spotify impossible : %s", exc)

    return redirect(f"/?spotify=connected&imported={imported}")


@app.get("/logout")
def spotify_logout():
    db.clear_spotify_session(sid())
    session.pop("spotify_state", None)
    return redirect("/?spotify=logout")


@app.get("/api/spotify/status")
def api_spotify_status():
    return jsonify(spotify.status(sid()))


@app.get("/api/me")
def api_me():
    status = spotify.status(sid())
    if not status["connected"]:
        return jsonify({"authenticated": False})
    profile = status.get("profile") or {}
    return jsonify({"authenticated": True, **profile})


@app.post("/api/spotify/import")
def api_spotify_import():
    data = request.get_json(silent=True) or {}
    try:
        limit = int(data.get("limit") or 30)
    except (TypeError, ValueError):
        limit = 30
    try:
        result = spotify.import_artists(sid(), limit=limit)
        return jsonify(result)
    except spotify.SpotifyAuthError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 401
    except spotify.SpotifyError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@app.get("/api/spotify/top-artists")
def api_spotify_top_artists():
    try:
        token = spotify.get_valid_token(sid())
        if not token:
            return jsonify({"ok": False, "error": "Connecte-toi avec Spotify."}), 401
        return jsonify({"ok": True, "artistes": spotify.get_top_artists(token, 20)})
    except spotify.SpotifyAuthError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 401
    except spotify.SpotifyError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


# --------------------------------------------------------------------- agent

@app.post("/api/chat")
def api_chat():
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    confirm = data.get("confirm")

    if not message and confirm not in ("oui", "non"):
        return jsonify({"error": "Message vide."}), 400

    try:
        result = run_agent(sid(), message, confirm)
        return jsonify(result)
    except Exception as exc:  # noqa: BLE001 - message clair pour l'utilisateur
        app.logger.exception("Erreur agent")
        return jsonify({
            "reply": "❌ Une erreur interne est survenue. Regarde le terminal pour le détail.",
            "traces": [],
            "confirmation": None,
            "mode": "erreur",
            "error": str(exc),
        }), 500


@app.get("/api/historique")
def api_historique():
    return jsonify({
        "interactions": db.get_interactions(sid(), 50),
        "traces": db.get_traces(sid(), 50),
    })


# --------------------------------------------------------------- preferences

@app.get("/api/preferences")
def api_preferences_get():
    prefs = db.get_preferences()
    return jsonify({
        "preferences": prefs,
        "artistes": db.list_artistes(),
        "favoris": db.list_favoris(),
    })


@app.post("/api/preferences")
def api_preferences_post():
    data = request.get_json(silent=True) or {}
    ville = (data.get("ville") or "").strip()
    region = (data.get("region") or "").strip()
    code = villes.region_code(region) if region else None
    if ville and not code:
        code = villes.CITY_TO_REGION.get(villes.norm(ville))

    budget = data.get("budget_max")
    try:
        budget = float(budget) if budget not in (None, "") else None
    except (TypeError, ValueError):
        budget = None

    prefs = db.update_preferences(
        ville=ville,
        region=villes.region_name(code) if code else region,
        region_code=code or "",
        budget_max=budget,
    )
    return jsonify({"ok": True, "preferences": prefs})


# ------------------------------------------------------------------- artistes

@app.get("/api/artistes")
def api_artistes_get():
    return jsonify({"artistes": db.list_artistes()})


@app.post("/api/artistes")
def api_artistes_post():
    data = request.get_json(silent=True) or {}
    nom = (data.get("artiste") or "").strip()
    if not nom:
        return jsonify({"error": "Nom d'artiste manquant."}), 400
    db.add_artiste(nom)
    return jsonify({"ok": True, "artistes": db.list_artistes()})


@app.delete("/api/artistes/<path:nom>")
def api_artistes_delete(nom):
    db.remove_artiste(nom)
    return jsonify({"ok": True, "artistes": db.list_artistes()})


# -------------------------------------------------------------------- favoris

@app.get("/api/favoris")
def api_favoris_get():
    return jsonify({"favoris": db.list_favoris()})


@app.delete("/api/favoris/<int:favori_id>")
def api_favoris_delete(favori_id):
    db.delete_favori(favori_id)
    return jsonify({"ok": True, "favoris": db.list_favoris()})


# ----------------------------------------------------------------------- etat

@app.get("/api/etat")
def api_etat():
    pending = db.get_pending(sid())
    if pending:
        tool = TOOL_MAP.get(pending.get("tool"))
        if tool:
            pending["message"] = tool.confirmation(pending.get("arguments") or {}, sid())
    return jsonify({
        "llm": etat_llm(),
        "ticketmaster": bool(os.getenv("TICKETMASTER_API_KEY", "").strip()),
        "demo_force": os.getenv("MODE_DEMO", "0").lower() in ("1", "true", "oui", "yes"),
        "demo_fallback": os.getenv("DEMO_FALLBACK", "1").lower() not in ("0", "false", "non", "no"),
        "date": date.today().isoformat(),
        "pending": pending,
        "spotify": spotify.status(sid()),
    })


@app.errorhandler(404)
def not_found(_error):
    if wants_json():
        return jsonify({"error": "Route inconnue."}), 404
    return render_template("index.html"), 404


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    host = os.getenv("HOST", "127.0.0.1")
    print("=" * 60)
    print(" Concert Agent")
    print(" http://127.0.0.1:" + str(port))
    info = etat_llm()
    print(" LLM : " + info["message"])
    print(" Spotify : " + ("configure" if spotify.configure() else "non configure"))
    print("=" * 60)
    app.run(host=host, port=port, debug=False)
