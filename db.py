"""Acces SQLite pour Concert Agent.

Toutes les lectures/ecritures de l'agent passent par ce module.
La base est creee et initialisee au demarrage de l'application.
"""

import calendar
import json
import os
import sqlite3
from datetime import date, datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("CONCERT_DB_PATH") or os.path.join(BASE_DIR, "data", "concerts.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS preferences (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    ville TEXT NOT NULL DEFAULT '',
    region TEXT NOT NULL DEFAULT '',
    region_code TEXT NOT NULL DEFAULT '',
    budget_max REAL,
    modifie_le TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artistes_suivis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nom TEXT NOT NULL UNIQUE,
    ajoute_le TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS favoris (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    concert_id TEXT NOT NULL UNIQUE,
    artiste TEXT NOT NULL,
    date TEXT NOT NULL,
    heure TEXT DEFAULT '',
    salle TEXT DEFAULT '',
    ville TEXT DEFAULT '',
    region TEXT DEFAULT '',
    pays TEXT DEFAULT '',
    prix_min REAL,
    prix_max REAL,
    devise TEXT DEFAULT 'EUR',
    url TEXT DEFAULT '',
    source TEXT DEFAULT '',
    ajoute_le TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    contenu TEXT NOT NULL,
    cree_le TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tool_traces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    tool TEXT NOT NULL,
    arguments TEXT NOT NULL,
    resultat TEXT NOT NULL,
    statut TEXT NOT NULL,
    duree_ms INTEGER NOT NULL,
    cree_le TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_actions (
    session_id TEXT PRIMARY KEY,
    tool TEXT NOT NULL,
    arguments TEXT NOT NULL,
    cree_le TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS spotify_sessions (
    session_id TEXT PRIMARY KEY,
    access_token TEXT NOT NULL,
    refresh_token TEXT DEFAULT '',
    expires_at INTEGER NOT NULL,
    profile TEXT DEFAULT '{}',
    connecte_le TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS resultats_cache (
    session_id TEXT NOT NULL,
    concert_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    cree_le TEXT NOT NULL,
    PRIMARY KEY (session_id, concert_id)
);

CREATE TABLE IF NOT EXISTS concerts_demo (
    id TEXT PRIMARY KEY,
    artiste TEXT NOT NULL,
    date TEXT NOT NULL,
    heure TEXT DEFAULT '',
    salle TEXT DEFAULT '',
    ville TEXT DEFAULT '',
    region TEXT DEFAULT '',
    region_code TEXT DEFAULT '',
    pays TEXT DEFAULT 'France',
    prix_min REAL,
    prix_max REAL,
    devise TEXT DEFAULT 'EUR',
    url TEXT DEFAULT ''
);
"""

ARTISTES_DEMO = [
    "Gims",
    "Ninho",
    "Orelsan",
    "SCH",
    "Damso",
    "Gazo",
    "Jul",
    "Aya Nakamura",
    "Sofiane Pamart",
]


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def _connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def _exec(sql, params=()):
    conn = _connect()
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _rows(sql, params=()):
    conn = _connect()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _row(sql, params=()):
    rows = _rows(sql, params)
    return rows[0] if rows else None


def _next_month_day(day):
    today = date.today()
    year = today.year + (1 if today.month == 12 else 0)
    month = 1 if today.month == 12 else today.month + 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last)).isoformat()


def _shift(days):
    return (date.today() + timedelta(days=days)).isoformat()


def _demo_concerts():
    return [
        ("demo-gims-lyon", "Gims", _next_month_day(10), "20:00", "Halle Tony Garnier", "Lyon", "Auvergne-Rhône-Alpes", "ARA", "France", 45, 45, "EUR", ""),
        ("demo-pamart-grenoble", "Sofiane Pamart", _next_month_day(14), "20:30", "Summum", "Grenoble", "Auvergne-Rhône-Alpes", "ARA", "France", 35, 35, "EUR", ""),
        ("demo-ninho-lyon", "Ninho", _next_month_day(18), "20:00", "Halle Tony Garnier", "Lyon", "Auvergne-Rhône-Alpes", "ARA", "France", 60, 60, "EUR", ""),
        ("demo-ninho-paris", "Ninho", _shift(35), "20:00", "Accor Arena", "Paris", "Île-de-France", "IDF", "France", 65, 65, "EUR", ""),
        ("demo-aya-paris", "Aya Nakamura", _shift(40), "20:00", "Accor Arena", "Paris", "Île-de-France", "IDF", "France", 60, 60, "EUR", ""),
        ("demo-damso-lille", "Damso", _shift(45), "20:00", "Zénith de Lille", "Lille", "Hauts-de-France", "HDF", "France", 55, 55, "EUR", ""),
        ("demo-orelsan-marseille", "Orelsan", _shift(50), "20:30", "Le Dôme", "Marseille", "Provence-Alpes-Côte d'Azur", "PAC", "France", 55, 55, "EUR", ""),
        ("demo-sch-lyon", "SCH", _shift(55), "20:00", "Halle Tony Garnier", "Lyon", "Auvergne-Rhône-Alpes", "ARA", "France", 50, 50, "EUR", ""),
        ("demo-gazo-toulouse", "Gazo", _shift(60), "20:00", "Zénith de Toulouse", "Toulouse", "Occitanie", "OCC", "France", 45, 45, "EUR", ""),
        ("demo-sch-paris", "SCH", _shift(65), "20:00", "Zénith Paris", "Paris", "Île-de-France", "IDF", "France", 50, 50, "EUR", ""),
        ("demo-jul-marseille", "Jul", _shift(75), "21:00", "Orange Vélodrome", "Marseille", "Provence-Alpes-Côte d'Azur", "PAC", "France", 40, 40, "EUR", ""),
        ("demo-gims-paris", "Gims", _shift(90), "20:00", "Accor Arena", "Paris", "Île-de-France", "IDF", "France", 70, 70, "EUR", ""),
    ]


def init_db():
    conn = _connect()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()

    if not _row("SELECT id FROM preferences WHERE id = 1"):
        _exec(
            "INSERT INTO preferences (id, ville, region, region_code, budget_max, modifie_le) VALUES (1, ?, ?, ?, ?, ?)",
            ("Lyon", "Auvergne-Rhône-Alpes", "ARA", 60, now_iso()),
        )

    if not _row("SELECT id FROM artistes_suivis LIMIT 1"):
        for nom in ARTISTES_DEMO:
            _exec("INSERT OR IGNORE INTO artistes_suivis (nom, ajoute_le) VALUES (?, ?)", (nom, now_iso()))

    conn = _connect()
    try:
        conn.execute("DELETE FROM concerts_demo")
        conn.executemany(
            """INSERT INTO concerts_demo
               (id, artiste, date, heure, salle, ville, region, region_code, pays,
                prix_min, prix_max, devise, url)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            _demo_concerts(),
        )
        conn.execute("DELETE FROM resultats_cache WHERE cree_le < ?",
                     ((datetime.now() - timedelta(hours=2)).isoformat(timespec="seconds"),))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------- preferences

def get_preferences():
    return _row("SELECT * FROM preferences WHERE id = 1") or {}


_KEEP = object()


def update_preferences(ville=None, region=None, region_code=None, budget_max=_KEEP):
    prefs = get_preferences()
    _exec(
        """UPDATE preferences SET ville = ?, region = ?, region_code = ?, budget_max = ?, modifie_le = ?
           WHERE id = 1""",
        (
            ville if ville is not None else prefs.get("ville", ""),
            region if region is not None else prefs.get("region", ""),
            region_code if region_code is not None else prefs.get("region_code", ""),
            prefs.get("budget_max") if budget_max is _KEEP else budget_max,
            now_iso(),
        ),
    )
    return get_preferences()


# ------------------------------------------------------------ artistes suivis

def list_artistes():
    return [r["nom"] for r in _rows("SELECT nom FROM artistes_suivis ORDER BY nom COLLATE NOCASE")]


def add_artiste(nom):
    nom = (nom or "").strip()
    if not nom:
        return False
    conn = _connect()
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO artistes_suivis (nom, ajoute_le) VALUES (?, ?)",
            (nom, now_iso()),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def remove_artiste(nom):
    _exec("DELETE FROM artistes_suivis WHERE nom = ? COLLATE NOCASE", (nom,))
    return True


# --------------------------------------------------------------------- favoris

def list_favoris():
    return _rows("SELECT * FROM favoris ORDER BY date ASC, id ASC")


def add_favori(concert):
    conn = _connect()
    try:
        cur = conn.execute(
            """INSERT INTO favoris
               (concert_id, artiste, date, heure, salle, ville, region, pays,
                prix_min, prix_max, devise, url, source, ajoute_le)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                concert.get("id", ""),
                concert.get("artiste", ""),
                concert.get("date", ""),
                concert.get("heure", ""),
                concert.get("salle", ""),
                concert.get("ville", ""),
                concert.get("region", ""),
                concert.get("pays", ""),
                concert.get("prix_min"),
                concert.get("prix_max"),
                concert.get("devise", "EUR"),
                concert.get("url", ""),
                concert.get("source", ""),
                now_iso(),
            ),
        )
        conn.commit()
        return cur.lastrowid, True
    except sqlite3.IntegrityError:
        row = conn.execute("SELECT id FROM favoris WHERE concert_id = ?", (concert.get("id", ""),)).fetchone()
        return (row["id"] if row else None), False
    finally:
        conn.close()


def delete_favori(favori_id):
    _exec("DELETE FROM favoris WHERE id = ?", (favori_id,))
    return True


# ----------------------------------------------------------------- historique

def log_interaction(session_id, role, contenu):
    _exec(
        "INSERT INTO interactions (session_id, role, contenu, cree_le) VALUES (?, ?, ?, ?)",
        (session_id, role, (contenu or "")[:8000], now_iso()),
    )


def get_historique(session_id, limit=10):
    rows = _rows(
        """SELECT * FROM (
               SELECT * FROM interactions WHERE session_id = ? ORDER BY id DESC LIMIT ?
           ) ORDER BY id ASC""",
        (session_id, int(limit)),
    )
    return rows


def get_interactions(session_id, limit=50):
    return _rows(
        "SELECT * FROM interactions WHERE session_id = ? ORDER BY id DESC LIMIT ?",
        (session_id, int(limit)),
    )


def log_trace(session_id, tool, arguments, resultat, statut, duree_ms):
    _exec(
        """INSERT INTO tool_traces
           (session_id, tool, arguments, resultat, statut, duree_ms, cree_le)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            session_id,
            tool,
            json.dumps(arguments, ensure_ascii=False)[:8000],
            json.dumps(resultat, ensure_ascii=False)[:20000],
            statut,
            int(duree_ms),
            now_iso(),
        ),
    )


def get_traces(session_id, limit=30):
    rows = _rows(
        "SELECT * FROM tool_traces WHERE session_id = ? ORDER BY id DESC LIMIT ?",
        (session_id, int(limit)),
    )
    for r in rows:
        try:
            r["arguments"] = json.loads(r["arguments"])
        except Exception:
            pass
        try:
            r["resultat"] = json.loads(r["resultat"])
        except Exception:
            pass
    return rows


# ------------------------------------------------------------ session Spotify

def save_spotify_session(session_id, access_token, refresh_token, expires_at, profile=None):
    existing = get_spotify_session(session_id)
    if not refresh_token and existing:
        refresh_token = existing.get("refresh_token", "")
    if profile is None:
        profile = existing.get("profile", {}) if existing else {}
    _exec(
        """INSERT INTO spotify_sessions
           (session_id, access_token, refresh_token, expires_at, profile, connecte_le)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(session_id) DO UPDATE SET
             access_token = excluded.access_token,
             refresh_token = excluded.refresh_token,
             expires_at = excluded.expires_at,
             profile = excluded.profile,
             connecte_le = excluded.connecte_le""",
        (
            session_id,
            access_token,
            refresh_token or "",
            int(expires_at),
            json.dumps(profile or {}, ensure_ascii=False),
            now_iso(),
        ),
    )
    return get_spotify_session(session_id)


def get_spotify_session(session_id):
    row = _row("SELECT * FROM spotify_sessions WHERE session_id = ?", (session_id,))
    if not row:
        return None
    try:
        row["profile"] = json.loads(row.get("profile") or "{}")
    except Exception:
        row["profile"] = {}
    return row


def clear_spotify_session(session_id):
    _exec("DELETE FROM spotify_sessions WHERE session_id = ?", (session_id,))
    return True


# ------------------------------------------------------- confirmation en attente

def set_pending(session_id, tool, arguments):
    _exec(
        "INSERT OR REPLACE INTO pending_actions (session_id, tool, arguments, cree_le) VALUES (?, ?, ?, ?)",
        (session_id, tool, json.dumps(arguments, ensure_ascii=False), now_iso()),
    )


def get_pending(session_id):
    row = _row("SELECT * FROM pending_actions WHERE session_id = ?", (session_id,))
    if not row:
        return None
    try:
        row["arguments"] = json.loads(row["arguments"])
    except Exception:
        row["arguments"] = {}
    return row


def clear_pending(session_id):
    _exec("DELETE FROM pending_actions WHERE session_id = ?", (session_id,))


# ------------------------------------------------------- cache des recherches

def cache_results(session_id, concerts):
    conn = _connect()
    try:
        conn.execute("DELETE FROM resultats_cache WHERE session_id = ?", (session_id,))
        for c in concerts:
            conn.execute(
                "INSERT OR REPLACE INTO resultats_cache (session_id, concert_id, payload, cree_le) VALUES (?, ?, ?, ?)",
                (session_id, c.get("id", ""), json.dumps(c, ensure_ascii=False), now_iso()),
            )
        conn.commit()
    finally:
        conn.close()


def get_cached_concert(session_id, concert_id):
    row = _row(
        "SELECT payload FROM resultats_cache WHERE session_id = ? AND concert_id = ?",
        (session_id, concert_id),
    )
    if not row:
        return None
    try:
        return json.loads(row["payload"])
    except Exception:
        return None


def list_demo_concerts():
    return _rows("SELECT * FROM concerts_demo ORDER BY date ASC")
