"""Tools de l'agent.

Chaque tool porte une description en francais : c'est ce texte qui apprend
au LLM quand l'utiliser. Les tools d'ecriture sont marques is_write=True et
declenchent une confirmation avant execution.
"""

import json
import os
import time
from datetime import date, datetime, timedelta

import requests

import db
from . import villes

TM_URL = "https://app.ticketmaster.com/discovery/v2/events.json"
TM_ATTRACTIONS_URL = "https://app.ticketmaster.com/discovery/v2/attractions.json"
_TM_ATTRACTION_CACHE = {}


class ToolError(Exception):
    pass


# --------------------------------------------------------------------- dates

def _parse_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except ValueError:
        return None


def _next_month_range():
    today = date.today()
    year = today.year + (1 if today.month == 12 else 0)
    month = 1 if today.month == 12 else today.month + 1
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    return start, end


def _weekend_range():
    today = date.today()
    # 0 = lundi, 5 = samedi, 6 = dimanche
    days_until_saturday = (5 - today.weekday()) % 7
    if today.weekday() == 6:
        days_until_saturday = -1
    saturday = today + timedelta(days=days_until_saturday)
    sunday = saturday + timedelta(days=1)
    return saturday, sunday


def _resolve_range(periode, date_debut=None, date_fin=None):
    key = villes.norm(periode)
    if key in ("mois prochain", "le mois prochain", "next month"):
        return _next_month_range()
    if key == "demain":
        tomorrow = date.today() + timedelta(days=1)
        return tomorrow, tomorrow
    if key in ("ce weekend", "weekend", "ce week end"):
        return _weekend_range()
    if key in ("cette semaine", "semaine"):
        today = date.today()
        days_until_sunday = (6 - today.weekday()) % 7
        return today, today + timedelta(days=days_until_sunday)
    return _parse_date(date_debut), _parse_date(date_fin)


def format_date_fr(value):
    d = _parse_date(value)
    if not d:
        return value or "date inconnue"
    return d.strftime("%d/%m/%Y")


def format_price(concert):
    if concert.get("prix_min") is None and concert.get("prix_max") is None:
        return "prix non communiqué"
    pmin = concert.get("prix_min")
    pmax = concert.get("prix_max")
    devise = concert.get("devise") or "EUR"
    symbole = "€" if devise == "EUR" else devise
    if pmin is not None and pmax is not None and pmin != pmax:
        return f"de {_num(pmin)} à {_num(pmax)} {symbole}"
    value = pmin if pmin is not None else pmax
    return f"{_num(value)} {symbole}"


def _num(value):
    try:
        f = float(value)
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return value


def format_concert_affichage(concert, index=None):
    artiste = concert.get("artiste") or "Artiste inconnu"
    titre = f"{index}. {artiste}" if index else artiste
    date_txt = format_date_fr(concert.get("date"))
    heure = (concert.get("heure") or "").strip()
    heure_txt = heure[:5] if heure else "non communiquée"
    lieu = ", ".join(
        part for part in (concert.get("salle"), concert.get("ville")) if part
    ) or "non communiqué"
    region = (concert.get("region") or "").strip()
    if region and region != concert.get("ville"):
        lieu += f" ({region})"
    prix = format_price(concert)
    if prix == "prix non communiqué":
        prix = "non communiqué"
    if concert.get("source") == "demo":
        lien = "non disponible (démo)"
    else:
        lien = concert.get("url") or "non disponible"
    return "\n".join([
        titre,
        f"Date : {date_txt}",
        f"Heure : {heure_txt}",
        f"Lieu : {lieu}",
        f"Prix : {prix}",
        f"Billetterie : {lien}",
    ])


def format_concerts_affichage(concerts, source=None):
    return "\n\n".join(
        format_concert_affichage(concert, index)
        for index, concert in enumerate(concerts or [], start=1)
    )


# ------------------------------------------------------------- Ticketmaster

def _tm_key():
    return os.getenv("TICKETMASTER_API_KEY", "").strip()


