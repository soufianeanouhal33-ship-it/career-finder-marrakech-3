"""Classification automatique d'une entreprise dans un secteur d'activité."""
import re
import unicodedata

SECTEURS = [
    "Informatique", "Hôtellerie", "Tourisme", "Construction", "Comptabilité",
    "Industrie", "Logistique", "Marketing", "RH", "Commerce", "Autre",
]

# Ordre = priorité (le premier secteur qui correspond gagne).
# Mots entiers uniquement (\b) pour éviter les faux positifs ("ai" dans "maison").
_RULES = [
    ("Informatique", [
        "informatique", "it", "ia", "ai", "data", "tech", "digital", "digitale", "software",
        "logiciel", "web", "cloud", "cyber", "cybersecurite", "reseau", "reseaux", "systeme",
        "systemes", "developpement", "intelligence artificielle", "machine learning",
        "startup", "numerique", "telecom", "telecoms", "electronics_store",
    ]),
    ("Hôtellerie", ["hotel", "hotels", "riad", "resort", "hostel", "auberge", "lodging",
                    "restaurant", "restauration", "cafe", "traiteur", "spa"]),
    ("Tourisme", ["tourisme", "voyage", "voyages", "travel", "travel_agency", "excursion",
                  "excursions", "tour", "tours", "tourist_attraction", "location de voitures"]),
    ("Construction", ["construction", "batiment", "btp", "immobilier", "promoteur", "architecte",
                      "architecture", "general_contractor", "real_estate_agency", "travaux"]),
    ("Comptabilité", ["comptabilite", "comptable", "expert comptable", "audit", "fiduciaire",
                      "accounting", "finance", "conseil fiscal", "cabinet comptable"]),
    ("Industrie", ["industrie", "industriel", "usine", "manufacture", "fabrication",
                   "mecanique", "metallurgie", "textile", "agroalimentaire"]),
    ("Logistique", ["logistique", "transport", "transports", "livraison", "demenagement",
                    "moving_company", "storage", "fret", "messagerie"]),
    ("Marketing", ["marketing", "communication", "publicite", "agence de communication",
                   "seo", "branding", "media", "medias", "evenementiel"]),
    ("RH", ["rh", "recrutement", "interim", "ressources humaines", "emploi", "staffing",
            "cabinet de recrutement", "formation"]),
    ("Commerce", ["commerce", "boutique", "magasin", "store", "shopping_mall", "distribution",
                  "vente", "negoce", "grossiste"]),
]


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9_ ]+", " ", text.lower())


_COMPILED = [
    (sector, re.compile(r"\b(?:" + "|".join(re.escape(_normalize(k)) for k in kws) + r")\b"))
    for sector, kws in _RULES
]


def classify_sector(*texts: str) -> str:
    """Retourne le secteur le plus probable d'après un ou plusieurs textes
    (nom de l'entreprise, types Google, mots-clés…). 'Autre' si rien ne correspond."""
    corpus = _normalize(" ".join(str(t or "") for t in texts))
    for sector, pattern in _COMPILED:
        if pattern.search(corpus):
            return sector
    return "Autre"


def normalize_sector(value: str) -> str:
    """Ramène une valeur libre (ex. colonne Excel 'secteur') à un secteur connu, sinon ''."""
    v = _normalize(value).strip()
    for s in SECTEURS:
        if _normalize(s).strip() == v:
            return s
    return ""
