import asyncio
import atexit
import json
import logging
import os
import threading
import time
from pathlib import Path

import aiohttp
import requests
from dotenv import load_dotenv
from tesla_fleet_api import TeslaFleetApi
from tesla_fleet_api.exceptions import TeslaFleetError
from tesla_fleet_api.tesla.vehicle.signed import VehicleSigned

load_dotenv()

logger = logging.getLogger(__name__)

CLIENT_ID = os.getenv("TESLA_CLIENT_ID")
AUTH_BASE = "https://auth.tesla.com/oauth2/v3"
FLEET_API_BASE = os.getenv("TESLA_FLEET_API_BASE", "https://fleet-api.prd.na.vn.cloud.tesla.com")

_REPO_ROOT = Path(__file__).resolve().parent.parent
TOKEN_CACHE_PATH = _REPO_ROOT / ".tesla_token_cache.json"
PRIVATE_KEY = _REPO_ROOT / "keys" / "private-key.pem"

_loop: asyncio.AbstractEventLoop | None = None
_api: TeslaFleetApi | None = None
_start_lock = threading.Lock()


class TeslaError(Exception):
    """The one error this module raises for a failed Tesla call. The library's own
    TeslaFleetError derives from BaseException, so `except Exception` would miss it;
    _run() re-raises it as this instead.
    """


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


def get_valid_access_token() -> str:
    tokens = _load_token_cache()
    if tokens.get("expires_at", 0) - time.time() < 300:  # refresh if expiring within 5 min
        tokens = _refresh_access_token(tokens["refresh_token"])
        _save_token_cache(tokens)
    return tokens["access_token"]


def _ensure_loop() -> asyncio.AbstractEventLoop:
    """Starts the background event loop on first use. The library keeps its session state
    (handshakes, counters) on the objects it creates, so every call into it has to run on
    this one loop -- see _run().
    """
    global _loop
    with _start_lock:
        if _loop is None:
            _loop = asyncio.new_event_loop()
            threading.Thread(target=_loop.run_forever, name="tesla-loop", daemon=True).start()
            atexit.register(_shutdown)
    return _loop


def _shutdown():
    try:
        if _api is not None:
            asyncio.run_coroutine_threadsafe(_api.session.close(), _loop).result(timeout=5)
    finally:
        _loop.call_soon_threadsafe(_loop.stop)


def _run(coro, timeout_s: float = 60.0):
    """Runs a coroutine on the background loop and blocks until it finishes -- the bridge
    between JARVIS's synchronous tools and the async library. Cancels the coroutine after
    timeout_s, so a hung request can't freeze JARVIS. Library failures and timeouts come
    out as TeslaError, which (unlike TeslaFleetError) a plain `except Exception` catches.
    """
    future = asyncio.run_coroutine_threadsafe(coro, _ensure_loop())
    try:
        return future.result(timeout_s)
    except TeslaFleetError as e:
        raise TeslaError(str(e) or type(e).__name__) from e
    except TimeoutError:
        future.cancel()
        raise TeslaError(f"timed out after {timeout_s:g} s")


async def _access_token() -> str:
    """What the library calls before each request. Off-loop because a refresh uses requests."""
    return await asyncio.to_thread(get_valid_access_token)


async def _get_api() -> TeslaFleetApi:
    global _api
    if _api is None:
        if not PRIVATE_KEY.exists():
            # get_private_key() would silently generate a new key here, one the car doesn't trust
            raise FileNotFoundError(f"Tesla private key not found at {PRIVATE_KEY}")
        api = TeslaFleetApi(aiohttp.ClientSession(), access_token=_access_token, server=FLEET_API_BASE)
        await api.get_private_key(str(PRIVATE_KEY))
        _api = api
        logger.info("Tesla client ready.")
    return _api


