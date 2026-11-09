"use strict";
/* ===== Pages : Accueil, Entreprises, Offres, Carte ===== */

const pages = {};   // route -> async (view, params) => void

/* ---------- Accueil ---------- */
function statCard(icon, value, label) {
  return `<div class="card stat"><div>${icon}</div><div class="num">${esc(value)}</div><div class="lbl">${esc(label)}</div></div>`;
}

pages.accueil = async (view) => {
  const [stats, opps, offers] = await Promise.all([api("/stats"), loadOpps(true), api("/offers")]);
  const top = [...opps].sort((a, b) => b.score_opportunite - a.score_opportunite).slice(0, 6);
  const empty = opps.length === 0;

  view.innerHTML = `
    <div class="page-head">
      <h1>Bonjour ${esc(state.user.username)} 👋</h1>
      <p>Retrouve les entreprises, les offres et le suivi de tes candidatures à Marrakech.</p>
    </div>
    ${empty ? `<div class="notice info">Aucune donnée pour l'instant. Va dans
      <a href="#/donnees">Collecte &amp; Import</a> pour récupérer des entreprises (Google Places ou Excel).</div>` : ""}
    <div class="grid stats">
      ${statCard("🏢", stats.total_opportunites, "Entreprises")}
      ${statCard("📄", stats.total_offres, "Offres")}
      ${statCard("🏷️", stats.total_secteurs, "Secteurs")}
      ${statCard("✉️", stats.entreprises_avec_email, "Entreprises avec e-mail")}
      ${statCard("📨", stats.cv_envoyes, "CV envoyés")}
      ${statCard("📬", stats.total_candidatures, "Candidatures suivies")}
    </div>
    <div class="grid two" style="margin-top:1.25rem">
      <section class="card">
        <h2>🏆 Meilleures opportunités</h2>
        ${top.length ? `<table><tbody>${top.map((o) => `
          <tr><td><strong>${esc(o.nom)}</strong><div class="sub">${esc(o.secteur)}</div></td>
          <td style="text-align:right">${scoreBadge(o.score_opportunite)}</td></tr>`).join("")}</tbody></table>
          <p><a href="#/entreprises">Voir toutes les entreprises →</a></p>` : `<p class="muted">—</p>`}
      </section>
      <section class="card">
        <h2>🆕 Dernières offres</h2>
        ${offers.length ? `<table><tbody>${offers.slice(0, 6).map((f) => `
          <tr><td><strong>${esc(f.titre)}</strong><div class="sub">${esc(f.entreprise || "—")} · ${esc(f.contrat)}</div></td>
          <td class="sub" style="text-align:right">${esc(fmt.day(f.date_publication))}</td></tr>`).join("")}</tbody></table>
          <p><a href="#/offres">Voir toutes les offres →</a></p>`
          : `<p class="muted">Aucune offre. Ajoute-en ou importe un fichier depuis <a href="#/donnees">Collecte &amp; Import</a>.</p>`}
      </section>
    </div>`;
};

/* ---------- Envoi du CV (modale, utilisée par Entreprises et Offres) ---------- */
function defaultCvMessage(company) {
  return `Bonjour,\n\nJe me permets de vous contacter afin de vous proposer ma candidature pour un stage au sein de ${company}.\n` +
    `Vous trouverez mon CV en pièce jointe.\n\nJe reste à votre disposition pour tout complément d'information.\n\nCordialement,\n${state.user.username}`;
}