def _tm_attraction_id(artist):
    cache_key = villes.norm(artist)
    if cache_key in _TM_ATTRACTION_CACHE:
        return _TM_ATTRACTION_CACHE[cache_key]

    params = {
        "apikey": _tm_key(),
        "keyword": artist,
        "locale": "fr-fr",
        "countryCode": "FR",
        "size": 50,
    }
    try:
        response = requests.get(TM_ATTRACTIONS_URL, params=params, timeout=12)
    except requests.RequestException as exc:
        raise ToolError("Ticketmaster injoignable") from exc

    if response.status_code in (401, 403):
        raise ToolError(f"Ticketmaster a refusé la clé (HTTP {response.status_code})")
    if response.status_code == 429:
        raise ToolError("quota Ticketmaster dépassé (HTTP 429)")
    if response.status_code >= 400:
        _TM_ATTRACTION_CACHE[cache_key] = None
        return None

    try:
        data = response.json()
    except ValueError:
        _TM_ATTRACTION_CACHE[cache_key] = None
        return None

    for attraction in (data.get("_embedded") or {}).get("attractions") or []:
        if villes.norm(attraction.get("name")) == cache_key:
            _TM_ATTRACTION_CACHE[cache_key] = attraction.get("id")
            return attraction.get("id")

    _TM_ATTRACTION_CACHE[cache_key] = None
    return None


def _tm_event_matches(event, artist):
    needle = villes.norm(artist)
    names = [event.get("name") or ""]
    names.extend(
        attraction.get("name") or ""
        for attraction in ((event.get("_embedded") or {}).get("attractions") or [])
    )
    return any(needle in villes.norm(name) for name in names)


def _tm_search(artist, start=None, end=None):
    key = _tm_key()
    if not key:
        raise ToolError("cle Ticketmaster absente")

    attraction_id = _tm_attraction_id(artist)
    params = {
        "apikey": key,
        "locale": "fr-fr",
        "countryCode": "FR",
        "size": 50,
        "sort": "date,asc",
    }
    if attraction_id:
        params["attractionId"] = attraction_id
    else:
        params["keyword"] = artist
    if start:
        params["startDateTime"] = start.isoformat() + "T00:00:00Z"
    if end:
        params["endDateTime"] = end.isoformat() + "T23:59:59Z"

    try:
        response = requests.get(TM_URL, params=params, timeout=12)
    except requests.RequestException as exc:
        raise ToolError("Ticketmaster injoignable") from exc

    if response.status_code in (401, 403):
        raise ToolError(f"Ticketmaster a refusé la clé (HTTP {response.status_code})")
    if response.status_code == 429:
        raise ToolError("quota Ticketmaster dépassé (HTTP 429)")
    if response.status_code >= 400:
        raise ToolError(f"Ticketmaster a renvoyé HTTP {response.status_code}")

    try:
        data = response.json()
    except ValueError as exc:
        raise ToolError("réponse Ticketmaster illisible") from exc

    events = (data.get("_embedded") or {}).get("events") or []
    concerts = []
    for event in events:
        if not attraction_id and not _tm_event_matches(event, artist):
            continue
        venues = (event.get("_embedded") or {}).get("venues") or [{}]
        venue = venues[0] or {}
        city = ((venue.get("city") or {}).get("name") or "").strip()
        state = ((venue.get("state") or {}).get("name") or "").strip()
        country = ((venue.get("country") or {}).get("name") or "France").strip()
        region_code = villes.city_region_code(city, state)
        prices = event.get("priceRanges") or []
        price = prices[0] if prices else {}
        start_info = (event.get("dates") or {}).get("start") or {}

        concerts.append({
            "id": "tm-" + str(event.get("id") or ""),
            "artiste": artist,
            "date": start_info.get("localDate") or "",
            "heure": start_info.get("localTime") or "",
            "salle": (venue.get("name") or "").strip(),
            "ville": city,
            "region": villes.region_name(region_code) or state,
            "region_code": region_code or "",
            "pays": country,
            "prix_min": price.get("min"),
            "prix_max": price.get("max"),
            "devise": price.get("currency") or "EUR",
            "url": event.get("url") or "",
            "source": "ticketmaster",
            "prix_inconnu": not bool(prices),
        })
    return concerts


