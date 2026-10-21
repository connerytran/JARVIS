import os

import requests
from dotenv import load_dotenv

load_dotenv()

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
_FIELD_MASK = "places.id,places.displayName,places.formattedAddress,places.location"


def resolve_place(query: str, bias_lat: float = None, bias_lon: float = None) -> dict | None:
    """Resolves free text like 'chipotle on hillsborough' into one specific place via
    Places API Text Search. Biasing toward (bias_lat, bias_lon) when given picks the
    nearest branch of a chain rather than an arbitrary one. Returns None if nothing matched.
    """
    body = {"textQuery": query}
    if bias_lat is not None and bias_lon is not None:
        body["locationBias"] = {
            "circle": {
                "center": {"latitude": bias_lat, "longitude": bias_lon},
                "radius": 20000.0,
            }
        }

    resp = requests.post(
        _TEXT_SEARCH_URL,
        json=body,
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
            "X-Goog-FieldMask": _FIELD_MASK,
        },
        timeout=15,
    )
    resp.raise_for_status()
    places = resp.json().get("places", [])
    if not places:
        return None

    place = places[0]
    return {
        "place_id": place["id"],
        "name": place.get("displayName", {}).get("text"),
        "formatted_address": place.get("formattedAddress"),
        "lat": place["location"]["latitude"],
        "lon": place["location"]["longitude"],
    }
