import hashlib
import re

import pandas as pd

from pipeline.cleaner import IT_KEYWORDS
from pipeline.sectors import classify_sector, normalize_sector

# Valeurs de la colonne "type" considérées comme IT / IA
IT_SECTOR_TYPES = {"informatique", "it", "intelligence artificielle"}

OUTPUT_COLUMNS = [
    "place_id", "nom", "adresse", "note", "latitude",
    "longitude", "score_opportunite", "mots_cles", "source",
    "site_web", "telephone", "google_maps_url", "secteur", "email",
]

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _clean_email(value) -> str:
    v = str(value or "").strip().lower()
    return v if _EMAIL_RE.match(v) else ""


def _normalize_name(name) -> str:
    """Nettoie la casse d'un nom d'entreprise (évite le TOUT MAJUSCULE / tout
    minuscule) tout en préservant les acronymes courts déjà en majuscules."""
    name = re.sub(r"\s+", " ", str(name).strip())
    words = name.split(" ")
    normalized = [w if (w.isupper() and len(w) <= 3) else w.capitalize() for w in words]
    return " ".join(normalized)


def _make_place_id(nom: str, adresse: str) -> str:
    """Identifiant déterministe (pas de place_id Google pour ces données),
    basé sur nom + adresse, pour permettre l'upsert sans doublons."""
    raw = f"{nom.lower().strip()}-{str(adresse).lower().strip()}"
    return "excel-" + hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]


def clean_excel_opportunities(file_path_or_buffer, only_it_ai: bool = True):
    """
    Nettoie un fichier Excel brut d'entreprises (colonnes attendues :
    entreprise, secteur, type, adresse, lat, lon, note, avis, site_web,
    telephone, statut_google) et le convertit dans le même schéma que les
    opportunités Google Places, prêt pour upsert_opportunities().

    Étapes de nettoyage : suppression des lignes sans nom, normalisation de la
    casse, suppression des fiches fermées définitivement (CLOSED_PERMANENTLY),
    suppression des doublons (nom + adresse), filtrage optionnel sur les
    secteurs Informatique / IA, puis calcul du score d'opportunité (mots-clés
    + bonus de secteur explicite + note Google).

    Retourne (dataframe_nettoyé, rapport) où rapport détaille combien de
    lignes ont été retirées à chaque étape.
    """
    raw = pd.read_excel(file_path_or_buffer)
    raw.columns = [str(c).strip().lower() for c in raw.columns]

    if "entreprise" not in raw.columns:
        raise ValueError("Colonne 'entreprise' introuvable dans le fichier Excel.")

    # Conservée telle quelle (avant toute étape de nettoyage) pour l'export
    # Excel "avant nettoyage" (livrable).
    raw_snapshot = raw.copy()

    report = {"lignes_lues": len(raw)}
    df = raw.copy()

    # 1. Lignes sans nom d'entreprise
    df = df[df["entreprise"].notna() & (df["entreprise"].astype(str).str.strip() != "")]
    report["sans_nom_supprimees"] = report["lignes_lues"] - len(df)

    # 2. Normalisation des champs
    df["entreprise"] = df["entreprise"].apply(_normalize_name)
    df["type"] = df["type"].astype(str).str.strip() if "type" in df.columns else ""
    df["adresse"] = df["adresse"].fillna("").astype(str).str.strip() if "adresse" in df.columns else ""
    df["note"] = pd.to_numeric(df["note"], errors="coerce").fillna(0.0) if "note" in df.columns else 0.0
    if "lat" not in df.columns:
        df["lat"] = None
    if "lon" not in df.columns:
        df["lon"] = None

    # 3. Fiches fermées définitivement
    before = len(df)
    if "statut_google" in df.columns:
        df = df[df["statut_google"].astype(str).str.upper() != "CLOSED_PERMANENTLY"]
    report["fermees_supprimees"] = before - len(df)

    # 4. Doublons (même nom + même adresse)
    before = len(df)
    df = df.drop_duplicates(subset=["entreprise", "adresse"])
    report["doublons_supprimes"] = before - len(df)

    # 5. Filtrage secteur IT / IA (optionnel)
    before = len(df)
    if only_it_ai:
        df = df[df["type"].str.lower().isin(IT_SECTOR_TYPES)]
    report["hors_secteur_supprimees"] = before - len(df)

    if df.empty:
        report["lignes_conservees"] = 0
        return pd.DataFrame(columns=OUTPUT_COLUMNS), report, raw_snapshot

    # 6. Scoring : mots-clés détectés + bonus de secteur explicite + note
    def score_row(row):
        name = str(row.get("entreprise", "")).lower()
        sector_type = str(row.get("type", "")).lower()
        rating = float(row.get("note", 0.0) or 0.0)

        matched = [kw for kw in IT_KEYWORDS if kw in name]
        score_kw = sum(IT_KEYWORDS[kw] for kw in matched)

        if sector_type == "intelligence artificielle":
            sector_bonus = 35
        elif sector_type in ("informatique", "it"):
            sector_bonus = 30
        else:
            sector_bonus = 0

        total = min(score_kw + sector_bonus + int(rating * 6), 100)
        keywords_label = ", ".join(matched) if matched else sector_type
        return pd.Series({"score_opportunite": total, "mots_cles": keywords_label})

    df = pd.concat([df, df.apply(score_row, axis=1)], axis=1)

    # 6 bis. Secteur d'activité (colonne Excel "secteur" si valide, sinon classification
    # automatique) et e-mail de contact (colonne "email" ou "e-mail", validé)
    def sector_row(row):
        explicit = normalize_sector(row.get("secteur", "")) if "secteur" in df.columns else ""
        return explicit or classify_sector(row.get("entreprise", ""), row.get("type", ""))

    sectors = df.apply(sector_row, axis=1)
    email_col = next((c for c in ("email", "e-mail", "mail") if c in df.columns), None)
    emails = df[email_col].apply(_clean_email) if email_col else ""

    # 7. Mise en forme finale, même schéma que les opportunités Google Places
    cleaned = pd.DataFrame({
        "place_id": [_make_place_id(n, a) for n, a in zip(df["entreprise"], df["adresse"])],
        "nom": df["entreprise"],
        "adresse": df["adresse"],
        "note": df["note"],
        "latitude": df["lat"],
        "longitude": df["lon"],
        "score_opportunite": df["score_opportunite"],
        "mots_cles": df["mots_cles"],
        "source": "Import Excel",
        "site_web": df["site_web"].fillna("").astype(str) if "site_web" in df.columns else "",
        "telephone": df["telephone"].fillna("").astype(str) if "telephone" in df.columns else "",
        "google_maps_url": "",
        "secteur": sectors,
        "email": emails,
    })
    cleaned = cleaned.drop_duplicates(subset=["place_id"]).reset_index(drop=True)

    report["lignes_conservees"] = len(cleaned)
    return cleaned, report, raw_snapshot
