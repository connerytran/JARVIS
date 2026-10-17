import os
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv

from _tesla_client import ensure_awake, locate, send_route, set_temps, start_climate

from _google_maps import resolve_place

load_dotenv()

DEFAULT_CAR_NAME = "The Sensei Mobile"
CARS = {
    "The Sensei Mobile": os.getenv("SENSEI_TESLA_VIN"),
    "parent's tesla": os.getenv("OTHER_TESLA_VIN")
}

ADDRESS_BOOK_PATH = Path(__file__).parent / "_tesla-addresses.yaml"
if ADDRESS_BOOK_PATH.exists():
    with open(ADDRESS_BOOK_PATH, "r") as f:
        _raw_addresses = yaml.safe_load(f) or {}
    ADDRESSES = {k.strip().lower(): v for k, v in _raw_addresses.items()}
else:
    ADDRESSES = {}


def _resolve_car(car_name: str = None):
    """Returns (display_name, vin), or (None, None) if car_name isn't recognized."""
    if not car_name:
        return DEFAULT_CAR_NAME, CARS[DEFAULT_CAR_NAME]
    key = car_name.strip()
    if key not in CARS or not CARS[key]:
        return None, None
    return key, CARS[key]


def prep_car(car_name: str = None, temp: int = None) -> dict:

    name, vin = _resolve_car(car_name)
    if vin is None:
        known = ", ".join(sorted(set(CARS.keys())))
        return {"status": "error", "message": f"I don't recognize a car called '{car_name}', Sir. Known cars: {known}."}

    try:
        awake = ensure_awake(vin)
    except Exception as e:
        return {"status": "error", "message": f"I couldn't reach {name}. ({e})"}
    if not awake:
        return {"status": "error", "message": f"{name} did not wake up in time, Sir."}

    try:
        ok, reason = start_climate(vin)
    except Exception as e:
        return {"status": "error", "message": f"Failed to start climate control on {name}. ({e})"}
    if not ok:
        detail = f" ({reason})" if reason else ""
        return {"status": "error", "message": f"Failed to start climate control on {name}.{detail}"}

    if temp is not None:
        celsius = round((temp - 32) * 5 / 9, 1)  # the car works in Celsius; the user speaks Fahrenheit
        try:
            ok, reason = set_temps(vin, celsius, celsius)
        except Exception as e:
            return {"status": "error", "message": f"Climate is on for {name}, but I could not set the target temperature. ({e})"}
        if not ok:
            detail = f" ({reason})" if reason else ""
            return {"status": "error", "message": f"Climate is on for {name}, but I could not set the target temperature.{detail}"}

    temp_msg = f" and set to {temp}°F" if temp is not None else ""
    return {"status": "success", "message": f"Climate control is on{temp_msg} for {name}."}
prep_car.__doc__ = f"""Wakes a Tesla and turns on climate control, optionally setting a target cabin temperature.
Call this when the user asks to warm up / cool down / prep / get their car ready.
Args:
    car_name (str, optional): Which car. One of: {', '.join(sorted(set(CARS.keys())))}. Defaults to '{DEFAULT_CAR_NAME}' if not specified.
    temp (int, optional): Target cabin temperature in degrees Fahrenheit. If omitted, uses the vehicle's last-used setting.
"""


   



def navigate_car(destinations: list[str], car_name: str = None) -> dict:

    name, vin = _resolve_car(car_name)
    if vin is None:
        known = ", ".join(sorted(set(CARS.keys())))
        return {"status": "error", "message": f"I don't recognize a car called '{car_name}', Sir. Known cars: {known}."}

    if isinstance(destinations, str):  # the model sometimes passes a lone string instead of a list
        destinations = [destinations]
    if not destinations:
        return {"status": "error", "message": "There was an error with the destinations provided."}

    try:
        awake = ensure_awake(vin)
        location = locate(vin) if awake else None
    except Exception as e:
        return {"status": "error", "message": f"I couldn't reach {name}. ({e})"}
    if not awake:
        return {"status": "error", "message": f"{name} did not wake up."}

    bias_lat, bias_lon = location or (None, None)
    places = []
    for destination in destinations:
        known_address = ADDRESSES.get(destination.strip().lower())
        try:
            if known_address:  # exact address text, so no need to bias toward the car
                place = resolve_place(known_address)
            else:
                place = resolve_place(destination, bias_lat, bias_lon)
        except requests.RequestException as e:
            return {"status": "error", "message": f"The Google Maps lookup failed on '{destination}', so nothing was sent to {name}. ({e})"}
        if place is None:
            return {"status": "error", "message": f"I couldn't find a place matching '{destination}', so nothing was sent to {name}."}
        places.append(place)

    try:
        result = send_route(vin, [place["place_id"] for place in places])
    except Exception as e:
        return {"status": "error", "message": f"I found the places, but failed to send the route to {name}'s navigation. ({e})"}

    response = result.get("response") or {}
    if not response.get("result"):
        reason = response.get("reason")
        detail = f" ({reason})" if reason else ""
        return {"status": "error", "message": f"I found the places, but {name}'s navigation rejected the route.{detail}"}

    stops = []
    for place in places:
        street = (place["formatted_address"] or "").split(",")[0]  # "2316 Hillsborough St, Raleigh, NC ..." -> "2316 Hillsborough St"
        stops.append(street if street.startswith(place["name"] or "") else f"{place['name']} at {street}")  # an address-only place is named after its street
    route = ", then \n".join(stops)
    return {"status": "success", "message": f"Navigating {name} to {route}."}
navigate_car.__doc__ = f"""Sends one or more destinations to a Tesla's navigation system as a single route, and the car starts navigating.
Call this when the user asks to navigate, drive, or go somewhere.
Args:
    destinations (list[str]): A JSON array of places, in the order the user wants to visit them. Always an array, even for one stop,
        e.g. ["chipotle on hillsborough"] or ["chipotle on hillsborough", "my house"].
        Do not look up or convert addresses yourself; every entry is resolved for you via Google Maps Text Search, biased toward the car's current location.
        Saved places: {', '.join(sorted(ADDRESSES.keys())) or 'none configured yet'}.
        If the user refers to a saved place, even loosely (different spelling, word order or extra words -- speech recognition is imperfect),
        pass the saved name EXACTLY as written above, not the user's wording.
        e.g. if "mom's house" is saved and the user says "my mom's place", pass "mom's house".
        Only for places that are not saved, pass the place/business name or address as spoken.
    car_name (str, optional): Which car. One of: {', '.join(sorted(set(CARS.keys())))}. Defaults to '{DEFAULT_CAR_NAME}' if not specified.
"""


TOOLS = [prep_car, navigate_car]
