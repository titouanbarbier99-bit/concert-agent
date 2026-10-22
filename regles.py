"""Moteur de regles de secours.

Il reproduit le comportement de l'agent (mêmes tools, mêmes traces, même
confirmation) quand aucune cle LLM n'est configuree ou quand le LLM est
indisponible. Il sert aussi de filet de securite pour les demonstrations.
"""

import re
from datetime import date

import db
from . import villes
from .tools import (
    TOOL_MAP,
    execute_tool,
    format_concert_affichage,
    format_concerts_affichage,
    resume_result,
)


def _trace(name, arguments, result, duree, statut=None):
    return {
        "tool": name,
        "arguments": arguments,
        "statut": statut or ("succes" if result.get("ok") else "erreur"),
        "duree_ms": duree,
        "resume": resume_result(name, result),
    }


def _call(name, arguments, session_id, traces):
    result, duree = execute_tool(name, arguments, session_id)
    traces.append(_trace(name, arguments, result, duree))
    return result


def _help():
    return (
        "Je suis ton agent de concerts. Je peux :\n"
        "• chercher des concerts de tes artistes suivis,\n"
        "• filtrer par ville, région, date ou budget,\n"
        "• ajouter un concert à tes favoris (avec confirmation),\n"
        "• ajouter un artiste à ta liste suivie.\n\n"
        "Exemples :\n"
        "• « Trouve un concert de mes artistes préférés en Auvergne-Rhône-Alpes le mois prochain. »\n"
        "• « Je veux voir un concert à Paris demain, max 40 €. »\n"
        "• « Ajoute le concert de Gims à Lyon à mes favoris. »"
    )


def _known_artist(text):
    for name in sorted(db.list_artistes(), key=len, reverse=True):
        key = villes.norm(name)
        if key and (" " + key + " ") in (" " + text + " "):
            return name
    return None