async function openSendCvModal(o, subject = "Candidature pour un stage") {
  const meta = await loadMeta();
  const smtp = meta.smtp_configured;
  openModal(`
    <h2>✉️ Envoyer mon CV</h2>
    <div class="report" style="margin:0 0 1rem">
      <strong>${esc(o.nom)}</strong> · ${esc(o.secteur)}<br>
      Destinataire : <strong>${esc(o.email)}</strong>
    </div>
    ${smtp ? "" : `<div class="notice">L'envoi automatique n'est pas configuré sur ce serveur (SMTP).
      Tu peux ouvrir ce message dans ta messagerie et joindre ton CV toi-même.</div>`}
    <form id="cv-form">
      <label>Objet<input name="subject" required maxlength="200" value="${esc(subject)}"></label>
      <label>Ton adresse e-mail (pour que l'entreprise te réponde)
        <input type="email" name="reply_to" maxlength="254" placeholder="toi@exemple.com"
               value="${esc(localStorage.getItem("cf_reply_to") || "")}"></label>
      <label>CV (PDF, 5 Mo maximum)
        <input type="file" name="cv" accept="application/pdf,.pdf" ${smtp ? "required" : ""}></label>
      <label>Message<textarea name="message" required maxlength="5000" rows="9">${esc(defaultCvMessage(o.nom))}</textarea></label>
      <p class="error" id="cv-error" hidden></p>
      <div class="modal-actions">
        <button class="btn" type="button" data-close>Annuler</button>
        <button class="btn" type="button" data-action="cv-mailto" data-email="${esc(o.email)}">Ouvrir dans ma messagerie</button>
        <button class="btn primary" type="submit" id="cv-send" ${smtp ? "" : "disabled"}>📤 Envoyer</button>
      </div>
    </form>`);

  const form = $("#cv-form");
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const err = $("#cv-error"); err.hidden = true;
    const file = form.cv.files[0];
    if (!file) { err.textContent = "Choisis ton CV au format PDF."; err.hidden = false; return; }
    if (!/\.pdf$/i.test(file.name)) { err.textContent = "Le CV doit être un fichier PDF."; err.hidden = false; return; }
    if (file.size > 5 * 1024 * 1024) { err.textContent = "CV trop volumineux (5 Mo maximum)."; err.hidden = false; return; }

    const send = async (force) => {
      const fd = new FormData();
      fd.append("opportunity_id", o.id);
      fd.append("subject", form.subject.value);
      fd.append("message", form.message.value);
      fd.append("reply_to", form.reply_to.value);
      fd.append("force", force ? "true" : "false");
      fd.append("cv", file);
      return api("/send-cv", { method: "POST", form: fd });
    };
    const btn = $("#cv-send"); btn.disabled = true; btn.textContent = "Envoi…";
    try {
      try { await send(false); }
      catch (e) {
        if (e.status === 409 && confirm(e.message)) await send(true);
        else throw e;
      }
      if (form.reply_to.value) localStorage.setItem("cf_reply_to", form.reply_to.value);
      toast("CV envoyé à " + o.nom + " ✅", "ok");
      closeModal();
      await loadOpps(true);
      route();   // rafraîchit la page courante (badge « envoyé », candidatures…)
    } catch (e) {
      err.textContent = e.message; err.hidden = false;
      btn.disabled = false; btn.textContent = "📤 Envoyer";
    }
  });
}

actionHandlers["cv-mailto"] = (el) => {
  const f = $("#cv-form");
  const href = `mailto:${encodeURIComponent(el.dataset.email).replace(/%40/g, "@")}` +
    `?subject=${encodeURIComponent(f.subject.value)}&body=${encodeURIComponent(f.message.value)}`;
  window.location.href = href;
};

/* ---------- Entreprises ---------- */
const companyFilters = { q: "", secteur: "", minScore: 0, emailOnly: false, favOnly: false, limit: 100 };

function filteredCompanies() {
  const f = companyFilters, q = f.q.trim().toLowerCase();
  return (state.opps || [])
    .filter((o) => (!q || (o.nom || "").toLowerCase().includes(q) || (o.adresse || "").toLowerCase().includes(q))
      && (!f.secteur || o.secteur === f.secteur)
      && (o.score_opportunite || 0) >= f.minScore
      && (!f.emailOnly || (o.email || "").trim())
      && (!f.favOnly || o.favori))
    .sort((a, b) => (b.score_opportunite || 0) - (a.score_opportunite || 0));
}

