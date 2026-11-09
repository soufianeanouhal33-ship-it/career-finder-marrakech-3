"use strict";
/* ===== Noyau : état, API, utilitaires, modales ===== */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

// Échappement HTML : TOUTE donnée issue de l'API (noms Google, Excel, saisies) passe par esc().
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// URL http(s) uniquement (bloque javascript:, data:…). Ajoute https:// si le schéma manque.
function safeUrl(u) {
  u = String(u ?? "").trim();
  if (!u) return "";
  if (/^https?:\/\//i.test(u)) return u;
  if (/^[\w-]+(\.[\w-]+)+(\/.*)?$/.test(u)) return "https://" + u;
  return "";
}

const state = {
  token: localStorage.getItem("cf_token"),
  user: JSON.parse(localStorage.getItem("cf_user") || "null"),
  meta: null,
  opps: null,        // cache des entreprises (rechargé après chaque modification)
  charts: [],
};

/* ---------- API ---------- */
class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

function errorText(data, fallback) {
  const d = data && data.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) {   // erreurs de validation FastAPI/Pydantic
    return d.map((e) => String(e.msg || "").replace(/^Value error, /, "")).filter(Boolean).join(" · ") || fallback;
  }
  return fallback;
}

async function api(path, { method = "GET", params, json, form, headers = {}, blob = false } = {}) {
  let url = "/api" + path;
  if (params) {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "") qs.set(k, v); });
    if ([...qs].length) url += "?" + qs.toString();
  }
  const opts = { method, headers: { ...headers } };
  if (state.token) opts.headers.Authorization = "Bearer " + state.token;
  if (json !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(json); }
  if (form) opts.body = form;

  let res;
  try { res = await fetch(url, opts); }
  catch { throw new ApiError("Serveur injoignable. Vérifie que l'application est démarrée.", 0); }

  if (!res.ok) {
    let data = null;
    try { data = await res.json(); } catch { /* corps non JSON */ }
    if (res.status === 401 && state.token) { logout(true); }
    throw new ApiError(errorText(data, `Erreur ${res.status}`), res.status);
  }
  return blob ? res.blob() : res.json();
}

/* ---------- Session ---------- */
function setSession(data) {
  state.token = data.access_token;
  state.user = { username: data.username, is_admin: data.is_admin };
  localStorage.setItem("cf_token", state.token);
  localStorage.setItem("cf_user", JSON.stringify(state.user));
}

function logout(expired = false) {
  state.token = null; state.user = null; state.meta = null; state.opps = null;
  localStorage.removeItem("cf_token");
  localStorage.removeItem("cf_user");
  sessionStorage.removeItem("cf_gmaps_key");
  destroyCharts();
  if (typeof showAuth === "function") showAuth(expired ? "Session expirée, reconnecte-toi." : "");
}

/* ---------- Interface ---------- */
function toast(msg, type = "") {
  const el = document.createElement("div");
  el.className = "toast " + type;
  el.textContent = msg;
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), type === "error" ? 6000 : 3500);
}

function openModal(html) {
  const dlg = $("#modal");
  dlg.innerHTML = `<div class="modal-body">${html}</div>`;
  if (!dlg.open) dlg.showModal();
  return dlg;
}
function closeModal() { const d = $("#modal"); if (d.open) d.close(); }

function destroyCharts() { state.charts.forEach((c) => c.destroy()); state.charts = []; }

const fmt = {
  // Horodatage SQLite (UTC, "YYYY-MM-DD HH:MM:SS") -> date locale
  ts(s) {
    if (!s) return "";
    const d = new Date(String(s).replace(" ", "T") + "Z");
    return isNaN(d) ? esc(s) : d.toLocaleDateString("fr-FR");
  },
  // Date ISO "YYYY-MM-DD" -> date locale (sans décalage de fuseau)
  day(s) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s || "");
    return m ? `${m[3]}/${m[2]}/${m[1]}` : (s || "");
  },
};

const canEdit = (rec) => !!state.user && (state.user.is_admin || rec.added_by === state.user.username);

function scoreBadge(score) {
  const n = Math.max(0, Math.min(100, Math.round(Number(score) || 0)));
  return `<span class="score">${n}<span class="bar"><i style="width:${n}%"></i></span></span>`;
}

function options(list, selected = "", allLabel = null) {
  const first = allLabel === null ? "" : `<option value="">${esc(allLabel)}</option>`;
  return first + list.map((v) => `<option value="${esc(v)}"${v === selected ? " selected" : ""}>${esc(v)}</option>`).join("");
}

function debounce(fn, ms = 250) {
  let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

async function loadMeta() {
  if (!state.meta) state.meta = await api("/meta");
  return state.meta;
}

async function loadOpps(force = false) {
  if (force || !state.opps) state.opps = await api("/opportunities", { params: { min_score: 0 } });
  return state.opps;
}

// Téléchargement d'un fichier protégé (l'en-tête Authorization interdit un simple lien <a href>)
async function downloadFile(path, filename) {
  try {
    const blob = await api(path, { blob: true });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  } catch (e) { toast(e.message, "error"); }
}

// Délégation d'événements : les boutons portent data-action / data-id (aucun onclick inline)
const actionHandlers = {};
document.addEventListener("click", (ev) => {
  const el = ev.target.closest("[data-action]");
  if (!el || el.disabled) return;
  const handler = actionHandlers[el.dataset.action];
  if (handler) { ev.preventDefault(); handler(el, ev); }
});
document.addEventListener("click", (ev) => {
  const dlg = $("#modal");
  if (ev.target === dlg || ev.target.closest("[data-close]")) closeModal();
});
