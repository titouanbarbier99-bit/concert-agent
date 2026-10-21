(() => {
  "use strict";

  const messagesEl = document.getElementById("messages");
  const chatForm = document.getElementById("chat-form");
  const chatInput = document.getElementById("chat-input");
  const sendBtn = document.getElementById("send-btn");
  const confirmationEl = document.getElementById("confirmation");
  const confirmationText = confirmationEl.querySelector(".confirmation-text");
  const confirmYes = document.getElementById("confirm-yes");
  const confirmNo = document.getElementById("confirm-no");
  const llmStatus = document.getElementById("llm-status");
  const dataStatus = document.getElementById("data-status");
  const prefsForm = document.getElementById("prefs-form");
  const prefVille = document.getElementById("pref-ville");
  const prefRegion = document.getElementById("pref-region");
  const prefBudget = document.getElementById("pref-budget");
  const artistForm = document.getElementById("artist-form");
  const artistInput = document.getElementById("artist-input");
  const artistsList = document.getElementById("artists-list");
  const favsList = document.getElementById("favs-list");
  const toastContainer = document.getElementById("toast-container");
  const spotifyStatus = document.getElementById("spotify-status");
  const spotifyLogin = document.getElementById("spotify-login");
  const spotifyProfile = document.getElementById("spotify-profile");
  const spotifyAvatar = document.getElementById("spotify-avatar");
  const spotifyName = document.getElementById("spotify-name");
  const spotifyImport = document.getElementById("spotify-import");
  const spotifyHint = document.getElementById("spotify-hint");

  let busy = false;
  let llmConfigured = false;

  async function api(path, options = {}) {
    const response = await fetch(path, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    const text = await response.text();
    let data;
    try {
      data = text ? JSON.parse(text) : {};
    } catch {
      data = { error: text || `Erreur HTTP ${response.status}` };
    }
    if (!response.ok) {
      throw new Error(data.reply || data.error || `Erreur HTTP ${response.status}`);
    }
    return data;
  }

  function toast(message, isError = false) {
    const el = document.createElement("div");
    el.className = "toast" + (isError ? " error" : "");
    el.textContent = message;
    toastContainer.appendChild(el);
    setTimeout(() => el.remove(), 3800);
  }

  function scrollBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function renderTraces(traces) {
    if (!Array.isArray(traces) || !traces.length) return null;

    const details = document.createElement("details");
    details.className = "traces";
    const summary = document.createElement("summary");
    summary.textContent = `🔧 Traces de l'agent (${traces.length})`;
    details.appendChild(summary);

    traces.forEach((trace) => {
      const box = document.createElement("div");
      box.className = "trace";

      const head = document.createElement("div");
      head.className = "trace-head";

      const name = document.createElement("span");
      name.className = "trace-name";
      name.textContent = trace.tool || "tool";
      head.appendChild(name);

      const status = document.createElement("span");
      status.className = "trace-status " + (trace.statut || "erreur");
      status.textContent = trace.statut || "?";
      head.appendChild(status);

      if (typeof trace.duree_ms === "number") {
        const duration = document.createElement("span");
        duration.textContent = `${trace.duree_ms} ms`;
        head.appendChild(duration);
      }

      box.appendChild(head);

      if (trace.arguments && Object.keys(trace.arguments).length) {
        const args = document.createElement("pre");
        args.textContent = "args " + JSON.stringify(trace.arguments);
        box.appendChild(args);
      }

      if (trace.resume) {
        const resume = document.createElement("pre");
        resume.textContent = "→ " + trace.resume;
        box.appendChild(resume);
      }

      details.appendChild(box);
    });

    return details;
  }

  function linkifyMessage(container, text) {
    const normalized = String(text || "").replace(
      /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
      "$1 : $2"
    );
    const pattern = /https?:\/\/[^\s]+/g;
    let lastIndex = 0;

    for (const match of normalized.matchAll(pattern)) {
      if (match.index > lastIndex) {
        container.appendChild(document.createTextNode(normalized.slice(lastIndex, match.index)));
      }
      const link = document.createElement("a");
      link.href = match[0];
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = match[0];
      container.appendChild(link);
      lastIndex = match.index + match[0].length;
    }

    if (lastIndex < normalized.length) {
      container.appendChild(document.createTextNode(normalized.slice(lastIndex)));
    }
  }

  function addMessage(role, text, traces = []) {
    const wrapper = document.createElement("div");
    wrapper.className = "msg " + (role === "user" ? "user" : "agent");

    const bubble = document.createElement("div");
    bubble.className = "bubble";
    linkifyMessage(bubble, text);
    wrapper.appendChild(bubble);

    const traceBox = renderTraces(traces);
    if (traceBox && role !== "user") {
      bubble.appendChild(traceBox);
    }

    messagesEl.appendChild(wrapper);
    scrollBottom();
    return wrapper;
  }

  function addTyping() {
    const wrapper = document.createElement("div");
    wrapper.className = "msg agent";
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.innerHTML = '<span class="typing"><i></i><i></i><i></i></span>';
    wrapper.appendChild(bubble);
    messagesEl.appendChild(wrapper);
    scrollBottom();
    return wrapper;
  }

  function showConfirmation(message) {
    confirmationText.textContent = message || "Confirmer cette action ?";
    confirmationEl.classList.remove("hidden");
    scrollBottom();
  }

  function hideConfirmation() {
    confirmationEl.classList.add("hidden");
    confirmationText.textContent = "";
  }

  function setBusy(value) {
    busy = value;
    sendBtn.disabled = value;
    chatInput.disabled = value;
  }

  function updateMode(mode) {
    if (!mode) return;
    if (mode === "llm") {
      if (llmConfigured) {
        llmStatus.textContent = "LLM : Gemini";
        llmStatus.className = "badge ok";
      }
    } else if (mode === "regles") {
      llmStatus.textContent = "LLM : mode règles";
      llmStatus.className = "badge warn";
    } else if (mode === "regles_fallback") {
      llmStatus.textContent = "LLM : secours règles";
      llmStatus.className = "badge warn";
    }
  }

  async function loadEtat() {
    try {
      const data = await api("/api/etat");
      const llm = data.llm || {};
      llmConfigured = Boolean(llm.disponible);
      if (llm.disponible) {
        llmStatus.textContent = `LLM : ${llm.model || llm.provider || "actif"}`;
        llmStatus.className = "badge ok";
      } else {
        llmStatus.textContent = "LLM : mode règles";
        llmStatus.className = "badge warn";
      }

      if (data.ticketmaster) {
        dataStatus.textContent = "Ticketmaster : clé active";
        dataStatus.className = "badge ok";
      } else {
        dataStatus.textContent = data.demo_force ? "Données : démo" : "Données : démo (secours)";
        dataStatus.className = "badge warn";
      }

      if (data.pending) {
        showConfirmation(data.pending.message || "Une action attend ta confirmation.");
      }
    } catch (error) {
      llmStatus.textContent = "Agent : erreur";
      llmStatus.className = "badge warn";
      console.warn(error);
    }
  }

  function setSpotifyDisconnected(configured) {
    spotifyProfile.classList.add("hidden");
    spotifyLogin.classList.remove("hidden");

    if (configured) {
      spotifyStatus.textContent = "Spotify : prêt";
      spotifyStatus.className = "badge";
      spotifyLogin.textContent = "Se connecter avec Spotify";
      spotifyLogin.href = "/login";
      spotifyLogin.classList.remove("is-disabled");
      delete spotifyLogin.dataset.disabled;
      spotifyHint.textContent = "Connecte Spotify pour importer tes artistes en un clic.";
    } else {
      spotifyStatus.textContent = "Spotify : non configuré";
      spotifyStatus.className = "badge warn";
      spotifyLogin.textContent = "Spotify non configuré";
      spotifyLogin.href = "#";
      spotifyLogin.classList.add("is-disabled");
      spotifyLogin.dataset.disabled = "1";
      spotifyHint.textContent =
        "Spotify n'est pas configuré : ajoute SPOTIFY_CLIENT_ID et SPOTIFY_CLIENT_SECRET dans .env.";
    }
  }

  async function loadSpotify() {
    try {
      const data = await api("/api/spotify/status");
      if (data.connected) {
        const profile = data.profile || {};
        spotifyStatus.textContent = "Spotify : connecté";
        spotifyStatus.className = "badge ok";
        spotifyLogin.classList.add("hidden");
        spotifyProfile.classList.remove("hidden");
        spotifyName.textContent = profile.display_name || "Compte Spotify";
        if (profile.image) {
          spotifyAvatar.src = profile.image;
          spotifyAvatar.style.display = "";
        } else {
          spotifyAvatar.removeAttribute("src");
          spotifyAvatar.style.display = "none";
        }
        spotifyHint.textContent = "Ton profil Spotify est connecté. Importe tes artistes quand tu veux.";
      } else {
        setSpotifyDisconnected(Boolean(data.configured));
      }
    } catch (error) {
      spotifyStatus.textContent = "Spotify : erreur";
      spotifyStatus.className = "badge warn";
      setSpotifyDisconnected(false);
      console.warn(error);
    }
  }

  async function importSpotifyArtists() {
    spotifyImport.disabled = true;
    const label = spotifyImport.textContent;
    spotifyImport.textContent = "Import…";
    try {
      const data = await api("/api/spotify/import", {
        method: "POST",
        body: JSON.stringify({ limit: 30 }),
      });
      toast(data.message || "Artistes Spotify importés.");
      await loadSidebar();
    } catch (error) {
      toast(error.message, true);
      await loadSpotify();
    } finally {
      spotifyImport.disabled = false;
      spotifyImport.textContent = label;
    }
  }

  function handleSpotifyQuery() {
    const params = new URLSearchParams(window.location.search);
    const value = params.get("spotify");
    if (!value) return;

    const imported = Number(params.get("imported") || 0);
    const reason = params.get("reason") || "";
    window.history.replaceState(null, "", window.location.pathname);

    if (value === "connected") {
      toast(
        imported > 0
          ? `Spotify connecté : ${imported} artiste(s) importé(s).`
          : "Spotify connecté. Aucun nouvel artiste à importer."
      );
      loadSidebar();
    } else if (value === "error") {
      toast("Connexion Spotify impossible : " + (reason || "réessaie."), true);
    } else if (value === "state") {
      toast("Session Spotify invalide. Réessaie la connexion.", true);
    } else if (value === "config") {
      toast("Spotify n'est pas configuré : ajoute les clés dans .env.", true);
    } else if (value === "logout") {
      toast("Spotify déconnecté.");
    }
  }

  function formatDate(iso) {
    if (!iso) return "date inconnue";
    const parsed = new Date(iso + "T12:00:00");
    if (Number.isNaN(parsed.getTime())) return iso;
    return parsed.toLocaleDateString("fr-FR", {
      weekday: "short",
      day: "numeric",
      month: "short",
      year: "numeric",
    });
  }

  function renderSidebar(data) {
    const prefs = data.preferences || {};
    if (document.activeElement !== prefVille) prefVille.value = prefs.ville || "";
    if (document.activeElement !== prefRegion) prefRegion.value = prefs.region_code || "";
    if (document.activeElement !== prefBudget) {
      prefBudget.value = prefs.budget_max === null || prefs.budget_max === undefined
        ? ""
        : prefs.budget_max;
    }

    const artistes = data.artistes || [];
    artistsList.innerHTML = "";
    if (!artistes.length) {
      const empty = document.createElement("p");
      empty.className = "muted";
      empty.textContent = "Aucun artiste suivi.";
      artistsList.appendChild(empty);
    } else {
      artistes.forEach((nom) => {
        const chip = document.createElement("span");
        chip.className = "artist-chip";
        const label = document.createElement("span");
        label.textContent = nom;
        const remove = document.createElement("button");
        remove.type = "button";
        remove.title = "Retirer " + nom;
        remove.textContent = "×";
        remove.addEventListener("click", () => removeArtist(nom));
        chip.appendChild(label);
        chip.appendChild(remove);
        artistsList.appendChild(chip);
      });
    }

    const favoris = data.favoris || [];
    favsList.innerHTML = "";
    if (!favoris.length) {
      const empty = document.createElement("p");
      empty.className = "muted";
      empty.textContent = "Aucun favori pour l'instant.";
      favsList.appendChild(empty);
    } else {
      favoris.forEach((fav) => {
        const item = document.createElement("div");
        item.className = "fav-item";

        const title = document.createElement("b");
        title.textContent = `${fav.artiste} — ${formatDate(fav.date)}`;
        item.appendChild(title);

        const place = document.createElement("span");
        place.textContent = [fav.salle, fav.ville].filter(Boolean).join(", ");
        item.appendChild(place);

        if (fav.prix_min !== null && fav.prix_min !== undefined) {
          const price = document.createElement("span");
          const value = fav.prix_min === fav.prix_max
            ? `${fav.prix_min} €`
            : `${fav.prix_min} – ${fav.prix_max} €`;
          price.textContent = " · " + value;
          item.appendChild(price);
        }

        const actions = document.createElement("div");
        actions.className = "fav-actions";
        const remove = document.createElement("button");
        remove.type = "button";
        remove.textContent = "retirer";
        remove.addEventListener("click", () => removeFavori(fav.id));
        actions.appendChild(remove);
        item.appendChild(actions);

        favsList.appendChild(item);
      });
    }
  }

  async function loadSidebar() {
    try {
      const data = await api("/api/preferences");
      renderSidebar(data);
    } catch (error) {
      console.warn(error);
    }
  }

  async function loadHistorique() {
    try {
      const data = await api("/api/historique");
      const items = (data.interactions || []).slice().reverse();
      if (!items.length) return;

      const divider = document.createElement("div");
      divider.className = "muted";
      divider.style.textAlign = "center";
      divider.style.padding = "4px 0";
      divider.textContent = "Conversation précédente";
      messagesEl.appendChild(divider);

      items.slice(-20).forEach((item) => {
        if (item.role === "user" || item.role === "assistant") {
          addMessage(item.role === "user" ? "user" : "agent", item.contenu);
        }
      });
    } catch (error) {
      console.warn(error);
    }
  }

  async function sendMessage(text, confirm) {
    if (busy) return;
    const trimmed = (text || "").trim();
    if (!trimmed && !confirm) return;

    hideConfirmation();
    if (trimmed) addMessage("user", trimmed);

    setBusy(true);
    const typing = addTyping();

    try {
      const payload = confirm ? { message: "", confirm } : { message: trimmed };
      const data = await api("/api/chat", {
        method: "POST",
        body: JSON.stringify(payload),
      });

      typing.remove();
      addMessage("agent", data.reply || "Je n'ai pas de réponse.", data.traces || []);
      if (data.confirmation) {
        showConfirmation(data.confirmation.message);
      }
      updateMode(data.mode);
      await loadSidebar();
    } catch (error) {
      typing.remove();
      addMessage("agent", "❌ " + error.message);
      toast(error.message, true);
      console.error(error);
    } finally {
      setBusy(false);
      chatInput.focus();
    }
  }

  async function savePreferences(event) {
    event.preventDefault();
    try {
      await api("/api/preferences", {
        method: "POST",
        body: JSON.stringify({
          ville: prefVille.value.trim(),
          region: prefRegion.value,
          budget_max: prefBudget.value === "" ? null : Number(prefBudget.value),
        }),
      });
      toast("Préférences enregistrées.");
      await loadSidebar();
    } catch (error) {
      toast(error.message, true);
    }
  }

  async function addArtist(nom) {
    try {
      await api("/api/artistes", {
        method: "POST",
        body: JSON.stringify({ artiste: nom }),
      });
      toast(`« ${nom} » ajouté aux artistes suivis.`);
      await loadSidebar();
    } catch (error) {
      toast(error.message, true);
    }
  }

  async function removeArtist(nom) {
    try {
      await api("/api/artistes/" + encodeURIComponent(nom), { method: "DELETE" });
      toast(`« ${nom} » retiré.`);
      await loadSidebar();
    } catch (error) {
      toast(error.message, true);
    }
  }

  async function removeFavori(id) {
    try {
      await api("/api/favoris/" + id, { method: "DELETE" });
      toast("Favori retiré.");
      await loadSidebar();
    } catch (error) {
      toast(error.message, true);
    }
  }

  chatForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const value = chatInput.value;
    chatInput.value = "";
    sendMessage(value);
  });

  messagesEl.addEventListener("click", (event) => {
    const example = event.target.closest(".example");
    if (example) {
      sendMessage(example.textContent);
    }
  });

  confirmYes.addEventListener("click", () => {
    addMessage("user", "Oui, je confirme.");
    hideConfirmation();
    sendMessage("", "oui");
  });

  confirmNo.addEventListener("click", () => {
    addMessage("user", "Non, j'annule.");
    hideConfirmation();
    sendMessage("", "non");
  });

  prefsForm.addEventListener("submit", savePreferences);

  spotifyLogin.addEventListener("click", (event) => {
    if (spotifyLogin.dataset.disabled === "1") {
      event.preventDefault();
      toast("Spotify n'est pas configuré sur ce serveur.", true);
    }
  });

  spotifyImport.addEventListener("click", importSpotifyArtists);

  artistForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const nom = artistInput.value.trim();
    if (!nom) return;
    artistInput.value = "";
    addArtist(nom);
  });

  document.getElementById("clear-chat").addEventListener("click", () => {
    window.location.reload();
  });

  handleSpotifyQuery();
  loadEtat();
  loadSidebar();
  loadHistorique();
  loadSpotify();
})();