async def _get_vehicle(vin: str) -> VehicleSigned:
    """Returns the signed vehicle for `vin`, creating it on first use. It has to be reused:
    it holds the handshake sessions, and createSigned() would replace them with a fresh
    vehicle (and a new handshake) every time.
    """
    api = await _get_api()
    vehicle = api.vehicles.get(vin)
    if vehicle is None:
        vehicle = api.vehicles.createSigned(vin)
    return vehicle


async def _is_online(vehicle: VehicleSigned) -> bool:
    try:
        body = await vehicle.vehicle()
    except TeslaFleetError:
        return False
    return (body.get("response") or {}).get("state") == "online"


async def _ensure_awake(vin: str, timeout_s: float = 30.0) -> bool:
    """Only sends a wake_up command if the car isn't already online, to avoid burning rate limits."""
    vehicle = await _get_vehicle(vin)
    if await _is_online(vehicle):
        return True

    await vehicle.wake_up()
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        await asyncio.sleep(2)
        if await _is_online(vehicle):
            return True
    return False


async def _locate(vin: str) -> tuple[float, float] | None:
    """Returns the car's current (lat, lon), or None if unavailable -- e.g. if the
    cached token predates the `vehicle_location` scope Tesla now requires for GPS
    data (added Nov 2024). Callers should treat None as "no location bias available"
    rather than a hard failure.
    """
    vehicle = await _get_vehicle(vin)
    try:
        body = await vehicle.vehicle_data(["location_data"])
    except TeslaFleetError:
        return None
    drive_state = (body.get("response") or {}).get("drive_state") or {}
    lat, lon = drive_state.get("latitude"), drive_state.get("longitude")
    if lat is None or lon is None:
        return None
    return lat, lon


async def _send_route(vin: str, place_ids: list[str]) -> dict:
    vehicle = await _get_vehicle(vin)
    return await vehicle.navigation_waypoints_request(",".join(f"refId:{pid}" for pid in place_ids))


def _result(body: dict) -> tuple[bool, str | None]:
    """A signed command's reply is always {"response": {"result": bool, "reason": str}}.
    `reason` is None when `result` is True.
    """
    response = body.get("response") or {}
    ok = bool(response.get("result"))
    return ok, (None if ok else response.get("reason"))


async def _start_climate(vin: str, on: bool) -> tuple[bool, str | None]:
    vehicle = await _get_vehicle(vin)
    if on:
        return _result(await vehicle.auto_conditioning_start())
    return _result(await vehicle.auto_conditioning_stop())


async def _set_temps(vin: str, driver_c: float, passenger_c: float) -> tuple[bool, str | None]:
    vehicle = await _get_vehicle(vin)
    return _result(await vehicle.set_temps(driver_c, passenger_c))


# Synchronous entry points for the tools in services/. Everything above is async and lives on
# the background loop; these hide that. Each raises TeslaError on failure.

def ensure_awake(vin: str) -> bool:
    """Wakes the car only if it isn't already online. Returns False if it didn't come online in time.
    The commands below don't wake the car themselves, so call this first.
    """
    return _run(_ensure_awake(vin))


def locate(vin: str) -> tuple[float, float] | None:
    """Returns the car's (lat, lon), or None if it won't share it -- callers should treat that as
    "no location available", not a failure. Never wakes the car: a sleeping car also gives None.
    """
    return _run(_locate(vin))


def send_route(vin: str, place_ids: list[str]) -> dict:
    """Sends all the stops (Google place IDs) as one route, in order. The car starts
    navigating on its own. Returns the raw response body: {"response": {"result": bool, "reason": str}}.
    """
    return _run(_send_route(vin, place_ids))


def start_climate(vin: str, on: bool = True) -> tuple[bool, str | None]:
    """Turns climate control on (or off). Returns (ok, reason); reason is None on success."""
    return _run(_start_climate(vin, on))


def set_temps(vin: str, driver_c: float, passenger_c: float) -> tuple[bool, str | None]:
    """Sets cabin temperature in Celsius. Returns (ok, reason); reason is None on success."""
    return _run(_set_temps(vin, driver_c, passenger_c))