# ------------------------------------------------------------------- demo

def _demo_search(artists, start=None, end=None):
    rows = db.list_demo_concerts()
    wanted = {villes.norm(a) for a in (artists or [])}
    out = []
    for row in rows:
        if wanted and villes.norm(row["artiste"]) not in wanted:
            continue
        concert_date = _parse_date(row["date"])
        if start and concert_date and concert_date < start:
            continue
        if end and concert_date and concert_date > end:
            continue
        out.append({
            "id": row["id"],
            "artiste": row["artiste"],
            "date": row["date"],
            "heure": row["heure"],
            "salle": row["salle"],
            "ville": row["ville"],
            "region": row["region"],
            "region_code": row["region_code"],
            "pays": row["pays"],
            "prix_min": row["prix_min"],
            "prix_max": row["prix_max"],
            "devise": row["devise"],
            "url": row["url"],
            "source": "demo",
            "prix_inconnu": row["prix_min"] is None,
        })
    return out


# ------------------------------------------------------------------ filtres

def _apply_filters(concerts, artiste=None, ville=None, region_code=None,
                   budget_max=None, start=None, end=None):
    out = []
    seen = set()
    artiste_key = villes.norm(artiste) if artiste else None
    ville_key = villes.norm(ville) if ville else None

    for concert in concerts:
        if artiste_key and artiste_key not in villes.norm(concert.get("artiste")):
            continue
        if ville_key and ville_key not in villes.norm(concert.get("ville")):
            continue

        if region_code:
            code = (
                concert.get("region_code")
                or villes.detect_region(concert.get("region"))
                or villes.detect_region(concert.get("ville"))
            )
            if code != region_code:
                continue

        concert_date = _parse_date(concert.get("date"))
        if start and concert_date and concert_date < start:
            continue
        if end and concert_date and concert_date > end:
            continue

        if budget_max is not None:
            price = concert.get("prix_min")
            if price is None:
                concert["prix_inconnu"] = True
            else:
                try:
                    if float(price) > float(budget_max):
                        continue
                except (TypeError, ValueError):
                    pass

        key = (
            villes.norm(concert.get("artiste")),
            concert.get("date"),
            villes.norm(concert.get("salle")),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(concert)

    out.sort(key=lambda c: (c.get("date") or "9999", villes.norm(c.get("artiste"))))
    return out


# --------------------------------------------------------------- tools (lecture)

def consulter_preferences(session_id):
    prefs = db.get_preferences()
    artistes = db.list_artistes()
    favoris = db.list_favoris()
    return {
        "ok": True,
        "statut": "resultats",
        "date_du_jour": date.today().isoformat(),
        "preferences": {
            "ville": prefs.get("ville", ""),
            "region": prefs.get("region", ""),
            "region_code": prefs.get("region_code", ""),
            "budget_max": prefs.get("budget_max"),
        },
        "artistes_suivis": artistes,
        "nombre_favoris": len(favoris),
        "message": f"{len(artistes)} artistes suivis, {len(favoris)} favoris.",
    }


def rechercher_concerts(session_id, artiste=None, ville=None, region=None,
                        date_debut=None, date_fin=None, periode=None,
                        budget_max=None, limite=10):
    artiste = (artiste or "").strip() or None
    ville = (ville or "").strip() or None
    region_code = villes.region_code(region) if region else None

    if ville and not region_code:
        region_code = villes.CITY_TO_REGION.get(villes.norm(ville))

    start, end = _resolve_range(periode, date_debut, date_fin)

    try:
        budget = float(budget_max) if budget_max not in (None, "") else None
    except (TypeError, ValueError):
        budget = None

    try:
        limite = max(1, min(int(limite or 10), 30))
    except (TypeError, ValueError):
        limite = 10

    artistes = [artiste] if artiste else db.list_artistes()
    if not artistes:
        return {
            "ok": False,
            "statut": "erreur",
            "source": "aucune",
            "concerts": [],
            "message": "Aucun artiste suivi. Ajoute d'abord un artiste.",
        }

    notes = []
    source = "demo"
    mode_demo = os.getenv("MODE_DEMO", "0").lower() in ("1", "true", "oui", "yes")
    demo_fallback = os.getenv("DEMO_FALLBACK", "1").lower() not in ("0", "false", "non", "no")
    key = _tm_key()

    if key and not mode_demo:
        errors = []
        raw = []
        for current in artistes[:8]:
            try:
                raw.extend(_tm_search(current, start, end))
            except ToolError as exc:
                errors.append(str(exc))

        if errors and not raw:
            if not demo_fallback:
                return {
                    "ok": False,
                    "statut": "erreur",
                    "source": "ticketmaster",
                    "concerts": [],
                    "message": "La recherche Ticketmaster a échoué : " + " ; ".join(errors[:2]),
                }
            source = "demo"
            notes.append("Ticketmaster indisponible (" + errors[0] + ").")
            raw = _demo_search(artistes, start, end)
        else:
            source = "ticketmaster"
            if errors:
                notes.append("Certaines requêtes Ticketmaster ont échoué (" + errors[0] + ").")
            if not raw and demo_fallback:
                source = "demo"
                notes.append("Aucun événement Ticketmaster : données de démonstration.")
                raw = _demo_search(artistes, start, end)
    else:
        source = "demo"
        if mode_demo:
            notes.append("Mode démonstration forcé.")
        elif not key:
            notes.append("Clé Ticketmaster absente : données de démonstration.")
        raw = _demo_search(artistes, start, end)

    concerts = _apply_filters(
        raw,
        artiste=artiste,
        ville=ville,
        region_code=region_code,
        budget_max=budget,
        start=start,
        end=end,
    )[:limite]

    db.cache_results(session_id, concerts)

    if concerts:
        message = f"{len(concerts)} concert(s) trouve(s)."
    else:
        message = "Aucun concert ne correspond aux critères demandés."

    if source == "demo":
        notes.append("Ces résultats sont des données de démonstration, pas des événements réels.")

    return {
        "ok": True,
        "statut": "resultats" if concerts else "vide",
        "source": source,
        "date_du_jour": date.today().isoformat(),
        "filtres": {
            "artiste": artiste,
            "ville": ville,
            "region": region,
            "region_code": region_code or "",
            "date_debut": start.isoformat() if start else "",
            "date_fin": end.isoformat() if end else "",
            "periode": periode or "",
            "budget_max": budget,
        },
        "concerts": concerts,
        "affichage": format_concerts_affichage(concerts, source),
        "note": " ".join(notes).strip(),
        "message": message,
    }


def lister_favoris(session_id):
    favoris = db.list_favoris()
    return {
        "ok": True,
        "statut": "resultats",
        "favoris": favoris,
        "message": f"{len(favoris)} favori(s).",
    }


def historique_agent(session_id, limite=8):
    try:
        limite = max(1, min(int(limite or 8), 20))
    except (TypeError, ValueError):
        limite = 8
    interactions = db.get_interactions(session_id, limite)
    traces = db.get_traces(session_id, limite)
    return {
        "ok": True,
        "statut": "resultats",
        "interactions": [
            {"role": r["role"], "contenu": r["contenu"], "date": r["cree_le"]}
            for r in reversed(interactions)
        ],
        "traces": [
            {
                "tool": t["tool"],
                "arguments": t["arguments"],
                "statut": t["statut"],
                "duree_ms": t["duree_ms"],
                "date": t["cree_le"],
            }
            for t in reversed(traces)
        ],
    }


# --------------------------------------------------------------- tools (ecriture)

def _favori_from_args(session_id, arguments):
    concert_id = (arguments or {}).get("concert_id") or (arguments or {}).get("id")
    if not concert_id:
        return None, "Identifiant de concert manquant."
    concert = db.get_cached_concert(session_id, concert_id)
    if not concert:
        return None, "Concert introuvable dans la derniere recherche. Relance une recherche avant d'ajouter un favori."
    return concert, None


def ajouter_favori(session_id, concert_id=None):
    concert, error = _favori_from_args(session_id, {"concert_id": concert_id})
    if error:
        return {"ok": False, "statut": "erreur", "message": error}

    favori_id, created = db.add_favori(concert)
    return {
        "ok": True,
        "statut": "resultats",
        "favori_id": favori_id,
        "deja_present": not created,
        "concert": concert,
        "message": (
            f"« {concert.get('artiste')} — {format_date_fr(concert.get('date'))} à "
            f"{concert.get('ville')} » est déjà dans les favoris."
            if not created else
            f"« {concert.get('artiste')} — {format_date_fr(concert.get('date'))} à "
            f"{concert.get('ville')} » ajouté aux favoris."
        ),
    }


def ajouter_artiste_suivi(session_id, artiste=None):
    nom = (artiste or "").strip()
    if not nom:
        return {"ok": False, "statut": "erreur", "message": "Nom d'artiste manquant."}
    added = db.add_artiste(nom)
    if added:
        message = f"« {nom} » ajouté aux artistes suivis."
    else:
        message = f"« {nom} » est déjà dans tes artistes suivis."
    return {
        "ok": True,
        "statut": "resultats",
        "artiste": nom,
        "deja_present": not added,
        "message": message,
    }


# ------------------------------------------------------------------- registry

class Tool:
    def __init__(self, name, description, parameters, func,
                 is_write=False, confirmation=None, validate=None):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.func = func
        self.is_write = is_write
        self._confirmation = confirmation
        self._validate = validate

    def schema_openai(self):
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def validate(self, arguments, session_id):
        if not self._validate:
            return None
        return self._validate(arguments or {}, session_id)

    def confirmation(self, arguments, session_id):
        if self._confirmation:
            return self._confirmation(arguments or {}, session_id)
        return f"Je vais executer « {self.name} ». Confirmer ?"


def _confirmation_favori(arguments, session_id):
    concert, error = _favori_from_args(session_id, arguments)
    if error:
        return f"Je ne peux pas ajouter ce concert : {error}"
    return (
        f"Je vais ajouter « {concert.get('artiste')} — {format_date_fr(concert.get('date'))} "
        f"à {concert.get('ville')} ({concert.get('salle')}) » à tes favoris. Confirmer ?"
    )


def _validate_favori(arguments, session_id):
    concert, error = _favori_from_args(session_id, arguments)
    if error:
        return {"ok": False, "statut": "erreur", "message": error}
    return None


def _confirmation_artiste(arguments, session_id):
    nom = (arguments or {}).get("artiste", "").strip()
    return f"Je vais ajouter « {nom} » à tes artistes suivis. Confirmer ?"


def _validate_artiste(arguments, session_id):
    if not (arguments or {}).get("artiste", "").strip():
        return {"ok": False, "statut": "erreur", "message": "Nom d'artiste manquant."}
    return None


TOOLS = [
    Tool(
        "consulter_preferences",
        "Lit les preferences de l'utilisateur (ville, region, budget maximum) et la liste "
        "de ses artistes suivis dans SQLite. A appeler avant une recherche quand l'utilisateur "
        "parle de « mes artistes », « mes preferences » ou « pres de chez moi ».",
        {"type": "object", "properties": {}, "required": []},
        consulter_preferences,
    ),
    Tool(
        "rechercher_concerts",
        "Recherche des concerts reels via Ticketmaster (ou des donnees de demonstration "
        "clairement signalees si l'API est indisponible). Utilise les artistes suivis si "
        "aucun artiste n'est precise. Retourne dates, salles, villes, prix et liens. "
        "A appeler pour toute demande de concerts.",
        {
            "type": "object",
            "properties": {
                "artiste": {"type": "string", "description": "Nom d'un artiste precis, facultatif."},
                "ville": {"type": "string", "description": "Ville francaise, facultatif."},
                "region": {"type": "string", "description": "Region francaise (nom ou code), facultatif."},
                "date_debut": {"type": "string", "description": "Date ISO de debut (AAAA-MM-JJ), facultatif."},
                "date_fin": {"type": "string", "description": "Date ISO de fin (AAAA-MM-JJ), facultatif."},
                "periode": {
                    "type": "string",
                    "enum": ["mois_prochain", "demain", "ce_weekend", "cette_semaine"],
                    "description": "Periode relative, facultatif.",
                },
                "budget_max": {"type": "number", "description": "Prix maximum en euros, facultatif."},
                "limite": {"type": "integer", "description": "Nombre maximum de concerts (defaut 10)."},
            },
            "required": [],
        },
        rechercher_concerts,
    ),
    Tool(
        "ajouter_favori",
        "Enregistre un concert dans les favoris SQLite. Action d'ECRITURE : le systeme "
        "demande confirmation a l'utilisateur avant d'executer. Utilise l'identifiant `id` "
        "renvoye par rechercher_concerts.",
        {
            "type": "object",
            "properties": {
                "concert_id": {"type": "string", "description": "Identifiant du concert renvoye par rechercher_concerts."},
            },
            "required": ["concert_id"],
        },
        ajouter_favori,
        is_write=True,
        confirmation=_confirmation_favori,
        validate=_validate_favori,
    ),
    Tool(
        "lister_favoris",
        "Liste les concerts deja enregistres dans les favoris SQLite.",
        {"type": "object", "properties": {}, "required": []},
        lister_favoris,
    ),
    Tool(
        "ajouter_artiste_suivi",
        "Ajoute un artiste a la liste suivie dans SQLite. Action d'ECRITURE : le systeme "
        "demande confirmation a l'utilisateur avant d'executer.",
        {
            "type": "object",
            "properties": {
                "artiste": {"type": "string", "description": "Nom de l'artiste a suivre."},
            },
            "required": ["artiste"],
        },
        ajouter_artiste_suivi,
        is_write=True,
        confirmation=_confirmation_artiste,
        validate=_validate_artiste,
    ),
    Tool(
        "historique_agent",
        "Retourne les dernieres demandes, reponses et traces d'outils de cette session. "
        "Utile pour repondre a « qu'est-ce que tu as fait ? ».",
        {
            "type": "object",
            "properties": {
                "limite": {"type": "integer", "description": "Nombre d'elements (defaut 8)."},
            },
            "required": [],
        },
        historique_agent,
    ),
]

TOOL_MAP = {tool.name: tool for tool in TOOLS}


def execute_tool(name, arguments, session_id):
    tool = TOOL_MAP.get(name)
    started = time.time()

    if not tool:
        result = {"ok": False, "statut": "erreur", "message": f"Tool inconnu : {name}"}
    else:
        try:
            result = tool.func(session_id, **(arguments or {}))
        except TypeError as exc:
            result = {"ok": False, "statut": "erreur", "message": f"Arguments invalides : {exc}"}
        except Exception as exc:  # noqa: BLE001 - on renvoie l'erreur au LLM
            result = {"ok": False, "statut": "erreur", "message": f"Erreur interne : {exc}"}

    duree = int((time.time() - started) * 1000)
    db.log_trace(
        session_id,
        name,
        arguments or {},
        result,
        "succes" if result.get("ok") else "erreur",
        duree,
    )
    return result, duree


def resume_result(name, result):
    if not result.get("ok"):
        return str(result.get("message", "erreur"))[:160]
    if name == "rechercher_concerts":
        return f"{len(result.get('concerts', []))} concert(s), source={result.get('source')}"
    if name == "consulter_preferences":
        return f"{len(result.get('artistes_suivis', []))} artistes suivis"
    if name == "lister_favoris":
        return f"{len(result.get('favoris', []))} favori(s)"
    if name == "ajouter_favori":
        return "favori enregistré" if not result.get("deja_present") else "déjà en favori"
    if name == "ajouter_artiste_suivi":
        etat = "déjà suivi" if result.get("deja_present") else "ajouté"
        return f"{result.get('artiste', '')} {etat}"
    if name == "historique_agent":
        return f"{len(result.get('interactions', []))} interactions"
    return str(result.get("message", "ok"))[:160]
