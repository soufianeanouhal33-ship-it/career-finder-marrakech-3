import pandas as pd

from pipeline.sectors import classify_sector

# Mots-clés pondérés par pertinence IA / IT (poids sur 100)
IT_KEYWORDS = {
    "intelligence artificielle": 25,
    "machine learning": 25,
    "data science": 22,
    "deep learning": 22,
    "ia": 15,
    "ai": 15,
    "data": 15,
    "python": 15,
    "cloud": 12,
    "software": 12,
    "développement": 12,
    "developpement": 12,
    "informatique": 10,
    "tech": 8,
    "digital": 8,
    "startup": 8,
}


def clean_and_score_places(raw_places: list) -> pd.DataFrame:
    """Nettoie les résultats de l'API Places (New) et calcule un score
    d'opportunité (0-100) basé sur des mots-clés pondérés + la note Google."""
    cleaned = []
    for place in raw_places:
        name = (place.get("displayName") or {}).get("text", "").strip()
        address = place.get("formattedAddress", "")
        rating = place.get("rating", 0.0) or 0.0
        types = " ".join(place.get("types", []))
        location = place.get("location") or {}

        text_corpus = f"{name} {types}".lower()
        matched = [kw for kw in IT_KEYWORDS if kw in text_corpus]
        score_ia = sum(IT_KEYWORDS[kw] for kw in matched)
        score_total = min(score_ia + int(rating * 6), 100)

        cleaned.append({
            "place_id": place.get("id"),
            "nom": name,
            "adresse": address,
            "note": rating,
            "latitude": location.get("latitude"),
            "longitude": location.get("longitude"),
            "score_opportunite": score_total,
            "mots_cles": ", ".join(matched),
            "source": "Google Places",
            "site_web": place.get("websiteUri", "") or "",
            "telephone": place.get("internationalPhoneNumber", "") or "",
            "google_maps_url": place.get("googleMapsUri", "") or "",
            "secteur": classify_sector(name, types),
            "email": "",
        })

    df = pd.DataFrame(cleaned)
    if not df.empty:
        df.drop_duplicates(subset=["place_id"], inplace=True)
    return df


def raw_places_to_dataframe(raw_places: list) -> pd.DataFrame:
    """Met à plat les résultats bruts de l'API Places (New), tels que reçus,
    AVANT tout nettoyage ni calcul de score. Sert uniquement à produire
    l'export Excel 'avant nettoyage' (livrable), et n'est jamais inséré en
    base : les doublons, valeurs manquantes, etc. sont volontairement
    conservés tels quels pour montrer l'état brut de la collecte."""
    rows = []
    for place in raw_places:
        location = place.get("location") or {}
        rows.append({
            "place_id": place.get("id"),
            "nom_brut": (place.get("displayName") or {}).get("text", ""),
            "adresse_brute": place.get("formattedAddress", ""),
            "note_brute": place.get("rating"),
            "latitude": location.get("latitude"),
            "longitude": location.get("longitude"),
            "types_google": ", ".join(place.get("types", [])),
            "site_web": place.get("websiteUri", ""),
            "telephone": place.get("internationalPhoneNumber", ""),
            "google_maps_url": place.get("googleMapsUri", ""),
        })
    return pd.DataFrame(rows)