def _extract_artist(text):
    known = _known_artist(text)
    if known:
        return known

    patterns = [
        r"concert de (.+?)(?: a mes favoris| aux favoris| dans mes favoris| a | au | en |$)",
        r"ajoute (?:l artiste )?(.+?)(?: a mes artistes| dans mes artistes| aux artistes|$)",
        r"suis (?:l artiste )?(.+?)(?:$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        candidate = match.group(1).strip(" .!?,")
        if not candidate:
            continue
        if any(word in candidate for word in ("mes artistes", "mes favoris", "concert", "artiste")):
            continue
        if len(candidate) > 60:
            continue
        return candidate.title()
    return None


def _extract_budget(text):
    match = re.search(r"(?:max(?:imum)?|budget|moins de|jusqu a)\s*(\d+)", text)
    if not match:
        match = re.search(r"(\d+)\s*(?:euros?|eur)", text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def _extract_periode(text):
    if "mois prochain" in text:
        return "mois_prochain"
    if "cette annee" in text or "annee en cours" in text:
        return "cette_annee"
    if "demain" in text:
        return "demain"
    if "week end" in text or "weekend" in text:
        return "ce_weekend"
    if "cette semaine" in text:
        return "cette_semaine"
    return None


def _extract_ville(text):
    return villes.find_city(text)


def _extract_region(text):
    code = villes.detect_region(text)
    return villes.region_name(code) if code else None


def _format_concerts(result):
    if not result.get("ok"):
        return (
            "❌ La recherche a échoué : "
            + str(result.get("message", "erreur inconnue"))
            + "\nJe ne peux pas te répondre sans données."
        )

    concerts = result.get("concerts") or []
    note = result.get("note") or ""
    if result.get("statut") == "vide" or not concerts:
        message = (
            "Je ne trouve aucun concert correspondant à ces critères. "
            "Je ne peux pas inventer de dates ni de salles."
        )
        if note:
            message += "\nℹ️ " + note
        return message

    nombre = len(concerts)
    titre = f"{nombre} concert" if nombre == 1 else f"{nombre} concerts"
    lines = [
        f"J'ai trouvé {titre} :",
        "",
        format_concerts_affichage(concerts, result.get("source")),
    ]

    if result.get("source") == "demo":
        lines.append("\n⚠️ Données de démonstration : ce ne sont pas de vrais événements.")
    elif note:
        lines.append("\nℹ️ " + note)
    return "\n".join(lines)


def _format_favoris(result):
    favoris = result.get("favoris") or []
    if not favoris:
        return "Tu n'as encore aucun concert dans tes favoris."
    blocs = [
        format_concert_affichage(favori, index)
        for index, favori in enumerate(favoris, start=1)
    ]
    return f"Tes favoris ({len(favoris)}) :\n\n" + "\n\n".join(blocs)


def _format_preferences(result, traces):
    prefs = result.get("preferences") or {}
    artistes = result.get("artistes_suivis") or []
    budget = prefs.get("budget_max")
    budget_txt = f"{int(budget)} €" if budget not in (None, "") else "non défini"
    return (
        "Tes préférences :\n"
        f"• Ville : {prefs.get('ville') or 'non définie'}\n"
        f"• Région : {prefs.get('region') or 'non définie'}\n"
        f"• Budget maximum : {budget_txt}\n"
        f"• Artistes suivis ({len(artistes)}) : " + (", ".join(artistes) if artistes else "aucun")
    )


def _format_historique(result):
    interactions = result.get("interactions") or []
    traces = result.get("traces") or []
    if not interactions:
        return "Aucune interaction enregistrée pour cette session."
    lines = ["Dernières interactions :"]
    for item in interactions[-6:]:
        role = "Toi" if item.get("role") == "user" else "Agent"
        content = (item.get("contenu") or "").replace("\n", " ")
        lines.append(f"• {role} : {content[:120]}")
    if traces:
        lines.append("\nDerniers tools appelés :")
        for trace in traces[-6:]:
            lines.append(f"• {trace.get('tool')} ({trace.get('statut')}, {trace.get('duree_ms')} ms)")
    return "\n".join(lines)


def _search(session_id, text, traces):
    prefs = _call("consulter_preferences", {}, session_id, traces)

    artiste = _known_artist(text)
    ville = _extract_ville(text)
    region = _extract_region(text)
    periode = _extract_periode(text)
    budget = _extract_budget(text)

    if not artiste and "mes artistes" not in text and "mes préférés" not in text and "mes preferes" not in text:
        artiste = _extract_artist(text)

    arguments = {}
    if artiste:
        arguments["artiste"] = artiste
    if ville:
        arguments["ville"] = ville
    if region:
        arguments["region"] = region
    if periode:
        arguments["periode"] = periode
    if budget is not None:
        arguments["budget_max"] = budget

    result = _call("rechercher_concerts", arguments, session_id, traces)
    reply = _format_concerts(result)

    if prefs.get("ok") and not artiste and not arguments.get("ville") and not arguments.get("region"):
        reply = f"J'utilise tes artistes suivis ({len(prefs.get('artistes_suivis') or [])}).\n\n" + reply
    return reply, None


def _add_favori(session_id, text, traces):
    artiste = _known_artist(text) or _extract_artist(text)
    ville = _extract_ville(text)
    region = _extract_region(text)
    periode = _extract_periode(text)
    budget = _extract_budget(text)

    arguments = {}
    if artiste:
        arguments["artiste"] = artiste
    if ville:
        arguments["ville"] = ville
    if region:
        arguments["region"] = region
    if periode:
        arguments["periode"] = periode
    if budget is not None:
        arguments["budget_max"] = budget

    result = _call("rechercher_concerts", arguments, session_id, traces)
    concerts = result.get("concerts") or []

    if not concerts:
        return _format_concerts(result), None

    concert = concerts[0]
    action = {"concert_id": concert.get("id")}
    db.set_pending(session_id, "ajouter_favori", action)
    reply = TOOL_MAP["ajouter_favori"].confirmation(action, session_id)
    traces.append({
        "tool": "ajouter_favori",
        "arguments": action,
        "statut": "confirmation",
        "duree_ms": 0,
        "resume": "en attente de confirmation",
    })
    pending = {"tool": "ajouter_favori", "arguments": action, "message": reply}
    return reply, pending


def _add_artiste(session_id, text, traces):
    artiste = _known_artist(text) or _extract_artist(text)
    if not artiste:
        return "Quel artiste veux-tu ajouter à ta liste suivie ?", None

    action = {"artiste": artiste}
    db.set_pending(session_id, "ajouter_artiste_suivi", action)
    reply = TOOL_MAP["ajouter_artiste_suivi"].confirmation(action, session_id)
    traces.append({
        "tool": "ajouter_artiste_suivi",
        "arguments": action,
        "statut": "confirmation",
        "duree_ms": 0,
        "resume": "en attente de confirmation",
    })
    pending = {"tool": "ajouter_artiste_suivi", "arguments": action, "message": reply}
    return reply, pending


def run_rules(session_id, message, note=None):
    """Retourne (reponse, traces, pending)."""
    text = villes.norm(message)
    traces = []

    if not text or text in ("bonjour", "salut", "hello", "coucou", "aide", "help"):
        return _help(), traces, None

    is_write_favori = (
        any(word in text for word in ("ajoute", "ajouter", "enregistre", "sauvegarde", "mets"))
        and "favori" in text
    )
    is_write_artiste = (
        any(word in text for word in ("ajoute", "ajouter", "suis", "suivre"))
        and "artiste" in text
        and "favori" not in text
    )
    is_history = "historique" in text or "qu as tu fait" in text
    is_favoris = "favori" in text and not is_write_favori
    is_prefs = any(word in text for word in ("preference", "profil", "ma ville", "mon budget"))
    is_search = any(word in text for word in ("concert", "concerts", "trouve", "recherche", "date", "voir"))

    if is_write_favori:
        reply, pending = _add_favori(session_id, text, traces)
        return reply, traces, pending

    if is_write_artiste:
        reply, pending = _add_artiste(session_id, text, traces)
        return reply, traces, pending

    if is_history:
        result = _call("historique_agent", {"limite": 8}, session_id, traces)
        return _format_historique(result), traces, None

    if is_favoris:
        result = _call("lister_favoris", {}, session_id, traces)
        return _format_favoris(result), traces, None

    if is_prefs:
        result = _call("consulter_preferences", {}, session_id, traces)
        return _format_preferences(result, traces), traces, None

    if is_search:
        reply, pending = _search(session_id, text, traces)
        return reply, traces, pending

    return _help(), traces, None
