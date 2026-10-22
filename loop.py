"""Boucle de l'agent : demande -> LLM -> tool -> resultat -> reponse."""

import json
from datetime import date

import db
from . import villes
from .llm import LLMError, obtenir_llm
from .regles import run_rules
from .tools import TOOL_MAP, TOOLS, execute_tool, format_date_fr, resume_result

MAX_STEPS = 6

SYSTEM_PROMPT = """Tu es Concert Agent, un agent qui aide a trouver des concerts en France.

Date du jour : {date}.

Regles absolues :
1. Tu ne connais AUCUNE date, salle, prix ou disponibilite de concert. Tu dois toujours appeler les tools pour obtenir des donnees.
2. N'invente jamais un concert, une date, un prix ou un lien. Si un tool renvoie statut="vide", dis qu'aucun concert ne correspond. Si statut="erreur", dis qu'il y a eu une panne et que tu ne peux pas repondre sans donnees.
3. Pour toute demande de concerts, appelle rechercher_concerts. Si l'utilisateur parle de ses artistes ou de ses preferences, tu peux appeler consulter_preferences d'abord.
4. Pour "le mois prochain", passe periode="mois_prochain". Pour "cette annee", passe periode="cette_annee". Pour "demain", periode="demain". Pour "ce week-end", periode="ce_weekend".
5. Si le resultat contient source="demo", precise clairement que ce sont des donnees de demonstration.
6. Les tools ajouter_favori et ajouter_artiste_suivi sont des ECRITURES : le systeme demande automatiquement confirmation a l'utilisateur. Appelle-les normalement, ne demande pas toi-meme la confirmation.
7. Quand le resultat de rechercher_concerts contient des concerts, reprends le champ "affichage" tel quel, sans modifier les dates, heures, prix ni les liens. Ajoute seulement une phrase d'introduction. N'utilise ni tableau ni lien Markdown : ecris l'URL complete.
8. Chaque concert doit afficher clairement : Artiste, Date (JJ/MM/AAAA), Heure (HH:MM), Lieu (salle, ville, region), Prix et Billetterie (URL complete). Si une information manque, ecris "non communique" ou "non disponible".
9. Reponds en francais, de facon concise. Ne mentionne pas les tools si ce n'est pas utile.
10. Si l'utilisateur demande l'historique, utilise historique_agent.
11. Si le resultat de rechercher_concerts contient un champ "note" ou "avertissement" non vide, reprends cette information a la fin de ta reponse.
"""


def _system_prompt():
    return SYSTEM_PROMPT.format(date=date.today().strftime("%d/%m/%Y"))


def _verdict(text):
    key = villes.norm(text)
    if key in ("oui", "yes", "ok", "d accord", "confirme", "valide", "go"):
        return "oui"
    if key in ("non", "no", "annule", "annuler", "stop"):
        return "non"
    return None


def _looks_like_concert_request(text):
    key = villes.norm(text)
    return any(word in key for word in (
        "concert", "concerts", "favori", "favoris", "artiste", "artistes",
        "prefere", "preferes", "ville", "region", "budget", "date", "demain",
        "mois prochain", "week end", "weekend", "cherche", "trouve", "recherche",
    ))


def _history_messages(session_id):
    rows = db.get_historique(session_id, 10)
    messages = []
    for row in rows:
        if row.get("role") in ("user", "assistant"):
            messages.append({
                "role": row["role"],
                "content": (row.get("contenu") or "")[:3000],
            })
    return messages


def _trace_entry(name, arguments, result, duree, statut=None):
    return {
        "tool": name,
        "arguments": arguments,
        "statut": statut or ("succes" if result.get("ok") else "erreur"),
        "duree_ms": duree,
        "resume": resume_result(name, result),
    }


def _format_search_reply(result):
    concerts = (result or {}).get("concerts") or []
    if not concerts:
        return None
    affichage = (result or {}).get("affichage") or ""
    nombre = len(concerts)
    titre = f"{nombre} concert" if nombre == 1 else f"{nombre} concerts"
    reply = f"J'ai trouvé {titre} :\n\n{affichage}".rstrip()
    note = ((result or {}).get("note") or "").strip()
    if note:
        reply += "\n\nℹ️ " + note
    return reply


def _write_reply(tool, result):
    if not result.get("ok"):
        return "❌ L'action a échoué : " + str(result.get("message", "erreur inconnue"))

    if tool == "ajouter_favori":
        concert = result.get("concert") or {}
        label = (
            f"« {concert.get('artiste')} — {format_date_fr(concert.get('date'))} "
            f"à {concert.get('ville')} »"
        )
        if result.get("deja_present"):
            return f"ℹ️ {label} est déjà dans tes favoris."
        return f"✅ C'est fait : {label} a été ajouté à tes favoris (n° {result.get('favori_id')})."

    if tool == "ajouter_artiste_suivi":
        if result.get("deja_present"):
            return f"ℹ️ « {result.get('artiste')} » est déjà dans tes artistes suivis."
        return f"✅ « {result.get('artiste')} » a été ajouté à tes artistes suivis."

    return "✅ Action effectuée."