function companyRow(o) {
  const site = safeUrl(o.site_web), maps = safeUrl(o.google_maps_url);
  const tel = (o.telephone || "").trim();
  const email = (o.email || "").trim();
  return `<tr>
    <td><button class="star ${o.favori ? "on" : ""}" data-action="fav" data-id="${o.id}" title="Favori" aria-label="Favori">★</button></td>
    <td><strong>${esc(o.nom)}</strong><div class="sub">${esc(o.adresse || "")}</div>
        <span class="chip gray">${esc(o.secteur)}</span></td>
    <td>${scoreBadge(o.score_opportunite)}${o.note ? `<div class="sub">⭐ ${esc(o.note)}</div>` : ""}</td>
    <td>${tel ? `<a href="tel:${esc(tel.replace(/[^\d+]/g, ""))}">${esc(tel)}</a>` : "—"}</td>
    <td>${email ? `<a href="mailto:${esc(email)}">${esc(email)}</a>` : "—"}
        ${o.cv_envoye_le ? `<div><span class="chip ok">CV envoyé le ${fmt.ts(o.cv_envoye_le)}</span></div>` : ""}</td>
    <td>${site ? `<a href="${esc(site)}" target="_blank" rel="noopener noreferrer">🌐 Site</a>` : ""}
        ${maps ? `<a href="${esc(maps)}" target="_blank" rel="noopener noreferrer">📍 Maps</a>` : ""}</td>
    <td><div class="actions">
      <button class="btn small primary" data-action="send-cv" data-id="${o.id}" ${email ? "" : "disabled"}
        title="${email ? "Envoyer mon CV" : "Pas d'e-mail enregistré"}">✉️ CV</button>
      <button class="btn small" data-action="track" data-id="${o.id}">📋 Suivre</button>
      ${canEdit(o) ? `<button class="btn small" data-action="edit-company" data-id="${o.id}" title="Modifier">✏️</button>
      <button class="btn small danger" data-action="del-company" data-id="${o.id}" title="Supprimer">🗑</button>` : ""}
    </div></td></tr>`;
}

function renderCompanyRows() {
  const list = filteredCompanies();
  const shown = list.slice(0, companyFilters.limit);
  $("#company-count").textContent = `${list.length} entreprise(s) trouvée(s)`;
  $("#company-rows").innerHTML = shown.length ? shown.map(companyRow).join("")
    : `<tr><td colspan="7" class="empty">Aucune entreprise ne correspond aux filtres.</td></tr>`;
  $("#company-more").hidden = list.length <= shown.length;
}

pages.entreprises = async (view) => {
  const [meta] = await Promise.all([loadMeta(), loadOpps(true)]);
  const f = companyFilters;
  view.innerHTML = `
    <div class="page-head"><h1>🏢 Entreprises</h1><p>Entreprises IA &amp; IT de Marrakech, classées par score d'opportunité.</p></div>
    <div class="card toolbar">
      <label>Recherche<input id="f-q" type="search" placeholder="Nom ou adresse…" value="${esc(f.q)}"></label>
      <label>Secteur<select id="f-secteur">${options(meta.secteurs, f.secteur, "Tous les secteurs")}</select></label>
      <label>Score minimum : <span id="f-score-val">${f.minScore}</span>
        <input id="f-score" type="range" min="0" max="100" step="5" value="${f.minScore}"></label>
      <label class="inline"><input id="f-email" type="checkbox" ${f.emailOnly ? "checked" : ""}>Avec e-mail</label>
      <label class="inline"><input id="f-fav" type="checkbox" ${f.favOnly ? "checked" : ""}>Favoris</label>
    </div>
    <p id="company-count" class="muted"></p>
    <div class="table-wrap"><table>
      <thead><tr><th></th><th>Entreprise</th><th>Score</th><th>Téléphone</th><th>E-mail</th><th>Liens</th><th>Actions</th></tr></thead>
      <tbody id="company-rows"></tbody>
    </table></div>
    <p style="text-align:center"><button id="company-more" class="btn" data-action="more-companies" hidden>Afficher plus</button></p>`;

  const bind = (sel, ev, fn) => $(sel).addEventListener(ev, () => { fn(); f.limit = 100; renderCompanyRows(); });
  bind("#f-q", "input", () => { f.q = $("#f-q").value; });
  bind("#f-secteur", "change", () => { f.secteur = $("#f-secteur").value; });
  bind("#f-score", "input", () => { f.minScore = Number($("#f-score").value); $("#f-score-val").textContent = f.minScore; });
  bind("#f-email", "change", () => { f.emailOnly = $("#f-email").checked; });
  bind("#f-fav", "change", () => { f.favOnly = $("#f-fav").checked; });
  renderCompanyRows();
};

const findOpp = (id) => (state.opps || []).find((o) => o.id === Number(id));

actionHandlers["more-companies"] = () => { companyFilters.limit += 100; renderCompanyRows(); };

actionHandlers["fav"] = async (el) => {
  try {
    const r = await api(`/opportunities/${el.dataset.id}/favorite`, { method: "PATCH" });
    const o = findOpp(el.dataset.id); if (o) o.favori = r.favori ? 1 : 0;
    if (companyFilters.favOnly) renderCompanyRows(); else el.classList.toggle("on", r.favori);
  } catch (e) { toast(e.message, "error"); }
};

actionHandlers["send-cv"] = (el) => {
  const o = findOpp(el.dataset.id);
  if (o) openSendCvModal(o);
};

