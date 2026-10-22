# Guide des 3 démonstrations

## Préparation

1. Lancer l'application :

        run.bat

2. Ouvrir **http://127.0.0.1:5000**.

3. Vérifier les badges en haut à droite :

    - `LLM : gemini-3.5-flash-lite` si la clé Gemini est configurée ; `LLM : mode règles` sinon ;
    - `Ticketmaster : clé active` si la clé est configurée ; les résultats peuvent être réels ou basculer en démo si aucun événement n'est trouvé ;
    - `Spotify : connecté` après une connexion réussie.

4. Pour repartir d'une base propre avant la démo :

        .venv\Scripts\python.exe -c "import db; [db._exec('DELETE FROM ' + t) for t in ('favoris','pending_actions','interactions','tool_traces','resultats_cache')]"

    Cela supprime les favoris et l'historique, mais garde les artistes suivis et les préférences.

---

## Démo 0 (optionnelle) — Import Spotify

### Préparation

1. Le dashboard Spotify doit contenir `http://127.0.0.1:5000/callback` dans **Redirect URIs**. Spotify n'accepte plus `localhost` : utiliser l'IP loopback `127.0.0.1`.
2. Le compte utilisé doit être ajouté dans **User Management** (5 comptes maximum en mode développement).
3. Cliquer sur **Se connecter avec Spotify**, accepter les scopes, puis revenir sur l'application.

### Ce qui doit se passer

- Le badge passe à `Spotify : connecté`.
- Le profil Spotify apparaît en haut à droite.
- Les top artistes et les écoutes récentes sont ajoutés aux artistes suivis (30 maximum, sans doublons).
- Le bouton **Importer mes artistes** permet de relancer l'import.

### Phrase d'explication

> « La connexion Spotify remplace l'ancien site Node : les artistes que tu écoutes vraiment alimentent directement l'agent. »

---

## Démo 1 — Recherche avec préférences

### Message à envoyer

> Trouve un concert de mes artistes préférés en Auvergne-Rhône-Alpes le mois prochain.

### Ce qui doit se passer

1. L'agent appelle `consulter_preferences`.
2. Il appelle `rechercher_concerts` avec la région `ARA` et la période `mois_prochain`.
3. Il répond avec les concerts trouvés par Ticketmaster. Exemple avec la clé actuelle : Gims — LDLC Arena, Décines (Auvergne-Rhône-Alpes), en novembre 2026.
4. Chaque concert affiche : artiste, date, heure, lieu, prix et lien de billetterie.
5. Si Ticketmaster ne trouve rien, il bascule sur 3 concerts de démonstration et l'indique.

### Preuve à montrer

- Les traces `consulter_preferences` et `rechercher_concerts`.
- Le badge `Ticketmaster : clé active` et la source `ticketmaster`.
- Si la source est `demo`, l'avertissement « Données de démonstration ».

### Phrase d'explication

> « L'agent ne connaît pas les concerts : il a appelé un tool, et c'est le résultat du tool qui construit la réponse. »

---

## Démo 2 — Aucun résultat sans invention

### Message à envoyer

> Je veux voir un concert à Paris demain, max 5 €.

### Ce qui doit se passer

1. L'agent cherche réellement avec les filtres Paris + demain + 5 €.
2. Aucun concert ne correspond.
3. Il répond :

   > Je ne trouve aucun concert correspondant à ces critères. Je ne peux pas inventer de dates ni de salles.

### Preuve à montrer

- La trace `rechercher_concerts` avec le statut `succes` mais zéro concert.
- L'absence de date ou de salle inventée dans la réponse.
- Le fait que l'agent ne remplit pas le vide avec un faux concert.

### Phrase d'explication

> « Un agent fiable, c'est aussi un agent qui sait dire qu'il n'a rien trouvé. »

---

## Démo 3 — Écriture avec confirmation

### Message à envoyer

> Ajoute le concert de Gims à Décines à mes favoris.

### Ce qui doit se passer

1. L'agent cherche le concert.
2. Il prépare l'action `ajouter_favori`.
3. Il affiche une demande de confirmation :

   > Je vais ajouter « Gims — ... à Décines (LDLC Arena) » à tes favoris. Confirmer ?

4. **Ne pas cliquer tout de suite sur Oui.**
5. Montrer que le favori n'est pas encore dans la barre latérale.
6. Cliquer sur **Oui, confirmer**.
7. L'agent exécute le tool et répond :

   > ✅ C'est fait : « Gims — ... à Décines » a été ajouté à tes favoris (n° 1).

8. Le favori apparaît dans la colonne « Favoris ».
9. Cliquer sur le favori : la fiche affiche l'artiste, la date, l'heure, la salle, la ville, la région, le pays, le prix, la source, la date d'ajout et le lien de billetterie lorsqu'il existe.

### Variante à montrer

Recommencer avec un autre concert, puis cliquer sur **Non, annuler**. Le favori n'est pas ajouté et la trace indique `refuse`.

### Phrase d'explication

> « Le tool d'écriture est bloqué tant que l'utilisateur n'a pas confirmé. Ce n'est pas une consigne donnée au LLM : c'est le code Python qui impose la pause. »

---

## Démo 4 (optionnelle) — Historique et traces

### Message à envoyer

> Montre-moi l'historique de ce que tu as fait.

### Ce qui doit se passer

- L'agent appelle `historique_agent`.
- Il affiche les dernières demandes, réponses et traces.
- Le panneau « Traces de l'agent » de chaque message montre les tools, arguments, statuts et durées.

---

## Checklist avant l'oral

- [ ] `run.bat` lancé, page `http://127.0.0.1:5000` ouverte.
- [ ] Base nettoyée (favoris et historique vides).
- [ ] Démo 1 : concerts affichés (réels ou démo signalés).
- [ ] Démo 2 : aucun résultat, aucune invention.
- [ ] Démo 3 : confirmation visible, favori ajouté après Oui.
- [ ] Variante Non : aucun favori ajouté.
- [ ] Traces visibles.
- [ ] Badge LLM / données / Spotify compris.
- [ ] Tests lancés une fois : `Ran 13 tests ... OK`.

## Dépannage rapide

### Le port 5000 est déjà utilisé

```powershell
netstat -ano | findstr :5000
taskkill /PID <PID> /F
```

### `python` n'est pas reconnu

Utiliser `run.bat` ou :

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe app.py
```

### Le badge indique « mode règles »

C'est normal si la clé Gemini est absente ou refusée. Pour activer le LLM :

1. ouvrir `.env` ;
2. renseigner `GEMINI_API_KEY=...` ;
3. redémarrer le serveur.

### Les concerts affichés sont des données de démonstration

C'est normal si Ticketmaster ne trouve aucun événement pour cet artiste ou ces critères. L'application bascule alors sur les données de démonstration et le signale explicitement.

### Spotify affiche « non configuré »

Vérifier que `.env` contient `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET` et `REDIRECT_URI`, puis redémarrer le serveur.

### Spotify renvoie `INVALID_CLIENT` ou `redirect_uri mismatch`

L'URI doit être identique au caractère près à celle du dashboard Spotify. En local : `http://127.0.0.1:5000/callback`.

### Spotify renvoie « User not registered in the Developer Dashboard »

Ajouter le compte dans **User Management** du dashboard Spotify. Le mode développement est limité à 5 comptes.
