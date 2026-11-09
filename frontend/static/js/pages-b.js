"use strict";
/* ===== Pages : Candidatures, Statistiques, Profil & Matching, Collecte & Import ===== */

/* ---------- Candidatures ---------- */
pages.candidatures = async (view) => {
  const [meta, apps, opps] = await Promise.all([loadMeta(), api("/applications"), loadOpps()]);
  const today = new Date().toISOString().slice(0, 10);

  const col = (statut) => {
    const items = apps.filter((a) => a.statut === statut);
    return `<div class="col"><h3>${esc(statut)} <span class="chip gray">${items.length}</span></h3>
      ${items.map((a) => `<div class="kcard">
        <strong>${esc(a.company)}</strong><div class="sub">${esc(a.poste || "")}${a.date_candidature ? " · " + esc(fmt.day(a.date_candidature)) : ""}</div>
        ${a.remarque ? `<div class="sub">${esc(a.remarque)}</div>` : ""}
        <select data-app-id="${a.id}" aria-label="Changer le statut">${options(meta.statuts, a.statut)}</select>
        <button class="btn small danger" data-action="del-app" data-id="${a.id}">🗑 Supprimer</button>
      </div>`).join("")}</div>`;
  };

  view.innerHTML = `
    <div class="page-head"><h1>📬 Suivi des candidatures</h1><p>Ajoute et suis tes candidatures auprès des entreprises.</p></div>
    <section class="card" style="margin-bottom:1.25rem">
      <h2>➕ Ajouter une candidature</h2>
      <form id="app-form" class="grid two" style="gap:.25rem 1rem">
        <label>Entreprise *<input name="company" required list="app-companies" maxlength="200" placeholder="Nom de l'entreprise">
          <datalist id="app-companies">${opps.map((o) => `<option value="${esc(o.nom)}">`).join("")}</datalist></label>
        <label>Poste *<input name="poste" required maxlength="200" value="Stage"></label>
        <label>Date<input type="date" name="date" value="${today}"></label>
        <label>Statut<select name="statut">${options(meta.statuts, "À contacter")}</select></label>
        <label style="grid-column:1/-1">Commentaire<textarea name="remarque" rows="2" placeholder="Ex : CV envoyé par e-mail…"></textarea></label>
        <p class="error" id="app-error" hidden style="grid-column:1/-1"></p>
        <div style="grid-column:1/-1"><button class="btn primary" type="submit">💾 Enregistrer la candidature</button></div>
      </form>
    </section>
    ${apps.length ? "" : `<p class="muted">Aucune candidature pour l'instant.</p>`}
    <div class="kanban">${meta.statuts.map(col).join("")}</div>`;

  $("#app-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const f = ev.target;
    const match = opps.find((o) => o.nom.toLowerCase() === f.company.value.trim().toLowerCase());
    try {
      await api("/applications", { method: "POST", json: {
        company: f.company.value.trim(), poste: f.poste.value.trim(), statut: f.statut.value,
        date_candidature: f.date.value, remarque: f.remarque.value, opportunity_id: match ? match.id : null } });
      toast("Candidature enregistrée ✅", "ok"); route();
    } catch (e) { const er = $("#app-error"); er.textContent = e.message; er.hidden = false; }
  });
};

document.addEventListener("change", async (ev) => {
  const sel = ev.target.closest("select[data-app-id]");
  if (!sel) return;
  try {
    await api(`/applications/${sel.dataset.appId}`, { method: "PATCH", json: { statut: sel.value } });
    toast("Statut mis à jour", "ok"); route();
  } catch (e) { toast(e.message, "error"); }
});

actionHandlers["del-app"] = async (el) => {
  if (!confirm("Supprimer cette candidature ?")) return;
  try { await api(`/applications/${el.dataset.id}`, { method: "DELETE" }); toast("Candidature supprimée"); route(); }
  catch (e) { toast(e.message, "error"); }
};

/* ---------- Statistiques ---------- */
const PALETTE = ["#0d9488", "#f59e0b", "#6366f1", "#ec4899", "#22c55e", "#0ea5e9", "#ef4444", "#a855f7", "#14b8a6", "#eab308", "#64748b"];

function chartCard(title, id, data) {
  const has = Object.values(data || {}).some((v) => v > 0);
  return `<section class="card"><h2>${title}</h2>${has
    ? `<div class="chart-box"><canvas id="${id}"></canvas></div>`
    : `<p class="empty">Pas encore de données.</p>`}</section>`;
}

function makeChart(id, type, data, opts = {}) {
  const el = document.getElementById(id);
  if (!el) return;
  const labels = Object.keys(data), values = Object.values(data);
  const circular = type === "doughnut" || type === "pie";
  state.charts.push(new Chart(el, {
    type,
    data: { labels, datasets: [{ data: values, backgroundColor: circular ? PALETTE : PALETTE[0], borderWidth: 0, borderRadius: circular ? 0 : 6 }] },
    options: {
      maintainAspectRatio: false, indexAxis: opts.horizontal ? "y" : "x",
      plugins: { legend: { display: circular, position: "bottom" } },
      scales: circular ? {} : { [opts.horizontal ? "x" : "y"]: { beginAtZero: true, ticks: { precision: 0 } } },
    },
  }));
}

pages.statistiques = async (view) => {
  const [s, meta] = await Promise.all([api("/stats"), loadMeta()]);
  const secteurs = Object.fromEntries(Object.entries(s.par_secteur).sort((a, b) => b[1] - a[1]));
  const presence = {
    "Avec e-mail": s.presence_numerique.avec_email, "Sans e-mail": s.presence_numerique.sans_email,
    "Avec site web": s.presence_numerique.avec_site_web, "Sans site web": s.presence_numerique.sans_site_web,
  };
  const statuts = Object.fromEntries(meta.statuts.map((k) => [k, s.candidatures_par_statut[k] || 0]));

  view.innerHTML = `
    <div class="page-head"><h1>📊 Statistiques</h1><p>Analyse des entreprises, des offres et de ta recherche.</p></div>
    <div class="grid stats" style="margin-bottom:1.25rem">
      ${statCard("🏢", s.total_opportunites, "Entreprises")}${statCard("📄", s.total_offres, "Offres")}
      ${statCard("🏷️", s.total_secteurs, "Secteurs")}${statCard("✉️", s.entreprises_avec_email, "Avec e-mail")}
      ${statCard("📨", s.cv_envoyes, "CV envoyés")}${statCard("⭐", s.favoris, "Favoris")}
    </div>
    ${window.Chart ? "" : `<div class="notice">Les graphiques n'ont pas pu être chargés (connexion à cdnjs.cloudflare.com bloquée ?).</div>`}
    <div class="grid two">
      ${chartCard("🏢 Entreprises par secteur", "ch-secteur", secteurs)}
      ${chartCard("🎓 Offres par type de stage", "ch-stage", s.offres_par_type_stage)}
      ${chartCard("📋 Offres par type de contrat", "ch-contrat", s.offres_par_contrat)}
      ${chartCard("🌐 Présence numérique des entreprises", "ch-presence", presence)}
      ${chartCard("📬 Candidatures par statut", "ch-statut", statuts)}
    </div>`;

  if (!window.Chart) return;
  Chart.defaults.color = getComputedStyle(document.documentElement).getPropertyValue("--muted").trim() || "#64748b";
  makeChart("ch-secteur", "bar", secteurs);
  makeChart("ch-stage", "doughnut", s.offres_par_type_stage);
  makeChart("ch-contrat", "bar", s.offres_par_contrat);
  makeChart("ch-presence", "bar", presence, { horizontal: true });
  makeChart("ch-statut", "bar", statuts);
};

/* ---------- Profil & Matching ---------- */
async function runMatching() {
  const min = Number($("#match-min").value);
  $("#match-min-val").textContent = min;
  const box = $("#match-results");
  box.innerHTML = `<p class="loading">Calcul…</p>`;
  try {
    const rows = await api("/matching", { params: { min_score: min } });
    await loadOpps();
    box.innerHTML = rows.length ? `<div class="table-wrap"><table>
      <thead><tr><th>Entreprise</th><th>Match</th><th>Score d'opportunité</th><th>Mots-clés</th><th></th></tr></thead><tbody>
      ${rows.slice(0, 40).map((o) => `<tr>
        <td><strong>${esc(o.nom)}</strong><div class="sub">${esc(o.secteur)} · ${esc(o.adresse || "")}</div></td>
        <td>${scoreBadge(o.match_score)}</td><td>${scoreBadge(o.score_opportunite)}</td>
        <td class="sub">${esc(o.mots_cles || "—")}</td>
        <td><button class="btn small primary" data-action="send-cv" data-id="${o.id}" ${(o.email || "").trim() ? "" : "disabled"}>✉️ CV</button></td></tr>`).join("")}
      </tbody></table></div><p class="muted">${rows.length} résultat(s), 40 affichés au maximum.</p>`
      : `<p class="empty card">Aucune entreprise ne dépasse ce seuil. Complète tes compétences ou baisse le seuil.</p>`;
  } catch (e) { box.innerHTML = `<p class="error">${esc(e.message)}</p>`; }
}

pages.profil = async (view) => {
  const profile = await api("/profile");
  view.innerHTML = `
    <div class="page-head"><h1>🎯 Profil &amp; Matching</h1>
      <p>Renseigne tes compétences pour voir les entreprises qui te correspondent le mieux.</p></div>
    <section class="card" style="margin-bottom:1.25rem">
      <form id="profile-form">
        <label>Compétences (séparées par des virgules)
          <textarea name="skills" rows="3" placeholder="python, machine learning, data, cloud">${esc(profile.skills || "")}</textarea></label>
        <div class="grid two" style="gap:.5rem 1rem">
          <label>Années d'expérience<input type="number" name="experience_years" min="0" max="50" step="0.5" value="${esc(profile.experience_years || 0)}"></label>
          <label>Courte présentation<input name="bio" maxlength="500" value="${esc(profile.bio || "")}"></label>
        </div>
        <button class="btn primary" type="submit">💾 Enregistrer mon profil</button>
      </form>
    </section>
    <section>
      <h2>🤖 Entreprises recommandées</h2>
      <p class="muted">Indicatif : 60 % de compétences en commun avec les mots-clés de l'entreprise (surtout tirés de son nom),
        40 % du score d'opportunité.</p>
      <label>Match minimum : <span id="match-min-val">20</span>
        <input id="match-min" type="range" min="0" max="100" step="5" value="20" style="max-width:340px"></label>
      <div id="match-results"></div>
    </section>`;

  $("#profile-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const f = ev.target;
    try {
      await api("/profile", { method: "POST", json: {
        skills: f.skills.value, experience_years: Number(f.experience_years.value) || 0,
        bio: f.bio.value, cv_filename: profile.cv_filename || "" } });
      toast("Profil enregistré ✅", "ok"); runMatching();
    } catch (e) { toast(e.message, "error"); }
  });
  $("#match-min").addEventListener("change", runMatching);
  $("#match-min").addEventListener("input", () => { $("#match-min-val").textContent = $("#match-min").value; });
  runMatching();
};

/* ---------- Collecte & Import ---------- */
const EXTRA_QUERIES = ["entreprise informatique", "société IT", "startup tech", "data science",
  "développement logiciel", "cloud computing", "cybersécurité", "agence digitale"];

function reportHtml(report) {
  const labels = {
    lignes_lues: "Lignes lues", sans_nom_supprimees: "Sans nom (supprimées)", fermees_supprimees: "Fiches fermées (supprimées)",
    doublons_supprimes: "Doublons (supprimés)", hors_secteur_supprimees: "Hors secteur IT/IA (supprimées)",
    lignes_conservees: "Lignes conservées", opportunites_ajoutees: "Entreprises ajoutées / mises à jour",
    ajoutees: "Offres ajoutées", ignorees: "Offres ignorées (doublons ou titre vide)",
  };
  return `<div class="report">${Object.entries(report).map(([k, v]) => `${esc(labels[k] || k)} : <strong>${esc(v)}</strong>`).join("<br>")}</div>`;
}

pages.donnees = async (view) => {
  const meta = await loadMeta();
  view.innerHTML = `
    <div class="page-head"><h1>⚙️ Collecte &amp; Import</h1><p>Alimente l'application en entreprises et en offres.</p></div>
    <div class="grid two">

      <section class="card">
        <h2>🔄 Collecte Google Places</h2>
        <form id="collect-form">
          <label>Requête<input name="query" value="Intelligence Artificielle OR Informatique"></label>
          <label>Coordonnées (lat,lng)<input name="location" value="31.6295,-7.9811"></label>
          <label>Rayon : <span id="radius-val">15</span> km<input name="radius" type="range" min="1000" max="50000" step="1000" value="15000"></label>
          <label class="inline"><input name="wide" type="checkbox">Recherche élargie (plusieurs requêtes IT/IA)</label>
          <label>Clé API Google (optionnel, cette session uniquement)
            <input name="apikey" type="password" autocomplete="off" placeholder="Remplace la clé du serveur"
                   value="${esc(sessionStorage.getItem("cf_gmaps_key") || "")}"></label>
          <button class="btn primary" type="submit" id="collect-btn">Collecter</button>
          <div id="collect-out"></div>
        </form>
      </section>

      <section class="card">
        <h2>📂 Importer des entreprises (Excel)</h2>
        <p class="muted">Colonnes : <code>entreprise</code> (obligatoire), type, secteur, adresse, lat, lon, note, site_web,
          telephone, <code>email</code>, statut_google.</p>
        <form id="excel-form">
          <label>Fichier .xlsx<input type="file" name="file" accept=".xlsx,.xls" required></label>
          <label class="inline"><input type="checkbox" name="only" checked>Garder uniquement Informatique / IA</label>
          <button class="btn primary" type="submit">Importer</button>
          <div id="excel-out"></div>
        </form>
      </section>

      <section class="card">
        <h2>📄 Importer des offres (Excel ou CSV)</h2>
        <p class="muted">Colonnes reconnues : <code>titre</code> (obligatoire), entreprise, contrat, type de stage,
          ville, date de publication, lien, description.</p>
        <form id="offers-form">
          <label>Fichier .xlsx ou .csv<input type="file" name="file" accept=".xlsx,.xls,.csv" required></label>
          <button class="btn primary" type="submit">Importer</button>
          <div id="offers-out"></div>
        </form>
      </section>

      <section class="card">
        <h2>➕ Ajouter une entreprise</h2>
        <form id="manual-form" class="grid two" style="gap:0 .75rem">
          <label style="grid-column:1/-1">Nom *<input name="nom" required maxlength="200"></label>
          <label>Secteur<select name="secteur">${options(meta.secteurs, "", "Détection automatique")}</select></label>
          <label>E-mail<input type="email" name="email" maxlength="254"></label>
          <label>Téléphone<input name="telephone" maxlength="40"></label>
          <label>Site web<input name="site_web" maxlength="300"></label>
          <label style="grid-column:1/-1">Adresse<input name="adresse" maxlength="300"></label>
          <label>Latitude<input name="lat" type="number" step="any"></label>
          <label>Longitude<input name="lng" type="number" step="any"></label>
          <label>Score (0-100)<input name="score" type="number" min="0" max="100" value="50"></label>
          <p class="error" id="manual-error" hidden style="grid-column:1/-1"></p>
          <div style="grid-column:1/-1"><button class="btn primary" type="submit">Ajouter</button></div>
        </form>
      </section>

      <section class="card">
        <h2>📥 Exports</h2>
        <p class="muted">Tes données (favoris, candidatures) au format tableur.</p>
        <div class="actions">
          <button class="btn" data-action="export" data-path="/export/complet" data-file="resultats_analyse_et_suivi.xlsx">Export complet (.xlsx)</button>
          <button class="btn" data-action="export" data-path="/export/avant-apres" data-file="donnees_avant_apres.xlsx">Avant / après nettoyage (.xlsx)</button>
          <button class="btn" data-action="export" data-path="/opportunities/export" data-file="opportunites.csv">Entreprises (.csv)</button>
        </div>
      </section>
    </div>`;

  const out = (id, html) => { $(id).innerHTML = html; };
  const radius = $("#collect-form").radius;
  radius.addEventListener("input", () => { $("#radius-val").textContent = Math.round(radius.value / 1000); });

  $("#collect-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const f = ev.target, btn = $("#collect-btn");
    const key = f.apikey.value.trim();
    if (key) sessionStorage.setItem("cf_gmaps_key", key); else sessionStorage.removeItem("cf_gmaps_key");
    const queries = f.wide.checked ? [f.query.value, ...EXTRA_QUERIES] : [f.query.value];
    btn.disabled = true; let total = 0, errors = [];
    for (let i = 0; i < queries.length; i++) {
      out("#collect-out", `<p class="muted">« ${esc(queries[i])} » (${i + 1}/${queries.length})…</p>`);
      try {
        const r = await api("/opportunities/refresh", { method: "POST",
          params: { query: queries[i], location: f.location.value, radius: f.radius.value },
          headers: key ? { "X-Google-Api-Key": key } : {} });
        total += r.count || 0;
      } catch (e) { errors.push(`« ${queries[i]} » : ${e.message}`); if (e.status === 401) break; }
    }
    btn.disabled = false; state.opps = null;
    out("#collect-out", `<div class="report">${total} entreprise(s) collectée(s) ou mise(s) à jour.
      ${errors.length ? `<br><span class="error">${errors.map(esc).join("<br>")}</span>` : ""}</div>`);
    if (total) toast(`${total} entreprise(s) collectée(s) ✅`, "ok");
  });

  const uploader = (formId, outId, path, extra) => $(formId).addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const f = ev.target, file = f.file.files[0];
    if (!file) return;
    const fd = new FormData(); fd.append("file", file);
    const btn = f.querySelector("button[type=submit]"); btn.disabled = true;
    try {
      const r = await api(path, { method: "POST", form: fd, params: extra ? extra(f) : undefined });
      out(outId, reportHtml(r.report)); state.opps = null; toast("Import terminé ✅", "ok");
    } catch (e) { out(outId, `<p class="error">${esc(e.message)}</p>`); }
    btn.disabled = false;
  });
  uploader("#excel-form", "#excel-out", "/opportunities/import-excel", (f) => ({ only_it_ai: f.only.checked }));
  uploader("#offers-form", "#offers-out", "/offers/import");

  $("#manual-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const f = ev.target, num = (v) => (v === "" ? null : Number(v));
    try {
      await api("/opportunities/manual", { method: "POST", json: {
        nom: f.nom.value, secteur: f.secteur.value, email: f.email.value, telephone: f.telephone.value,
        site_web: f.site_web.value, adresse: f.adresse.value, latitude: num(f.lat.value), longitude: num(f.lng.value),
        score_opportunite: Number(f.score.value) || 0 } });
      toast("Entreprise ajoutée ✅", "ok"); f.reset(); state.opps = null; $("#manual-error").hidden = true;
    } catch (e) { const er = $("#manual-error"); er.textContent = e.message; er.hidden = false; }
  });
};

actionHandlers["export"] = (el) => downloadFile(el.dataset.path, el.dataset.file);
