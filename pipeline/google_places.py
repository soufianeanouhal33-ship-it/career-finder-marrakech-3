import time

import requests

PLACES_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

# Le nouveau format d'API exige de déclarer explicitement les champs voulus
# (FieldMask), pour limiter la facturation aux données réellement utilisées.
FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,"
    "places.location,places.rating,places.types,"
    "places.websiteUri,places.internationalPhoneNumber,places.googleMapsUri,"
    "nextPageToken"
)


def fetch_it_companies_google(
    api_key: str,
    location: str = "31.6295,-7.9811",
    radius: int = 10000,
    query: str = "Intelligence Artificielle OR Informatique",
    max_pages: int = 3,
) -> list:
    """
    Récupère les entreprises IT / IA via l'API Places (New) - Text Search,
    en suivant la pagination (jusqu'à max_pages pages de 20 résultats
    chacune, soit 60 résultats max par recherche).
    """
    try:
        lat_str, lng_str = location.split(",")
        lat, lng = float(lat_str), float(lng_str)
    except (ValueError, AttributeError):
        lat, lng = 31.6295, -7.9811

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASK,
    }

    all_results = []
    page_token = None

    for _ in range(max_pages):
        body = {
            "textQuery": query,
            "locationBias": {
                "circle": {
                    "center": {"latitude": lat, "longitude": lng},
                    "radius": radius,
                }
            },
            "pageSize": 20,
        }
        if page_token:
            # Laisser le temps au pageToken de devenir valide côté Google
            time.sleep(2)
            body["pageToken"] = page_token

        try:
            response = requests.post(PLACES_SEARCH_URL, json=body, headers=headers, timeout=15)
        except requests.RequestException:
            break

        if response.status_code != 200:
            break

        payload = response.json()
        all_results.extend(payload.get("places", []))
        page_token = payload.get("nextPageToken")
        if not page_token:
            break

    return all_results
