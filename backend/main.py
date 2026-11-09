import io
import os
import re
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from typing import Optional

import pandas as pd
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, field_validator

load_dotenv()  # doit précéder l'import de backend.security (lecture de SECRET_KEY)

from backend.database import (  # noqa: E402
    CONTRATS,
    TYPES_STAGE,
    application_owner,
    count_emails_since,
    count_users,
    create_user,
    delete_offer,
    delete_opportunity,
    get_connection,
    get_opportunities_for_user,
    get_offer_owner,
    get_opportunity,
    get_opportunity_owner,
    get_profile,
    get_user,
    init_db,
    insert_manual_opportunity,
    insert_offer,
    last_email_to,
    list_offers,
    log_email,
    toggle_favorite,
    update_opportunity_fields,
    upsert_offers,
    upsert_opportunities,
    upsert_profile,
)
from backend.mailer import (  # noqa: E402
    MAX_CV_BYTES,
    MailError,
    build_cv_message,
    is_valid_email,
    send_message,
    smtp_configured,
)
from backend.security import (  # noqa: E402
    LoginRateLimiter,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from pipeline.cleaner import clean_and_score_places, raw_places_to_dataframe  # noqa: E402
from pipeline.excel_importer import clean_excel_opportunities  # noqa: E402
from pipeline.google_places import fetch_it_companies_google  # noqa: E402
from pipeline.sectors import SECTEURS, _normalize  # noqa: E402

GOOGLE_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")
ALLOW_REGISTRATION = os.getenv("ALLOW_REGISTRATION", "true").lower() in ("1", "true", "yes")
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:8501").split(",") if o.strip()]

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
MIN_PASSWORD_LENGTH = 8

STATUTS = ["À contacter", "Envoyée", "Entretien", "Offre reçue", "Refusée"]
MAX_CV_PER_HOUR = int(os.getenv("MAX_CV_PER_HOUR", "10"))
MAX_CV_PER_DAY = int(os.getenv("MAX_CV_PER_DAY", "30"))
CV_RESEND_DELAY_DAYS = 7
STATIC_DIR = Path(__file__).resolve().parent.parent / "frontend" / "static"

login_limiter = LoginRateLimiter(max_attempts=5, window=300)

# Cache mémoire (par utilisateur) de la dernière collecte brute / nettoyée,
# utilisé uniquement pour l'export Excel "avant / après nettoyage" (livrable).
_snapshots: dict = {}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Career Opportunities API", version="3.0", lifespan=lifespan)

# Le frontend Streamlit appelle l'API côté serveur ; CORS ne sert qu'aux clients navigateur.
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


bearer_scheme = HTTPBearer(auto_error=False)


# ---------- Authentification ----------

def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict:
    """Dépendance FastAPI : exige un jeton Bearer valide et un compte existant."""
    unauthorized = HTTPException(
        status_code=401,
        detail="Authentification requise ou session expirée.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized
    payload = decode_access_token(credentials.credentials)
    if not payload or "sub" not in payload:
        raise unauthorized
    user = get_user(payload["sub"])
    if user is None:
        raise unauthorized
    return {"username": user["username"], "is_admin": bool(user["is_admin"])}


def _records(df: pd.DataFrame) -> list:
    """DataFrame -> liste de dicts JSON-compatibles (NaN -> None)."""
    return df.astype(object).where(df.notna(), None).to_dict(orient="records")


class Credentials(BaseModel):
    username: str
    password: str


@app.post("/api/auth/register", status_code=201)
def register(data: Credentials):
    username = data.username.strip()
    if not USERNAME_RE.match(username):
        raise HTTPException(status_code=422, detail="Nom d'utilisateur : 3 à 32 caractères (lettres, chiffres, . _ -).")
    if len(data.password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(status_code=422, detail=f"Mot de passe : {MIN_PASSWORD_LENGTH} caractères minimum.")
    if not ALLOW_REGISTRATION and count_users() > 0:
        raise HTTPException(status_code=403, detail="Les inscriptions sont désactivées sur ce serveur.")
    try:
        user = create_user(username, hash_password(data.password))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {
        "access_token": create_access_token(user["username"], user["is_admin"]),
        "token_type": "bearer",
        "username": user["username"],
        "is_admin": user["is_admin"],
    }


@app.post("/api/auth/login")
def login(data: Credentials, request: Request):
    username = data.username.strip()
    client_ip = request.client.host if request.client else "unknown"
    key = f"{username.lower()}|{client_ip}"
    if login_limiter.is_blocked(key):
        raise HTTPException(status_code=429, detail="Trop de tentatives. Réessaie dans quelques minutes.")
    user = get_user(username)
    # verify_password est appelé même si l'utilisateur n'existe pas (temps de réponse homogène)
    stored = user["password_hash"] if user else "scrypt$AAAA$AAAA"
    if not verify_password(data.password, stored) or user is None:
        login_limiter.register_failure(key)
        raise HTTPException(status_code=401, detail="Identifiants incorrects.")
    login_limiter.reset(key)
    return {
        "access_token": create_access_token(user["username"], bool(user["is_admin"])),
        "token_type": "bearer",
        "username": user["username"],
        "is_admin": bool(user["is_admin"]),
    }


@app.get("/api/auth/me")
def me(current: dict = Depends(get_current_user)):
    return current


# ---------- Schemas ----------

class ApplicationSchema(BaseModel):
    company: str
    poste: str
    statut: str = "À contacter"

    @field_validator("statut")
    @classmethod
    def _check_statut(cls, v):
        if v not in STATUTS:
            raise ValueError(f"Statut invalide (attendu : {', '.join(STATUTS)})")
        return v

    date_candidature: Optional[str] = None
    remarque: Optional[str] = None
    opportunity_id: Optional[int] = None


class ApplicationUpdateSchema(BaseModel):
    statut: Optional[str] = None
    remarque: Optional[str] = None

    @field_validator("statut")
    @classmethod
    def _check_statut(cls, v):
        if v is not None and v not in STATUTS:
            raise ValueError(f"Statut invalide (attendu : {', '.join(STATUTS)})")
        return v


class OpportunityUpdateSchema(BaseModel):
    email: Optional[str] = None
    telephone: Optional[str] = None
    site_web: Optional[str] = None
    adresse: Optional[str] = None
    secteur: Optional[str] = None

    @field_validator("email")
    @classmethod
    def _check_email(cls, v):
        v = (v or "").strip().lower()
        if v and not is_valid_email(v):
            raise ValueError("Adresse e-mail invalide")
        return v

    @field_validator("secteur")
    @classmethod
    def _check_secteur(cls, v):
        if v is not None and v not in SECTEURS:
            raise ValueError("Secteur inconnu")
        return v


class OfferSchema(BaseModel):
    titre: str
    entreprise: Optional[str] = ""
    opportunity_id: Optional[int] = None
    contrat: Optional[str] = "Stage"
    type_stage: Optional[str] = "Non renseigné"
    ville: Optional[str] = "Marrakech"
    date_publication: Optional[str] = ""
    url: Optional[str] = ""
    description: Optional[str] = ""

    @field_validator("url")
    @classmethod
    def _check_url(cls, v):
        v = (v or "").strip()
        if v and not re.match(r"^https?://", v, re.I):
            raise ValueError("Le lien doit commencer par http:// ou https://")
        return v


class ManualOpportunitySchema(BaseModel):
    nom: str
    email: Optional[str] = ""
    secteur: Optional[str] = ""
    adresse: Optional[str] = ""
    note: Optional[float] = 0.0
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    score_opportunite: Optional[int] = 0
    mots_cles: Optional[str] = ""
    site_web: Optional[str] = ""
    telephone: Optional[str] = ""
    google_maps_url: Optional[str] = ""

    @field_validator("nom")
    @classmethod
    def _check_nom(cls, v):
        v = (v or "").strip()
        if not v:
            raise ValueError("Le nom de l'entreprise est obligatoire")
        return v

    @field_validator("email")
    @classmethod
    def _check_email(cls, v):
        v = (v or "").strip().lower()
        if v and not is_valid_email(v):
            raise ValueError("Adresse e-mail invalide")
        return v

    @field_validator("secteur")
    @classmethod
    def _check_secteur(cls, v):
        if v and v not in SECTEURS:
            raise ValueError("Secteur inconnu")
        return v or ""


class ProfileSchema(BaseModel):
    skills: str = ""
    experience_years: float = 0.0
    bio: str = ""
    cv_filename: str = ""


def compute_match_score(profile_skills: str, mots_cles: str, score_opportunite: int) -> float:
    """Score de correspondance (0-100) entre les compétences du profil et une
    opportunité : recoupement de mots-clés (60%) + score d'opportunité global (40%)."""
    skills_set = {s.strip().lower() for s in (profile_skills or "").split(",") if s.strip()}
    opp_set = {s.strip().lower() for s in (mots_cles or "").split(",") if s.strip()}

    if not skills_set or not opp_set:
        keyword_match = 0.0
    else:
        overlap = len(skills_set & opp_set)
        keyword_match = round(100 * overlap / len(skills_set), 1)

    final = round(0.6 * keyword_match + 0.4 * (score_opportunite or 0), 1)
    return min(final, 100.0)


# ---------- Health (public) ----------

@app.get("/api/health")
def health():
    return {"status": "ok", "google_api_key_configured": bool(GOOGLE_API_KEY), "smtp_configured": smtp_configured()}


@app.get("/api/maps-key")
def get_maps_key(_: dict = Depends(get_current_user)):
    """Fournit la clé Google Maps du serveur aux utilisateurs connectés uniquement,
    pour charger la carte JavaScript. Cette clé est visible dans le navigateur :
    restreins-la par référent HTTP dans la console Google Cloud."""
    return {"api_key": GOOGLE_API_KEY}


# ---------- Profile / CV ----------

@app.get("/api/profile")
def read_profile(current: dict = Depends(get_current_user)):
    return get_profile(current["username"])


@app.post("/api/profile")
def write_profile(data: ProfileSchema, current: dict = Depends(get_current_user)):
    payload = data.model_dump()
    payload["user"] = current["username"]
    upsert_profile(payload)
    return {"status": "success"}


# ---------- Matching IA ----------

@app.get("/api/matching")
def get_matching(min_score: float = Query(0), current: dict = Depends(get_current_user)):
    df = get_opportunities_for_user(current["username"])
    if df.empty:
        return []
    skills = get_profile(current["username"]).get("skills", "")
    df["match_score"] = df.apply(
        lambda r: compute_match_score(skills, r.get("mots_cles", ""), r.get("score_opportunite", 0)),
        axis=1,
    )
    df = df[df["match_score"] >= min_score].sort_values("match_score", ascending=False)
    return _records(df)


# ---------- Opportunities ----------

@app.get("/api/opportunities")
def get_opportunities(
    min_score: int = Query(0),
    favoris_only: bool = Query(False),
    current: dict = Depends(get_current_user),
):
    return _records(get_opportunities_for_user(current["username"], min_score, favoris_only))


@app.get("/api/opportunities/export")
def export_opportunities(min_score: int = Query(0), current: dict = Depends(get_current_user)):
    df = get_opportunities_for_user(current["username"], min_score)
    buf = StringIO()
    df.to_csv(buf, index=False)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=opportunites.csv"},
    )


@app.post("/api/opportunities/refresh")
def refresh_opportunities(
    query: str = Query("Intelligence Artificielle OR Informatique"),
    location: str = Query("31.6295,-7.9811"),
    radius: int = Query(10000),
    x_google_api_key: Optional[str] = Header(None),
    current: dict = Depends(get_current_user),
):
    """Pipeline complet : Google Places -> nettoyage/scoring -> enregistrement en base.
    Une clé personnelle peut être fournie dans l'en-tête `X-Google-Api-Key` (jamais
    journalisée ni stockée) ; sinon GOOGLE_MAPS_API_KEY du serveur est utilisée."""
    key_to_use = x_google_api_key or GOOGLE_API_KEY
    if not key_to_use:
        raise HTTPException(
            status_code=500,
            detail="Aucune clé Google Maps fournie (ni dans .env, ni dans l'interface).",
        )

    raw_places = fetch_it_companies_google(key_to_use, location=location, radius=radius, query=query)
    if not raw_places:
        return {"status": "empty", "message": "Aucun résultat renvoyé par Google Places.", "count": 0}

    df = clean_and_score_places(raw_places)
    count = upsert_opportunities(df, added_by=current["username"])

    _snapshots[current["username"]] = {
        "label": "Google Places",
        "avant": raw_places_to_dataframe(raw_places),
        "apres": df,
    }
    return {"status": "success", "count": count}


@app.patch("/api/opportunities/{opportunity_id}/favorite")
def patch_favorite(opportunity_id: int, current: dict = Depends(get_current_user)):
    try:
        new_val = toggle_favorite(current["username"], opportunity_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Opportunité introuvable")
    return {"id": opportunity_id, "favori": new_val}


@app.delete("/api/opportunities/{opportunity_id}")
def remove_opportunity(opportunity_id: int, current: dict = Depends(get_current_user)):
    """Le catalogue est partagé : seul l'auteur de l'ajout (ou un admin) peut supprimer."""
    exists, owner = get_opportunity_owner(opportunity_id)
    if not exists:
        raise HTTPException(status_code=404, detail="Opportunité introuvable")
    if not current["is_admin"] and owner != current["username"]:
        raise HTTPException(status_code=403, detail="Tu ne peux supprimer que les opportunités que tu as ajoutées.")
    delete_opportunity(opportunity_id)
    return {"status": "success"}


@app.post("/api/opportunities/manual")
def add_manual_opportunity(data: ManualOpportunitySchema, current: dict = Depends(get_current_user)):
    try:
        new_id = insert_manual_opportunity(data.model_dump(), added_by=current["username"])
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"status": "success", "id": new_id}


@app.post("/api/opportunities/import-excel")
async def import_excel(
    file: UploadFile = File(...),
    only_it_ai: bool = Query(True),
    current: dict = Depends(get_current_user),
):
    """Nettoie un fichier Excel brut d'entreprises et l'intègre à la base
    (dédoublonnage, suppression des fiches fermées, filtrage sectoriel, scoring)."""
    content = await file.read()
    try:
        df, report, raw_snapshot = clean_excel_opportunities(io.BytesIO(content), only_it_ai=only_it_ai)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erreur de lecture du fichier Excel : {e}")

    count = upsert_opportunities(df, added_by=current["username"])
    report["opportunites_ajoutees"] = count

    _snapshots[current["username"]] = {"label": "Import Excel", "avant": raw_snapshot, "apres": df}
    return {"status": "success", "report": report}


# ---------- Exports Excel (livrables) ----------

def _df_to_xlsx_response(sheets: dict, filename: str) -> StreamingResponse:
    """sheets: dict {nom_feuille: DataFrame} -> réponse .xlsx téléchargeable."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for sheet_name, sheet_df in sheets.items():
            safe_name = sheet_name[:31]  # limite Excel
            (sheet_df if sheet_df is not None else pd.DataFrame()).to_excel(
                writer, sheet_name=safe_name, index=False
            )
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def _user_applications(username: str) -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql_query(
        "SELECT * FROM applications WHERE user=? ORDER BY date_ajout DESC", conn, params=(username,)
    )
    conn.close()
    return df


@app.get("/api/export/avant-apres")
def export_avant_apres(current: dict = Depends(get_current_user)):
    """Excel à 2 feuilles (AVANT / APRÈS nettoyage) de ta dernière collecte ou import."""
    snap = _snapshots.get(current["username"])
    if not snap or snap["avant"] is None or snap["apres"] is None:
        raise HTTPException(
            status_code=404,
            detail="Aucune collecte ni import récent en mémoire. Lance d'abord une "
                   "collecte Google Places ou un import Excel.",
        )
    label = (snap["label"] or "donnees").replace(" ", "_")
    return _df_to_xlsx_response(
        {"Avant nettoyage": snap["avant"], "Apres nettoyage": snap["apres"]},
        f"donnees_avant_apres_{label}.xlsx",
    )


@app.get("/api/export/complet")
def export_complet(current: dict = Depends(get_current_user)):
    """Excel complet : opportunités scorées (tes favoris inclus), suivi de tes
    candidatures et résumé chiffré."""
    opps = get_opportunities_for_user(current["username"])
    apps = _user_applications(current["username"])

    resume = pd.DataFrame([{
        "total_opportunites": len(opps),
        "score_moyen": round(opps["score_opportunite"].mean(), 1) if not opps.empty else 0,
        "favoris": int(opps["favori"].sum()) if not opps.empty else 0,
        "total_candidatures": len(apps),
    }])
    if not apps.empty:
        par_statut = apps["statut"].value_counts().rename_axis("statut").reset_index(name="nombre")
    else:
        par_statut = pd.DataFrame(columns=["statut", "nombre"])

    return _df_to_xlsx_response(
        {
            "Opportunites (resultats)": opps,
            "Suivi candidatures": apps,
            "Resume": resume,
            "Candidatures par statut": par_statut,
        },
        "resultats_analyse_et_suivi.xlsx",
    )


# ---------- Métadonnées (listes de valeurs pour les filtres de l'interface) ----------

@app.get("/api/meta")
def get_meta(_: dict = Depends(get_current_user)):
    return {
        "secteurs": SECTEURS,
        "contrats": CONTRATS,
        "types_stage": TYPES_STAGE,
        "statuts": STATUTS,
        "smtp_configured": smtp_configured(),
        "cv_resend_delay_days": CV_RESEND_DELAY_DAYS,
    }


# ---------- Modification d'une entreprise (e-mail, téléphone, secteur…) ----------

@app.patch("/api/opportunities/{opportunity_id}")
def edit_opportunity(opportunity_id: int, data: OpportunityUpdateSchema,
                     current: dict = Depends(get_current_user)):
    """Seul l'auteur de l'ajout (ou un admin) peut modifier une fiche du catalogue partagé."""
    exists, owner = get_opportunity_owner(opportunity_id)
    if not exists:
        raise HTTPException(status_code=404, detail="Opportunité introuvable")
    if not current["is_admin"] and owner != current["username"]:
        raise HTTPException(status_code=403, detail="Tu ne peux modifier que les entreprises que tu as ajoutées.")
    fields = data.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail="Aucun champ à mettre à jour")
    update_opportunity_fields(opportunity_id, fields)
    return {"status": "success"}


# ---------- Offres de stage / d'emploi ----------

def _norm_contrat(value) -> str:
    v = _normalize(value).strip()
    for c in CONTRATS:
        if _normalize(c).strip() == v:
            return c
    if "stage" in v:
        return "Stage"
    return "Autre" if v else "Stage"


def _norm_type_stage(value) -> str:
    v = _normalize(value).strip()
    if not v or "renseign" in v:
        return "Non renseigné"
    if "pfe" in v or ("fin" in v and "etude" in v):
        return "Stage de fin d'études"
    if "embauche" in v:
        return "Stage Pré-embauche"
    if "fonction" in v or "observation" in v or "initiation" in v:
        return "Stage fonctionnel"
    return "Non renseigné"


_OFFER_ALIASES = {
    "titre": ["titre", "title", "intitule", "poste", "offre", "libelle"],
    "entreprise": ["entreprise", "company", "societe", "employeur"],
    "contrat": ["contrat", "contract", "type_contrat", "type de contrat"],
    "type_stage": ["type_stage", "type de stage", "stage", "nature"],
    "ville": ["ville", "city", "lieu", "localisation"],
    "date_publication": ["date_publication", "publication", "date de publication", "date_pub", "date"],
    "url": ["url", "lien", "link"],
    "description": ["description", "details", "détails", "resume"],
}


def _find_col(columns: dict, aliases: list):
    for a in aliases:
        if a in columns:
            return columns[a]
    return None


@app.get("/api/offers")
def get_offers(
    q: str = Query("", max_length=100),
    contrat: str = Query(""),
    type_stage: str = Query(""),
    opportunity_id: Optional[int] = Query(None),
    _: dict = Depends(get_current_user),
):
    return _records(list_offers(q.strip(), contrat, type_stage, opportunity_id))


@app.post("/api/offers", status_code=201)
def add_offer(data: OfferSchema, current: dict = Depends(get_current_user)):
    payload = data.model_dump()
    payload["contrat"] = _norm_contrat(payload.get("contrat"))
    payload["type_stage"] = _norm_type_stage(payload.get("type_stage"))
    try:
        new_id = insert_offer(payload, added_by=current["username"])
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"status": "success", "id": new_id}


@app.delete("/api/offers/{offer_id}")
def remove_offer(offer_id: int, current: dict = Depends(get_current_user)):
    exists, owner = get_offer_owner(offer_id)
    if not exists:
        raise HTTPException(status_code=404, detail="Offre introuvable")
    if not current["is_admin"] and owner != current["username"]:
        raise HTTPException(status_code=403, detail="Tu ne peux supprimer que les offres que tu as ajoutées.")
    delete_offer(offer_id)
    return {"status": "success"}


@app.post("/api/offers/import")
async def import_offers(file: UploadFile = File(...), current: dict = Depends(get_current_user)):
    """Importe des offres depuis un fichier Excel (.xlsx) ou CSV. Les noms de colonnes sont
    reconnus de façon souple (titre/intitulé/poste, entreprise/société, contrat, type de stage,
    date de publication, lien…). Les offres déjà présentes sont ignorées."""
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Fichier trop volumineux (10 Mo max).")
    name = (file.filename or "").lower()
    try:
        if name.endswith(".csv"):
            raw = pd.read_csv(io.BytesIO(content), sep=None, engine="python", encoding="utf-8-sig")
        else:
            raw = pd.read_excel(io.BytesIO(content))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Fichier illisible : {e}")

    columns = {_normalize(c).strip(): c for c in raw.columns}
    cols = {field: _find_col(columns, [_normalize(a).strip() for a in aliases])
            for field, aliases in _OFFER_ALIASES.items()}
    if cols["titre"] is None:
        raise HTTPException(status_code=400, detail="Colonne du titre introuvable (attendu : titre, intitulé ou poste).")

    # Rapprochement entreprise -> fiche du catalogue (par nom, insensible à la casse)
    catalogue = get_opportunities_for_user(current["username"])
    by_name = {str(n).strip().lower(): int(i) for n, i in zip(catalogue["nom"], catalogue["id"])}

    rows = []
    for _, r in raw.iterrows():
        def val(field):
            c = cols[field]
            v = r[c] if c is not None else ""
            return "" if pd.isna(v) else str(v).strip()

        pub = val("date_publication")
        parsed = pd.to_datetime(pub, errors="coerce", dayfirst=True) if pub else pd.NaT
        entreprise = val("entreprise")
        rows.append({
            "titre": val("titre"),
            "entreprise": entreprise,
            "opportunity_id": by_name.get(entreprise.lower()),
            "contrat": _norm_contrat(val("contrat")),
            "type_stage": _norm_type_stage(val("type_stage")),
            "ville": val("ville") or "Marrakech",
            "date_publication": parsed.strftime("%Y-%m-%d") if pd.notna(parsed) else pub,
            "url": val("url") if re.match(r"^https?://", val("url"), re.I) else "",
            "description": val("description"),
            "source": "Import fichier",
        })
    report = upsert_offers(rows, added_by=current["username"])
    report["lignes_lues"] = len(raw)
    return {"status": "success", "report": report}


# ---------- Envoi du CV par e-mail ----------

@app.post("/api/send-cv")
def send_cv(
    opportunity_id: int = Form(...),
    subject: str = Form(..., max_length=200),
    message: str = Form(..., max_length=5000),
    reply_to: str = Form("", max_length=254),
    force: bool = Form(False),
    cv: UploadFile = File(...),
    current: dict = Depends(get_current_user),
):
    """Envoie ton CV (PDF) à l'adresse e-mail enregistrée pour l'entreprise.
    Le destinataire vient TOUJOURS de la base (jamais du client) : l'API ne peut pas servir
    de relais d'e-mails vers des adresses arbitraires. Limites : 10 envois/heure, 30/jour,
    et confirmation requise pour renvoyer à la même entreprise dans les 7 jours."""
    if not smtp_configured():
        raise HTTPException(status_code=503, detail="L'envoi d'e-mails n'est pas configuré sur ce serveur (SMTP).")
    opp = get_opportunity(opportunity_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Entreprise introuvable")
    to_email = (opp.get("email") or "").strip()
    if not is_valid_email(to_email):
        raise HTTPException(status_code=400, detail="Cette entreprise n'a pas d'adresse e-mail valide enregistrée.")
    subject, message, reply_to = subject.strip(), message.strip(), reply_to.strip()
    if not subject or not message:
        raise HTTPException(status_code=422, detail="L'objet et le message sont obligatoires.")
    if reply_to and not is_valid_email(reply_to):
        raise HTTPException(status_code=422, detail="Ton adresse de réponse est invalide.")

    cv_bytes = cv.file.read(MAX_CV_BYTES + 1)
    if len(cv_bytes) > MAX_CV_BYTES:
        raise HTTPException(status_code=413, detail="CV trop volumineux (5 Mo maximum).")
    if not (cv.filename or "").lower().endswith(".pdf") or not cv_bytes.startswith(b"%PDF"):
        raise HTTPException(status_code=422, detail="Le CV doit être un fichier PDF valide.")

    user = current["username"]
    if count_emails_since(user, 1) >= MAX_CV_PER_HOUR or count_emails_since(user, 24) >= MAX_CV_PER_DAY:
        raise HTTPException(status_code=429, detail="Limite d'envois atteinte (10 par heure, 30 par jour). Réessaie plus tard.")

    previous = last_email_to(user, opportunity_id)
    if previous and not force:
        sent_at = datetime.strptime(previous, "%Y-%m-%d %H:%M:%S")
        if datetime.now(timezone.utc).replace(tzinfo=None) - sent_at < timedelta(days=CV_RESEND_DELAY_DAYS):
            raise HTTPException(
                status_code=409,
                detail=f"Tu as déjà envoyé ton CV à cette entreprise le {sent_at:%d/%m/%Y}. "
                       "Confirme pour le renvoyer.",
            )

    msg = build_cv_message(to_email=to_email, subject=subject, body=message, cv_bytes=cv_bytes,
                           cv_filename=cv.filename, reply_to=reply_to)
    try:
        send_message(msg)
    except MailError as e:
        raise HTTPException(status_code=502, detail=str(e))

    log_email(user, opportunity_id, to_email, subject)
    # Suivi automatique : une candidature « Envoyée » est créée
    conn = get_connection()
    conn.execute(
        """INSERT INTO applications (user, company, poste, statut, date_candidature, remarque, opportunity_id)
           VALUES (?, ?, ?, 'Envoyée', ?, ?, ?)""",
        (user, opp["nom"], "Candidature spontanée", date.today().isoformat(),
         f"CV envoyé par e-mail à {to_email}", opportunity_id),
    )
    conn.commit()
    conn.close()
    return {"status": "success", "to": to_email}


# ---------- Stats ----------

@app.get("/api/stats")
def get_stats(current: dict = Depends(get_current_user)):
    df = get_opportunities_for_user(current["username"])
    apps = _user_applications(current["username"])
    offers = list_offers()

    def counts(series: pd.Series) -> dict:
        return {str(k): int(v) for k, v in series.value_counts().items()} if len(series) else {}

    has_email = df["email"].fillna("").str.strip() != "" if not df.empty else pd.Series(dtype=bool)
    has_site = df["site_web"].fillna("").str.strip() != "" if not df.empty else pd.Series(dtype=bool)
    n = len(df)
    return {
        "total_opportunites": n,
        "score_moyen": round(df["score_opportunite"].mean(), 1) if n else 0,
        "favoris": int(df["favori"].sum()) if n else 0,
        "total_candidatures": len(apps),
        "candidatures_par_statut": counts(apps["statut"]) if not apps.empty else {},
        "total_offres": len(offers),
        "total_secteurs": int(df["secteur"].nunique()) if n else 0,
        "entreprises_avec_email": int(has_email.sum()) if n else 0,
        "cv_envoyes": int(df["cv_envoye_le"].notna().sum()) if n else 0,
        "par_secteur": counts(df["secteur"]) if n else {},
        "offres_par_type_stage": counts(offers["type_stage"]) if not offers.empty else {},
        "offres_par_contrat": counts(offers["contrat"]) if not offers.empty else {},
        "presence_numerique": {
            "avec_email": int(has_email.sum()) if n else 0,
            "sans_email": int((~has_email).sum()) if n else 0,
            "avec_site_web": int(has_site.sum()) if n else 0,
            "sans_site_web": int((~has_site).sum()) if n else 0,
        },
    }


# ---------- Applications (propres à chaque utilisateur) ----------

def _require_own_application(application_id: int, current: dict) -> None:
    owner = application_owner(application_id)
    # 404 aussi pour les candidatures d'autrui : on ne révèle pas leur existence
    if owner is None or owner != current["username"]:
        raise HTTPException(status_code=404, detail="Candidature introuvable")


@app.post("/api/applications")
def create_application(app_data: ApplicationSchema, current: dict = Depends(get_current_user)):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO applications (user, company, poste, statut, date_candidature, remarque, opportunity_id)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (current["username"], app_data.company, app_data.poste, app_data.statut,
         app_data.date_candidature, app_data.remarque, app_data.opportunity_id),
    )
    conn.commit()
    conn.close()
    return {"status": "success", "message": "Candidature enregistrée"}


@app.get("/api/applications")
def get_applications(current: dict = Depends(get_current_user)):
    return _records(_user_applications(current["username"]))


@app.patch("/api/applications/{application_id}")
def update_application(application_id: int, data: ApplicationUpdateSchema,
                       current: dict = Depends(get_current_user)):
    _require_own_application(application_id, current)
    fields, values = [], []
    if data.statut is not None:
        fields.append("statut=?")
        values.append(data.statut)
    if data.remarque is not None:
        fields.append("remarque=?")
        values.append(data.remarque)
    if not fields:
        raise HTTPException(status_code=400, detail="Aucun champ à mettre à jour")

    conn = get_connection()
    cur = conn.cursor()
    values.append(application_id)
    cur.execute(f"UPDATE applications SET {', '.join(fields)} WHERE id=?", values)
    conn.commit()
    conn.close()
    return {"status": "success"}


@app.delete("/api/applications/{application_id}")
def remove_application(application_id: int, current: dict = Depends(get_current_user)):
    _require_own_application(application_id, current)
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM applications WHERE id=?", (application_id,))
    conn.commit()
    conn.close()
    return {"status": "success"}


# ---------- Interface web (doit rester DERNIÈRE : le montage sur "/" capte tout le reste) ----------
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