def _run_llm(session_id, message, history, llm):
    messages = [{"role": "system", "content": _system_prompt()}]
    messages.extend(history)
    messages.append({"role": "user", "content": message})

    traces = []
    concert_result = None
    forced_tool = False

    for _step in range(MAX_STEPS):
        assistant = llm.chat(messages, TOOLS)
        tool_calls = assistant.get("tool_calls") or []

        if not tool_calls:
            content = (assistant.get("content") or "").strip()
            if not forced_tool and _looks_like_concert_request(message):
                forced_tool = True
                messages.append({
                    "role": "system",
                    "content": "Rappel : tu dois appeler un tool pour obtenir des donnees reelles. N'invente rien.",
                })
                continue
            if not content:
                content = "Je n'ai pas de réponse à te donner."
            return content, traces, None, concert_result

        messages.append({
            "role": "assistant",
            "content": assistant.get("content") or "",
            "tool_calls": tool_calls,
        })

        for call in tool_calls:
            function = call.get("function") or {}
            name = function.get("name") or ""
            raw_arguments = function.get("arguments") or "{}"
            call_id = call.get("id") or "call_0"

            try:
                arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else dict(raw_arguments)
                if not isinstance(arguments, dict):
                    raise ValueError("objet attendu")
            except Exception:
                arguments = {}
                result = {
                    "ok": False,
                    "statut": "erreur",
                    "message": "Arguments JSON invalides.",
                }
                traces.append(_trace_entry(name, arguments, result, 0))
                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": name,
                    "content": json.dumps(result, ensure_ascii=False),
                })
                continue

            tool = TOOL_MAP.get(name)
            if not tool:
                result = {"ok": False, "statut": "erreur", "message": f"Tool inconnu : {name}"}
                traces.append(_trace_entry(name, arguments, result, 0))
                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": name,
                    "content": json.dumps(result, ensure_ascii=False),
                })
                continue

            invalid = tool.validate(arguments, session_id)
            if invalid:
                traces.append(_trace_entry(name, arguments, invalid, 0))
                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": name,
                    "content": json.dumps(invalid, ensure_ascii=False),
                })
                continue

            if tool.is_write:
                db.set_pending(session_id, name, arguments)
                reply = tool.confirmation(arguments, session_id)
                traces.append({
                    "tool": name,
                    "arguments": arguments,
                    "statut": "confirmation",
                    "duree_ms": 0,
                    "resume": "en attente de confirmation",
                })
                pending = {"tool": name, "arguments": arguments, "message": reply}
                return reply, traces, pending, concert_result

            result, duree = execute_tool(name, arguments, session_id)
            if name == "rechercher_concerts" and result.get("concerts"):
                concert_result = result
            traces.append(_trace_entry(name, arguments, result, duree))
            messages.append({
                "role": "tool",
                "tool_call_id": call_id,
                "name": name,
                "content": json.dumps(result, ensure_ascii=False),
            })

    return "Je n'ai pas pu terminer la demande (trop d'étapes).", traces, None, concert_result


def run_agent(session_id, message="", confirm=None):
    message = (message or "").strip()
    pending = db.get_pending(session_id)

    if pending:
        verdict = _verdict(confirm) if confirm else _verdict(message)
        if verdict == "oui":
            db.clear_pending(session_id)
            db.log_interaction(session_id, "user", message or "oui")
            result, duree = execute_tool(pending["tool"], pending["arguments"], session_id)
            reply = _write_reply(pending["tool"], result)
            trace = _trace_entry(pending["tool"], pending["arguments"], result, duree)
            db.log_interaction(session_id, "assistant", reply)
            return {
                "reply": reply,
                "traces": [trace],
                "confirmation": None,
                "mode": "confirmation",
            }

        if verdict == "non":
            db.clear_pending(session_id)
            db.log_interaction(session_id, "user", message or "non")
            db.log_trace(
                session_id,
                pending["tool"],
                pending["arguments"],
                {"ok": False, "message": "Action annulee par l'utilisateur"},
                "refuse",
                0,
            )
            reply = "Action annulée. Aucune modification n'a été enregistrée."
            db.log_interaction(session_id, "assistant", reply)
            return {
                "reply": reply,
                "traces": [{
                    "tool": pending["tool"],
                    "arguments": pending["arguments"],
                    "statut": "refuse",
                    "duree_ms": 0,
                    "resume": "annulé par l'utilisateur",
                }],
                "confirmation": None,
                "mode": "confirmation",
            }

        return {
            "reply": (
                "Une action attend ta confirmation. Réponds « Oui » pour l'exécuter "
                "ou « Non » pour l'annuler."
            ),
            "traces": [],
            "confirmation": {
                "tool": pending["tool"],
                "arguments": pending["arguments"],
                "message": pending.get("message", ""),
            },
            "mode": "confirmation",
        }

    if not message:
        return {
            "reply": "Écris-moi une demande, par exemple : « Trouve un concert de mes artistes préférés le mois prochain. »",
            "traces": [],
            "confirmation": None,
            "mode": "regles",
        }

    history = _history_messages(session_id)
    llm = obtenir_llm()
    mode = "llm"

    if llm is not None:
        try:
            reply, traces, pending_action, concert_result = _run_llm(session_id, message, history, llm)
            mode = "llm"
            if pending_action is None:
                formatted = _format_search_reply(concert_result)
                if formatted:
                    reply = formatted
        except LLMError as exc:
            db.log_trace(
                session_id,
                "llm",
                {"message": message[:500]},
                {"ok": False, "message": str(exc)},
                "erreur",
                0,
            )
            reply, traces, pending_action = run_rules(session_id, message, note=str(exc))
            mode = "regles_fallback"
            reply = (
                "⚠️ Le LLM est indisponible (" + str(exc)[:140] + "). "
                "Je passe en mode règles.\n\n" + reply
            )
    else:
        reply, traces, pending_action = run_rules(session_id, message)
        mode = "regles"

    db.log_interaction(session_id, "user", message)
    db.log_interaction(session_id, "assistant", reply)

    return {
        "reply": reply,
        "traces": traces,
        "confirmation": pending_action,
        "mode": mode,
    }