actionHandlers["track"] = async (el) => {
  const o = findOpp(el.dataset.id); if (!o) return;
  const meta = await loadMeta();
  openModal(`
    <h2>📋 Suivre une candidature</h2>
    <p class="muted">${esc(o.nom)}</p>
    <form id="track-form">
      <label>Poste visé<input name="poste" required value="Stage"></label>
      <label>Statut<select name="statut">${options(meta.statuts, "À contacter")}</select></label>
      <label>Date<input type="date" name="date" value="${new Date().toISOString().slice(0, 10)}"></label>
      <label>Remarque<textarea name="remarque" rows="3"></textarea></label>
      <p class="error" id="track-error" hidden></p>
      <div class="modal-actions"><button class="btn" type="button" data-close>Annuler</button>
        <button class="btn primary" type="submit">Enregistrer</button></div>
    </form>`);
  $("#track-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const f = ev.target;
    try {
      await api("/applications", { method: "POST", json: {
        company: o.nom, poste: f.poste.value, statut: f.statut.value,
        date_candidature: f.date.value, remarque: f.remarque.value, opportunity_id: o.id } });
      toast("Candidature ajoutée au suivi ✅", "ok"); closeModal();
    } catch (e) { const er = $("#track-error"); er.textContent = e.message; er.hidden = false; }
  });
};

actionHandlers["edit-company"] = async (el) => {
  const o = findOpp(el.dataset.id); if (!o) return;
  const meta = await loadMeta();
  openModal(`
    <h2>✏️ Modifier l'entreprise</h2>
    <p class="muted">${esc(o.nom)}</p>
    <form id="edit-form">
      <label>E-mail de contact<input type="email" name="email" maxlength="254" value="${esc(o.email || "")}"></label>
      <label>Téléphone<input name="telephone" maxlength="40" value="${esc(o.telephone || "")}"></label>
      <label>Site web<input name="site_web" maxlength="300" value="${esc(o.site_web || "")}"></label>
      <label>Adresse<input name="adresse" maxlength="300" value="${esc(o.adresse || "")}"></label>
      <label>Secteur<select name="secteur">${options(meta.secteurs, o.secteur)}</select></label>
      <p class="error" id="edit-error" hidden></p>
      <div class="modal-actions"><button class="btn" type="button" data-close>Annuler</button>
        <button class="btn primary" type="submit">Enregistrer</button></div>
    </form>`);
  $("#edit-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const f = ev.target;
    try {
      await api(`/opportunities/${o.id}`, { method: "PATCH", json: {
        email: f.email.value, telephone: f.telephone.value, site_web: f.site_web.value,
        adresse: f.adresse.value, secteur: f.secteur.value } });
      toast("Entreprise mise à jour ✅", "ok"); closeModal();
      await loadOpps(true); renderCompanyRows();
    } catch (e) { const er = $("#edit-error"); er.textContent = e.message; er.hidden = false; }
  });
};

actionHandlers["del-company"] = async (el) => {
  const o = findOpp(el.dataset.id); if (!o) return;
  if (!confirm(`Supprimer « ${o.nom} » du catalogue ?`)) return;
  try {
    await api(`/opportunities/${o.id}`, { method: "DELETE" });
    toast("Entreprise supprimée"); await loadOpps(true); renderCompanyRows();
  } catch (e) { toast(e.message, "error"); }
};

/* ---------- Offres ---------- */
const offerFilters = { q: "", contrat: "", type_stage: "" };

