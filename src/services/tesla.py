import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

from _tesla_proxy import PROXY_BASE

load_dotenv()

CLIENT_ID = os.getenv("TESLA_CLIENT_ID")
AUTH_BASE = "https://auth.tesla.com/oauth2/v3"

TOKEN_CACHE_PATH = Path(__file__).resolve().parent.parent.parent / ".tesla_token_cache.json"

DEFAULT_CAR_NAME = "sensei"
CARS = {
    "sensei": os.getenv("SENSEI_TESLA_VIN"),
    "parent's car": os.getenv("OTHER_TESLA_VIN"),
    "mom's car": os.getenv("OTHER_TESLA_VIN"),
    "dad's car": os.getenv("OTHER_TESLA_VIN"),
}


def _resolve_car(car_name: str = None):
    """Returns (display_name, vin), or (None, None) if car_name isn't recognized."""
    if not car_name:
        return DEFAULT_CAR_NAME, CARS[DEFAULT_CAR_NAME]
    key = car_name.strip().lower()
    if key not in CARS or not CARS[key]:
        return None, None
    return key, CARS[key]


def _load_token_cache() -> dict:
    if not TOKEN_CACHE_PATH.exists():
        raise RuntimeError("No Tesla token cache found -- run scripts/tesla_setup.py first.")
    return json.loads(TOKEN_CACHE_PATH.read_text())


def _save_token_cache(tokens: dict):
    TOKEN_CACHE_PATH.write_text(json.dumps(tokens, indent=2))


def _refresh_access_token(refresh_token: str) -> dict:
    """Tesla rotates the refresh token on every use -- caller must persist the new one immediately."""
    resp = requests.post(
        f"{AUTH_BASE}/token",
        data={
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "refresh_token": refresh_token,
        },
        timeout=15,
    )
    resp.raise_for_status()
    tokens = resp.json()
    tokens["expires_at"] = time.time() + tokens["expires_in"]
    return tokens


def _get_valid_access_token() -> str:
    tokens = _load_token_cache()
    if tokens.get("expires_at", 0) - time.time() < 300:  # refresh if expiring within 5 min
        tokens = _refresh_access_token(tokens["refresh_token"])
        _save_token_cache(tokens)
    return tokens["access_token"]


def _wake_and_wait(vin: str, headers: dict, timeout_s: float = 30.0) -> bool:
    """Only sends a wake_up command if the car isn't already online, to avoid burning rate limits."""
    r = requests.get(f"{PROXY_BASE}/api/1/vehicles/{vin}", headers=headers, verify=False, timeout=15)
    if r.status_code == 200 and r.json().get("response", {}).get("state") == "online":
        return True

    requests.post(f"{PROXY_BASE}/api/1/vehicles/{vin}/wake_up", headers=headers, verify=False, timeout=15)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        time.sleep(2)
        r = requests.get(f"{PROXY_BASE}/api/1/vehicles/{vin}", headers=headers, verify=False, timeout=15)
        if r.status_code == 200 and r.json().get("response", {}).get("state") == "online":
            return True
    return False


def prep_car(car_name: str = None, temp: int = None) -> dict:

    name, vin = _resolve_car(car_name)
    if vin is None:
        known = ", ".join(sorted(set(CARS.keys())))
        return {"status": "error", "message": f"I don't recognize a car called '{car_name}', Sir. Known cars: {known}."}

    try:
        access_token = _get_valid_access_token()
    except Exception as e:
        return {"status": "error", "message": f"Tesla authentication failed: {e}"}

    headers = {"Authorization": f"Bearer {access_token}"}

    if not _wake_and_wait(vin, headers):
        return {"status": "error", "message": f"{name} did not wake up in time, Sir."}

    r = requests.post(
        f"{PROXY_BASE}/api/1/vehicles/{vin}/command/auto_conditioning_start",
        headers=headers, verify=False, timeout=15,
    )
    if r.status_code != 200 or not r.json().get("response", {}).get("result"):
        return {"status": "error", "message": f"Failed to start climate control on {name}."}

    if temp is not None:
        celsius = round((temp - 32) * 5 / 9, 1)
        r = requests.post(
            f"{PROXY_BASE}/api/1/vehicles/{vin}/command/set_temps",
            json={"driver_temp": celsius, "passenger_temp": celsius},
            headers=headers, verify=False, timeout=15,
        )
        if r.status_code != 200 or not r.json().get("response", {}).get("result"):
            return {"status": "error", "message": f"Climate is on for {name}, but I could not set the target temperature."}

    temp_msg = f" and set to {temp}°F" if temp is not None else ""
    return {"status": "success", "message": f"Climate control is on{temp_msg} for {name}."}


prep_car.__doc__ = f"""Wakes a Tesla and turns on climate control, optionally setting a target cabin temperature.
Call this when the user asks to warm up / cool down / prep / get their car ready.
Args:
    car_name (str, optional): Which car. One of: {', '.join(sorted(set(CARS.keys())))}. Defaults to '{DEFAULT_CAR_NAME}' if not specified.
    temp (int, optional): Target cabin temperature in degrees Fahrenheit. If omitted, uses the vehicle's last-used setting.
"""


TOOLS = [prep_car]
