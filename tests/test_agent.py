"""Tests fonctionnels des 3 scenarios du devoir.

Lancement :
    python -m unittest discover -s tests -v
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TEMP_DIR = tempfile.mkdtemp(prefix="concert-agent-tests-")
os.environ["CONCERT_DB_PATH"] = str(Path(TEMP_DIR) / "test.db")
os.environ["MODE_DEMO"] = "1"
os.environ["DEMO_FALLBACK"] = "1"
os.environ["GEMINI_API_KEY"] = ""
os.environ["LLM_API_KEY"] = ""
os.environ["SPOTIFY_CLIENT_ID"] = ""
os.environ["SPOTIFY_CLIENT_SECRET"] = ""
os.environ["REDIRECT_URI"] = ""

import app as app_module  # noqa: E402
import db  # noqa: E402
from agent.tools import TOOLS  # noqa: E402


def tearDownModule():
    shutil.rmtree(TEMP_DIR, ignore_errors=True)


class AgentApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_module.app.config.update(TESTING=True)
        cls.client = app_module.app.test_client()

    def setUp(self):
        db._exec("DELETE FROM favoris")
        db._exec("DELETE FROM pending_actions")
        db._exec("DELETE FROM interactions")
        db._exec("DELETE FROM tool_traces")
        db._exec("DELETE FROM resultats_cache")
        db._exec("DELETE FROM spotify_sessions")
        db._exec(
            """UPDATE preferences
               SET ville = ?, region = ?, region_code = ?, budget_max = ?, modifie_le = ?
               WHERE id = 1""",
            ("Lyon", "Auvergne-Rhône-Alpes", "ARA", 60, db.now_iso()),
        )
        for nom in ("Gims", "Ninho", "Orelsan", "SCH", "Damso", "Gazo", "Jul", "Aya Nakamura", "Sofiane Pamart"):
            db.add_artiste(nom)

    def post_chat(self, message="", confirm=None):
        payload = {"message": message}
        if confirm is not None:
            payload["confirm"] = confirm
        response = self.client.post("/api/chat", json=payload)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()

    def test_tools_du_devoir(self):
        noms = {tool.name for tool in TOOLS}
        self.assertEqual(noms, {
            "consulter_preferences",
            "rechercher_concerts",
            "ajouter_favori",
            "lister_favoris",
            "ajouter_artiste_suivi",
            "historique_agent",
        })
        writes = {tool.name for tool in TOOLS if tool.is_write}
        self.assertEqual(writes, {"ajouter_favori", "ajouter_artiste_suivi"})

    def test_etat_sans_cle_llm(self):
        data = self.client.get("/api/etat").get_json()
        self.assertFalse(data["llm"]["disponible"])
        self.assertEqual(data["llm"]["mode"], "regles")
        self.assertIsNone(data["pending"])
        self.assertRegex(data["date"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertFalse(data["spotify"]["configured"])
        self.assertFalse(data["spotify"]["connected"])

    def test_scenario_1_recherche_region_mois_prochain(self):
        data = self.post_chat(
            "Trouve un concert de mes artistes préférés en Auvergne-Rhône-Alpes le mois prochain."
        )
        self.assertEqual(data["mode"], "regles")
        self.assertIn("3 concert", data["reply"])
        self.assertIn("Gims", data["reply"])
        self.assertIn("démonstration", data["reply"])
        for label in ("Date :", "Heure :", "Lieu :", "Prix :", "Billetterie :"):
            self.assertIn(label, data["reply"])
        self.assertIsNone(data["confirmation"])

        tools = [trace["tool"] for trace in data["traces"]]
        self.assertIn("consulter_preferences", tools)
        self.assertIn("rechercher_concerts", tools)

        search = next(t for t in data["traces"] if t["tool"] == "rechercher_concerts")
        self.assertEqual(search["statut"], "succes")

    def test_scenario_2_aucun_resultat_sans_invention(self):
        data = self.post_chat("Je veux voir un concert à Paris demain, max 5 €.")
        self.assertIn("aucun concert", data["reply"].lower())
        self.assertIn("inventer", data["reply"].lower())
        self.assertEqual(data["mode"], "regles")

    def test_scenario_3_confirmation_puis_ajout_favori(self):
        data = self.post_chat("Ajoute le concert de Gims à Lyon à mes favoris.")
        self.assertIsNotNone(data["confirmation"])
        self.assertEqual(data["confirmation"]["tool"], "ajouter_favori")
        self.assertIn("Gims", data["confirmation"]["message"])
        self.assertIn("Confirmer", data["confirmation"]["message"])
        self.assertEqual(len(db.list_favoris()), 0)

        pending = self.client.get("/api/etat").get_json()["pending"]
        self.assertIsNotNone(pending)
        self.assertIn("Gims", pending["message"])

        confirmed = self.post_chat(confirm="oui")
        self.assertIn("ajouté", confirmed["reply"])
        self.assertEqual(confirmed["mode"], "confirmation")
        favoris = db.list_favoris()
        self.assertEqual(len(favoris), 1)
        self.assertEqual(favoris[0]["artiste"], "Gims")
        self.assertEqual(favoris[0]["ville"], "Lyon")

    def test_confirmation_refusee(self):
        self.post_chat("Ajoute le concert de Gims à Lyon à mes favoris.")
        refused = self.post_chat(confirm="non")
        self.assertIn("annulée", refused["reply"])
        self.assertEqual(len(db.list_favoris()), 0)
        self.assertIsNone(self.client.get("/api/etat").get_json()["pending"])

    def test_historique_et_traces(self):
        self.post_chat("Trouve un concert de Gims à Lyon le mois prochain.")
        data = self.client.get("/api/historique").get_json()
        self.assertGreaterEqual(len(data["interactions"]), 2)
        self.assertGreaterEqual(len(data["traces"]), 1)
        self.assertEqual(data["interactions"][0]["role"], "assistant")
        self.assertEqual(data["interactions"][1]["role"], "user")

    def test_preferences_budget_effacable(self):
        response = self.client.post("/api/preferences", json={
            "ville": "Paris",
            "region": "IDF",
            "budget_max": None,
        })
        self.assertEqual(response.status_code, 200)
        prefs = db.get_preferences()
        self.assertEqual(prefs["ville"], "Paris")
        self.assertEqual(prefs["region_code"], "IDF")
        self.assertIsNone(prefs["budget_max"])

    def test_spotify_non_configure_et_import_refuse(self):
        data = self.client.get("/api/spotify/status").get_json()
        self.assertFalse(data["configured"])
        self.assertFalse(data["connected"])

        response = self.client.post("/api/spotify/import", json={"limit": 30})
        self.assertEqual(response.status_code, 401)

        response = self.client.get("/login")
        self.assertEqual(response.status_code, 302)
        self.assertIn("spotify=config", response.headers["Location"])

        response = self.client.get("/callback?state=invalide&code=abc")
        self.assertEqual(response.status_code, 302)
        self.assertIn("spotify=state", response.headers["Location"])

    def test_spotify_login_redirige_vers_accounts(self):
        env = {
            "SPOTIFY_CLIENT_ID": "a" * 32,
            "SPOTIFY_CLIENT_SECRET": "b" * 32,
            "REDIRECT_URI": "http://127.0.0.1:5000/callback",
        }
        with patch.dict(os.environ, env):
            response = self.client.get("/login")
            self.assertEqual(response.status_code, 302)
            location = response.headers["Location"]
            self.assertIn("https://accounts.spotify.com/authorize", location)
            self.assertIn("client_id=" + "a" * 32, location)
            self.assertIn("state=", location)

            status = self.client.get("/api/spotify/status").get_json()
            self.assertTrue(status["configured"])
            self.assertFalse(status["connected"])

    def test_import_spotify_ajoute_artistes(self):
        self.client.get("/api/spotify/status")
        with self.client.session_transaction() as sess:
            session_id = sess["sid"]

        db.save_spotify_session(
            session_id, "access-test", "refresh-test", 9999999999,
            {"display_name": "Test Spotify"},
        )
        top = [{"name": "Artiste Spotify A"}, {"name": "Artiste Spotify B"}]
        recent = ["Artiste Spotify A", "Various Artists", "Artiste Spotify C"]

        with patch.object(app_module.spotify, "get_top_artists", return_value=top), \
                patch.object(app_module.spotify, "get_recent_artists", return_value=recent):
            response = self.client.post("/api/spotify/import", json={"limit": 30})

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["total"], 3)
        self.assertEqual(
            sorted(data["added"]),
            ["Artiste Spotify A", "Artiste Spotify B", "Artiste Spotify C"],
        )
        self.assertIn("Artiste Spotify A", db.list_artistes())

        with patch.object(app_module.spotify, "get_top_artists", return_value=top), \
                patch.object(app_module.spotify, "get_recent_artists", return_value=recent):
            second = self.client.post("/api/spotify/import", json={"limit": 30})

        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.get_json()["added"], [])

    def test_spotify_session_sqlite(self):
        self.client.get("/api/spotify/status")
        with self.client.session_transaction() as sess:
            session_id = sess["sid"]

        db.save_spotify_session(
            session_id, "access-1", "refresh-1", 9999999999,
            {"display_name": "Test Spotify"},
        )
        record = db.get_spotify_session(session_id)
        self.assertEqual(record["access_token"], "access-1")
        self.assertEqual(record["profile"]["display_name"], "Test Spotify")

        db.save_spotify_session(session_id, "access-2", "", 9999999999)
        record = db.get_spotify_session(session_id)
        self.assertEqual(record["access_token"], "access-2")
        self.assertEqual(record["refresh_token"], "refresh-1")

        self.client.get("/logout")
        self.assertIsNone(db.get_spotify_session(session_id))

    def test_artistes_et_favoris_api(self):
        response = self.client.post("/api/artistes", json={"artiste": "Booba"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Booba", response.get_json()["artistes"])

        self.post_chat("Ajoute le concert de Gims à Lyon à mes favoris.")
        self.post_chat(confirm="oui")
        favoris = self.client.get("/api/favoris").get_json()["favoris"]
        self.assertEqual(len(favoris), 1)

        response = self.client.delete("/api/favoris/" + str(favoris[0]["id"]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(db.list_favoris()), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