function offerCard(f) {
  const url = safeUrl(f.url);
  const company = f.opportunity_id ? findOpp(f.opportunity_id) : null;
  const canSend = company && (company.email || "").trim();
  return `<article class="card offer">
    <h3>${esc(f.titre)}</h3>
    <dl>
      <dt>🏢 Entreprise</dt><dd>${esc(f.entreprise || "Non renseignée")}</dd>
      <dt>📋 Contrat</dt><dd><span class="chip">${esc(f.contrat)}</span></dd>
      <dt>🎓 Stage</dt><dd>${esc(f.type_stage)}</dd>
      <dt>📍 Ville</dt><dd>${esc(f.ville || "—")}</dd>
      <dt>📅 Publication</dt><dd>${esc(fmt.day(f.date_publication) || "—")}</dd>
    </dl>
    ${f.description ? `<p class="muted">${esc(f.description.length > 180 ? f.description.slice(0, 180) + "…" : f.description)}</p>` : ""}
    <div class="actions">
      ${url ? `<a class="btn small" href="${esc(url)}" target="_blank" rel="noopener noreferrer">🔗 Voir l'offre</a>` : ""}
      ${canSend ? `<button class="btn small primary" data-action="offer-cv" data-id="${f.id}">✉️ Envoyer mon CV</button>` : ""}
      ${canEdit(f) ? `<button class="btn small danger" data-action="del-offer" data-id="${f.id}" title="Supprimer">🗑</button>` : ""}
    </div></article>`;
}

let currentOffers = [];

async function refreshOffers() {
  try {
    currentOffers = await api("/offers", { params: offerFilters });
    $("#offer-count").textContent = `${currentOffers.length} offre(s) trouvée(s)`;
    $("#offer-grid").innerHTML = currentOffers.length ? currentOffers.map(offerCard).join("")
      : `<div class="empty card" style="grid-column:1/-1">Aucune offre. Ajoute-en une ou importe un fichier depuis
         <a href="#/donnees">Collecte &amp; Import</a>.</div>`;
  } catch (e) { toast(e.message, "error"); }
}

pages.offres = async (view) => {
  const [meta] = await Promise.all([loadMeta(), loadOpps()]);
  const f = offerFilters;
  view.innerHTML = `
    <div class="page-head"><h1>📄 Offres de stage et d'emploi</h1><p>Opportunités professionnelles à Marrakech.</p></div>
    <div class="card toolbar">
      <label>Recherche<input id="o-q" type="search" placeholder="Titre, entreprise…" value="${esc(f.q)}"></label>
      <label>Type de stage<select id="o-type">${options(meta.types_stage, f.type_stage, "Tous les types")}</select></label>
      <label>Contrat<select id="o-contrat">${options(meta.contrats, f.contrat, "Tous les contrats")}</select></label>
      <button class="btn primary" data-action="add-offer">➕ Ajouter une offre</button>
    </div>
    <p id="offer-count" class="muted"></p>
    <div id="offer-grid" class="grid cards"></div>`;
  $("#o-q").addEventListener("input", debounce(() => { f.q = $("#o-q").value.trim(); refreshOffers(); }));
  $("#o-type").addEventListener("change", () => { f.type_stage = $("#o-type").value; refreshOffers(); });
  $("#o-contrat").addEventListener("change", () => { f.contrat = $("#o-contrat").value; refreshOffers(); });
  await refreshOffers();
};

actionHandlers["offer-cv"] = (el) => {
  const offer = currentOffers.find((x) => x.id === Number(el.dataset.id));
  const company = offer && findOpp(offer.opportunity_id);
  if (company) openSendCvModal(company, `Candidature : ${offer.titre}`);
};

actionHandlers["del-offer"] = async (el) => {
  if (!confirm("Supprimer cette offre ?")) return;
  try { await api(`/offers/${el.dataset.id}`, { method: "DELETE" }); toast("Offre supprimée"); refreshOffers(); }
  catch (e) { toast(e.message, "error"); }
};

actionHandlers["add-offer"] = async () => {
  const meta = await loadMeta(); const opps = await loadOpps();
  openModal(`
    <h2>➕ Ajouter une offre</h2>
    <form id="offer-form">
      <label>Titre *<input name="titre" required maxlength="200"></label>
      <label>Entreprise<input name="entreprise" list="company-list" maxlength="200" placeholder="Choisis ou saisis un nom">
        <datalist id="company-list">${opps.map((o) => `<option value="${esc(o.nom)}">`).join("")}</datalist></label>
      <div class="grid two" style="gap:.5rem">
        <label>Contrat<select name="contrat">${options(meta.contrats, "Stage")}</select></label>
        <label>Type de stage<select name="type_stage">${options(meta.types_stage, "Non renseigné")}</select></label>
        <label>Ville<input name="ville" value="Marrakech" maxlength="80"></label>
        <label>Date de publication<input type="date" name="date_publication" value="${new Date().toISOString().slice(0, 10)}"></label>
      </div>
      <label>Lien de l'offre<input name="url" type="url" placeholder="https://…"></label>
      <label>Description<textarea name="description" rows="3" maxlength="3000"></textarea></label>
      <p class="error" id="offer-error" hidden></p>
      <div class="modal-actions"><button class="btn" type="button" data-close>Annuler</button>
        <button class="btn primary" type="submit">Enregistrer</button></div>
    </form>`);
  $("#offer-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const f = ev.target;
    const match = opps.find((o) => o.nom.toLowerCase() === f.entreprise.value.trim().toLowerCase());
    try {
      await api("/offers", { method: "POST", json: {
        titre: f.titre.value, entreprise: f.entreprise.value, opportunity_id: match ? match.id : null,
        contrat: f.contrat.value, type_stage: f.type_stage.value, ville: f.ville.value,
        date_publication: f.date_publication.value, url: f.url.value, description: f.description.value } });
      toast("Offre ajoutée ✅", "ok"); closeModal(); refreshOffers();
    } catch (e) { const er = $("#offer-error"); er.textContent = e.message; er.hidden = false; }
  });
};

/* ---------- Carte Google Maps ---------- */
let mapsPromise = null;
function loadGoogleMaps(key) {
  if (window.google && window.google.maps) return Promise.resolve();
  if (mapsPromise) return mapsPromise;
  mapsPromise = new Promise((resolve, reject) => {
    window.__mapsReady = resolve;
    window.gm_authFailure = () => toast("Clé Google Maps refusée : vérifie-la dans la console Google Cloud.", "error");
    const s = document.createElement("script");
    s.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(key)}&callback=__mapsReady`;
    s.async = true;
    s.onerror = () => { mapsPromise = null; reject(new Error("Impossible de charger Google Maps.")); };
    document.head.appendChild(s);
  });
  return mapsPromise;
}

