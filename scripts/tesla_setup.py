"""
One-time setup for Tesla Fleet API access. Run manually:

    python scripts/tesla_setup.py

Does three things, in order:
  1. Gets a partner (app-level) token and registers TESLA_DOMAIN with Tesla,
     so Tesla's backend fetches and trusts the public key hosted there.
  2. Runs the one-time browser OAuth login flow to get a user access/refresh
     token for the Tesla account that owns the car, and caches it.
  3. Lists the vehicles on that account so you can copy the right VIN into .env.

Safe to re-run any time (e.g. if the refresh token cache is lost).
"""

import json
import os
import secrets
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv("TESLA_CLIENT_ID")
CLIENT_SECRET = os.getenv("TESLA_CLIENT_SECRET")
DOMAIN = os.getenv("TESLA_DOMAIN")
REDIRECT_URI = os.getenv("TESLA_REDIRECT_URI", "http://localhost:8585/callback")
FLEET_API_BASE = os.getenv("TESLA_FLEET_API_BASE", "https://fleet-api.prd.na.vn.cloud.tesla.com")
AUTH_BASE = "https://auth.tesla.com/oauth2/v3"
SCOPES = "openid offline_access vehicle_device_data vehicle_cmds vehicle_charging_cmds"

TOKEN_CACHE_PATH = Path(__file__).parent.parent / ".tesla_token_cache.json"


def _require_env():
    missing = [name for name, val in [
        ("TESLA_CLIENT_ID", CLIENT_ID),
        ("TESLA_CLIENT_SECRET", CLIENT_SECRET),
        ("TESLA_DOMAIN", DOMAIN),
    ] if not val]
    if missing:
        sys.exit(f"Missing required .env vars: {', '.join(missing)}")


def get_partner_token() -> str:
    """Client-credentials grant -- authenticates as the APP itself, no user involved."""
    resp = requests.post(
        f"{AUTH_BASE}/token",
        data={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "scope": SCOPES,
            "audience": FLEET_API_BASE,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def register_partner_account(partner_token: str) -> dict:
    """Tells Tesla to fetch/trust the public key hosted at TESLA_DOMAIN."""
    resp = requests.post(
        f"{FLEET_API_BASE}/api/1/partner_accounts",
        headers={"Authorization": f"Bearer {partner_token}"},
        json={"domain": DOMAIN},
        timeout=15,
    )
    if resp.status_code != 200:
        sys.exit(f"Partner registration failed ({resp.status_code}): {resp.text}")
    print(f"Partner account registered for domain: {DOMAIN}")
    return resp.json()


class _CallbackHandler(BaseHTTPRequestHandler):
    """Catches the OAuth redirect once and grabs ?code=... / ?state=...."""

    result = {}

    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        _CallbackHandler.result["code"] = query.get("code", [None])[0]
        _CallbackHandler.result["state"] = query.get("state", [None])[0]
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"<html><body>Login complete. You can close this tab and return to the terminal.</body></html>")

    def log_message(self, format, *args):
        pass  # silence default request logging


def get_user_tokens() -> dict:
    """3-legged OAuth: you log in via browser, we catch the redirect locally, exchange the code for tokens."""
    state = secrets.token_urlsafe(16)
    parsed_redirect = urlparse(REDIRECT_URI)
    port = parsed_redirect.port or 8585

    server = HTTPServer((parsed_redirect.hostname, port), _CallbackHandler)
    server.timeout = 5  # poll interval; overall wait bounded by the loop below

    auth_url = f"{AUTH_BASE}/authorize?" + urlencode({
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
    })
    print(f"Opening browser for Tesla login:\n{auth_url}\n")
    webbrowser.open(auth_url)

    deadline = time.time() + 180
    while time.time() < deadline and not _CallbackHandler.result.get("code"):
        server.handle_request()
    server.server_close()

    if not _CallbackHandler.result.get("code"):
        sys.exit("Timed out waiting for the Tesla login redirect.")
    if _CallbackHandler.result.get("state") != state:
        sys.exit("State mismatch on OAuth redirect -- aborting for safety.")

    code = _CallbackHandler.result["code"]
    resp = requests.post(
        f"{AUTH_BASE}/token",
        data={
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "audience": FLEET_API_BASE,
        },
        timeout=15,
    )
    resp.raise_for_status()
    tokens = resp.json()
    tokens["expires_at"] = time.time() + tokens["expires_in"]
    return tokens


def save_token_cache(tokens: dict):
    TOKEN_CACHE_PATH.write_text(json.dumps(tokens, indent=2))
    print(f"Saved tokens to {TOKEN_CACHE_PATH}")


def list_vehicles(access_token: str):
    resp = requests.get(
        f"{FLEET_API_BASE}/api/1/vehicles",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    resp.raise_for_status()
    vehicles = resp.json().get("response", [])
    if not vehicles:
        print("No vehicles found on this Tesla account.")
        return
    print("\nVehicles on this account:")
    for v in vehicles:
        print(f"  VIN: {v['vin']}    name: {v.get('display_name')}    state: {v.get('state')}")
    print("\nCopy each VIN into .env, e.g. SENSEI_TESLA_VIN and OTHER_TESLA_VIN.")


def main():
    _require_env()

    print("Step 1: Getting partner token (app-level auth)...")
    partner_token = get_partner_token()

    print("Step 2: Registering partner account / domain with Tesla...")
    register_partner_account(partner_token)

    print("Step 3: Logging in as you (browser will open)...")
    tokens = get_user_tokens()
    save_token_cache(tokens)

    print("Step 4: Listing vehicles on your account...")
    list_vehicles(tokens["access_token"])


if __name__ == "__main__":
    main()