pages.carte = async (view) => {
  const [meta, opps] = await Promise.all([loadMeta(), loadOpps(true)]);
  view.innerHTML = `
    <div class="page-head"><h1>🗺️ Carte</h1><p>Localisation des entreprises collectées.</p></div>
    <div class="card toolbar">
      <label>Secteur<select id="m-secteur">${options(meta.secteurs, "", "Tous les secteurs")}</select></label>
      <label>Score minimum : <span id="m-score-val">0</span><input id="m-score" type="range" min="0" max="100" step="5" value="0"></label>
      <span id="m-count" class="muted"></span>
    </div>
    <div id="map-msg"></div><div id="map"></div>`;

  let key = sessionStorage.getItem("cf_gmaps_key") || "";
  try { if (!key) key = (await api("/maps-key")).api_key || ""; } catch { /* géré ci-dessous */ }
  if (!key) {
    $("#map").hidden = true;
    $("#map-msg").innerHTML = `<div class="notice">Aucune clé Google Maps. Renseigne <code>GOOGLE_MAPS_API_KEY</code> dans
      le fichier <code>.env</code> du serveur, ou saisis une clé pour cette session dans
      <a href="#/donnees">Collecte &amp; Import</a>.</div>`;
    return;
  }
  try { await loadGoogleMaps(key); } catch (e) { $("#map-msg").innerHTML = `<div class="notice">${esc(e.message)}</div>`; return; }

  const map = new google.maps.Map($("#map"), { center: { lat: 31.6295, lng: -7.9811 }, zoom: 12 });
  const info = new google.maps.InfoWindow();
  let markers = [];

  const draw = () => {
    markers.forEach((m) => m.setMap(null)); markers = [];
    const sec = $("#m-secteur").value, min = Number($("#m-score").value);
    $("#m-score-val").textContent = min;
    const pts = opps.filter((o) => typeof o.latitude === "number" && typeof o.longitude === "number"
      && (!sec || o.secteur === sec) && (o.score_opportunite || 0) >= min);
    const bounds = new google.maps.LatLngBounds();
    pts.forEach((o) => {
      const pos = { lat: o.latitude, lng: o.longitude };
      const m = new google.maps.Marker({ position: pos, map, title: o.nom });
      m.addListener("click", () => {
        const site = safeUrl(o.site_web);
        info.setContent(`<div style="max-width:220px;color:#0f172a"><strong>${esc(o.nom)}</strong><br>
          ${esc(o.secteur)} · score ${esc(o.score_opportunite)}<br>${esc(o.adresse || "")}
          ${o.email ? `<br>✉️ ${esc(o.email)}` : ""}
          ${site ? `<br><a href="${esc(site)}" target="_blank" rel="noopener noreferrer">Site web</a>` : ""}</div>`);
        info.open(map, m);
      });
      markers.push(m); bounds.extend(pos);
    });
    $("#m-count").textContent = `${pts.length} entreprise(s) affichée(s)`;
    if (pts.length > 1) map.fitBounds(bounds);
  };
  $("#m-secteur").addEventListener("change", draw);
  $("#m-score").addEventListener("input", draw);
  draw();
};
