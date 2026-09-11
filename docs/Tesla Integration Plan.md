# Tesla Fleet API integration — "JARVIS, prep my car"

## Context

JARVIS already controls Spotify, system volume, and Home Assistant lights through a plugin pattern: any `src/services/*.py` module that exports a module-level `TOOLS` list is auto-discovered and made callable by the LLM (`src/services/__init__.py`), with zero changes needed to `state_machine.py`. Adding Tesla climate control follows the same pattern, but Tesla's Fleet API has real external setup overhead that Spotify/HA don't: an OAuth app registration, a publicly-hosted key file the car uses to trust command signatures, and Tesla's own signing proxy (modern vehicles reject unsigned climate commands sent as plain bearer-token REST calls).

A keypair (`keys/private-key.pem` / `keys/public-key.pem`) was already generated in a prior commit anticipating this — verified it's in the exact SEC1 P-256 format Tesla's tooling requires, so **no regeneration needed**.

Goal for v1: a single `prep_car(temp: int = None)` tool that wakes the car, turns on climate control, and optionally sets a target temperature — triggered by phrases like "JARVIS, prep my car."

Decisions already made (not open questions):
- No domain yet → use a free **GitHub Pages user site** to host the required public-key file.
- Signing → use Tesla's official **`vehicle-command` Go proxy**, not a custom Python signer. JARVIS's Python code just calls it over localhost via `requests`, same shape as `home-automation.py` calling Home Assistant.
- Scope → climate on + set temp only (no defrost/seat heat for v1).

---

## Phase 1 — Tesla developer app [MANUAL]

1. Register an app at developer.tesla.com using the Tesla account that owns the car (must match — see Risks).
2. Redirect URI: `http://localhost:8585/callback`. Domain: `<your-github-username>.github.io` (ties into Phase 2). Scopes: `openid offline_access vehicle_device_data vehicle_cmds vehicle_charging_cmds`.
3. Record Client ID/Secret → new `.env` vars `TESLA_CLIENT_ID`, `TESLA_CLIENT_SECRET`, `TESLA_DOMAIN`.

## Phase 2 — Host the public key via GitHub Pages [MANUAL]

Tesla fetches `https://<domain>/.well-known/appspecific/com.tesla.3p.public-key.pem` with no path prefix, so it must be a **user root Pages site** (`<username>.github.io`), not a project-pages repo.

1. Create/reuse a public repo named exactly `<username>.github.io`; add `.well-known/appspecific/com.tesla.3p.public-key.pem` with the contents of this repo's `keys/public-key.pem`.
2. Enable Pages (root, main branch). Confirm the URL serves raw PEM text in a browser before moving on (allow a few minutes for propagation).

## Phase 3 — One-time OAuth + partner registration [CODE + MANUAL]

New script `scripts/tesla_setup.py` (top-level `scripts/`, run manually once — not invoked by `jarvis.py`):
1. Get a **partner token** (`client_credentials` grant, `auth.tesla.com/oauth2/v3/token`).
2. `POST {fleet-api-base}/api/1/partner_accounts` with `{"domain": "<username>.github.io"}` — this tells Tesla to fetch/cache your public key. Must succeed before Phase 4 pairing works.
3. Run the 3-legged **user** OAuth flow: spin up a throwaway `http.server` on `localhost:8585/callback`, open the Tesla authorize URL in the browser (`[MANUAL]`: user logs in and clicks Allow), catch the redirect, exchange `code` for `access_token`/`refresh_token`.
4. Persist tokens to a new gitignored `.tesla_token_cache.json` at repo root (`{access_token, refresh_token, expires_at}`).
5. Call `GET /api/1/vehicles`, print VIN(s). `[MANUAL]`: copy the right one into `.env` as `TESLA_VIN`.

Region base URL as one shared env var read by both this script and `tesla.py`: `TESLA_FLEET_API_BASE=https://fleet-api.prd.na.vn.cloud.tesla.com` (swap to `.eu.` if outside NA/Oceania — see Risks).

**Refresh-token rotation**: Tesla issues a *new* refresh token on every refresh call and invalidates the old one. `tesla.py`'s refresh logic must overwrite the cache file immediately after each refresh, not just the access token — losing a rotated refresh token means re-running this script's browser flow.

## Phase 4 — Pair the key with the physical vehicle [MANUAL]

Independent of the OAuth token — this is about the car trusting your *signing key*.
1. Generate a QR code encoding `https://tesla.com/_ak/<username>.github.io`.
2. In the Tesla phone app, near the car: **Locks → Add Key → Set Up Using QR Code**, scan it.
3. Confirm the key shows as added on the car/app.

## Phase 5 — Run Tesla's `vehicle-command` Go proxy [MANUAL install + CODE launcher]

1. Install Go; `go install github.com/teslamotors/vehicle-command/cmd/tesla-http-proxy@latest` (and `tesla-control` for ad-hoc testing). Copy the built exe into a new `bin/` folder (gitignored, not committed).
2. Generate a **separate** self-signed localhost TLS cert for the proxy's own HTTPS transport (`keys/proxy-tls.key` gitignored, `keys/proxy-tls.crt` committed) — distinct from the Tesla signing keypair.
3. New `scripts/start_tesla_proxy.ps1` launches `tesla-http-proxy.exe` with `-tls-key`, `-cert`, `-key-file keys/private-key.pem`, `-port 4443`.
4. Run it as a long-lived background process the user starts once (Startup-folder shortcut), not something `jarvis.py` supervises — it's a stable local service, and there's no subprocess-orchestration code in this repo to build on for v1. `tesla.py` does a cheap health check + auto-launch fallback before each call, but that's a safety net, not the primary way to run it.
5. `.env` addition: `TESLA_PROXY_BASE=https://localhost:4443`.

## Phase 6 — `src/services/tesla.py` [CODE]

Follows this repo's existing tool conventions exactly (see `home-automation.py`: `{"status", "message"}` dict returns, post-hoc `__doc__ = f"""..."""` assignment so the docstring can embed runtime config, `TOOLS = [...]` export at the bottom).

```python
import os, requests
from dotenv import load_dotenv
load_dotenv()

TESLA_VIN = os.getenv("TESLA_VIN")
FLEET_API_BASE = os.getenv("TESLA_FLEET_API_BASE", "https://fleet-api.prd.na.vn.cloud.tesla.com")
PROXY_BASE = os.getenv("TESLA_PROXY_BASE", "https://localhost:4443")
TOKEN_CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", "..", ".tesla_token_cache.json")

# _load_cache() / _save_cache() / _refresh_access_token() / _get_valid_access_token()
#   -> implements the rotate-and-persist refresh logic from Phase 3.
# _ensure_proxy_running() -> health-check PROXY_BASE, subprocess.Popen fallback launch.
# _wake_and_wait(headers, timeout_s=30) -> POST wake_up, poll vehicle state until "online".

def prep_car(temp: int = None) -> dict:
    if not TESLA_VIN:
        return {"status": "error", "message": "No Tesla VIN configured."}
    try:
        access_token = _get_valid_access_token()
    except Exception as e:
        return {"status": "error", "message": f"Tesla authentication failed: {e}"}

    headers = {"Authorization": f"Bearer {access_token}"}
    _ensure_proxy_running()
    if not _wake_and_wait(headers):
        return {"status": "error", "message": "The vehicle did not wake up in time, Sir."}

    r = requests.post(f"{PROXY_BASE}/api/1/vehicles/{TESLA_VIN}/command/auto_conditioning_start",
                       headers=headers, verify=False, timeout=15)
    if r.status_code != 200 or not r.json().get("response", {}).get("result"):
        return {"status": "error", "message": "Failed to start climate control."}

    if temp is not None:
        celsius = round((temp - 32) * 5 / 9, 1)
        r = requests.post(f"{PROXY_BASE}/api/1/vehicles/{TESLA_VIN}/command/set_temps",
                           json={"driver_temp": celsius, "passenger_temp": celsius},
                           headers=headers, verify=False, timeout=15)
        if r.status_code != 200 or not r.json().get("response", {}).get("result"):
            return {"status": "error", "message": "Climate is on, but I could not set the target temperature."}

    temp_msg = f" and set to {temp}°F" if temp is not None else ""
    return {"status": "success", "message": f"Climate control is on{temp_msg}, Sir."}

prep_car.__doc__ = f"""Wakes the user's Tesla and turns on climate control, optionally setting a target cabin temperature.
Call this when the user asks to warm up / cool down / prep / get the car ready.
Args:
    temp (int, optional): Target cabin temperature in degrees Fahrenheit. If omitted, uses the vehicle's last-used setting.
Vehicle: {TESLA_VIN or "not configured"}
"""

TOOLS = [prep_car]
```

Notes:
- Fahrenheit-in → Celsius conversion happens inside the function, not left to the LLM, since this codebase has no other unit convention to anchor "72 degrees" to.
- No new `_`-prefixed YAML config (unlike `_HA-config.yaml`) — v1 is a single hardcoded VIN from `.env`, a config file would be pure overhead until multi-vehicle support exists.
- All vehicle calls route through the local proxy uniformly (not direct-to-`fleet-api`), so there's no need to special-case which calls require signing.

## Phase 7 — Supporting file updates [CODE]

- **`.env.example`**: add `TESLA_CLIENT_ID`, `TESLA_CLIENT_SECRET`, `TESLA_DOMAIN`, `TESLA_VIN`, `TESLA_FLEET_API_BASE`, `TESLA_PROXY_BASE`.
- **`.gitignore`**: add `.tesla_token_cache.json`, `keys/proxy-tls.key`, `bin/*.exe`.
- **`requirements.txt`**: confirmed **UTF-16LE** encoded — edit with a tool that preserves that encoding (or deliberately convert the whole file to UTF-8 in the same change, not silently mix encodings). No new crypto/JWT packages needed — signing is delegated entirely to the Go proxy, and OAuth is plain `requests`/wall-clock expiry tracking. Do add the pre-existing missing `pyyaml` (used by `home-automation.py` but currently unlisted).
- **`src/prompts/jarvis-prompt.txt`**: extend the tools sentence to mention Tesla/vehicle climate control, and add a short rule noting that waking the car can take up to ~30s so JARVIS shouldn't claim success early.

## Phase 8 — Verification

1. **Standalone, before touching JARVIS**: confirm the `.well-known` URL resolves; run `tesla_setup.py` and confirm the token cache is populated; start the proxy and manually `wake_up` → poll for `"state":"online"` → `auto_conditioning_start` → `set_temps` via PowerShell `Invoke-RestMethod` (or `tesla-control`), physically confirming the car's climate responds. Force one refresh-token rotation and confirm the cache file's `refresh_token` actually changes.
2. **Full voice flow**: start the proxy, run `python src/jarvis.py`, say "JARVIS, prep my car" and "...and set it to 72 degrees" — confirm correct tool args in logs, confirm JARVIS never claims success without a successful tool result (test a deliberate failure path, e.g. wrong proxy port, and confirm it reports the failure). Test cold-start: stop the proxy, restart JARVIS, confirm the auto-launch fallback (or a clear error) kicks in.

## Risks to keep in mind

- **Account match**: the car must be on the same Tesla account as the developer app — no separate consent flow exists at the free tier to authorize a different account's vehicle.
- **Refresh rotation**: the most likely "worked yesterday, broken today" failure — any stale cached refresh token (crash mid-refresh, second process reading old cache) breaks all Tesla calls until `tesla_setup.py` is re-run.
- **Vehicle/firmware support**: key pairing (Locks → Add Key) requires a sufficiently modern infotainment system — confirm the car supports it before investing in Phases 2–5.
- **Region mismatch**: `TESLA_FLEET_API_BASE`/`audience` must match the vehicle's actual region (NA/Oceania vs EU/ME/Africa) or calls fail confusingly later, not at auth time — kept as one shared env var to avoid drift.
- **Proxy TLS**: `verify=False` is fine for the local self-signed proxy only — never relax it for calls to `auth.tesla.com`/`fleet-api.*`.

## Critical files

- `src/services/tesla.py` (new)
- `scripts/tesla_setup.py` (new)
- `scripts/start_tesla_proxy.ps1` (new)
- `.env.example`, `.gitignore`, `requirements.txt`, `src/prompts/jarvis-prompt.txt` (edits)

## Appendix — full vehicle-command endpoint catalog (for future tools)

All commands available via `POST /api/1/vehicles/{vin}/command/{name}` through the proxy, grouped by function, for picking what to build next after `prep_car`.

**Climate & Cabin Comfort**
`auto_conditioning_start`, `auto_conditioning_stop`, `set_temps`, `set_preconditioning_max`, `set_climate_keeper_mode`, `set_cop_temp`, `set_cabin_overheat_protection`, `set_bioweapon_mode`, `remote_seat_heater_request`, `remote_seat_cooler_request`, `remote_auto_seat_climate_request`, `remote_steering_wheel_heater_request`, `remote_steering_wheel_heat_level_request`, `remote_auto_steering_wheel_heat_climate_request`, `add_precondition_schedule`, `remove_precondition_schedule`

**Charging**
`charge_start`, `charge_stop`, `charge_standard`, `charge_max_range`, `set_charge_limit`, `set_charging_amps`, `charge_port_door_open`, `charge_port_door_close`, `add_charge_schedule`, `remove_charge_schedule`, `set_scheduled_charging`, `set_scheduled_departure`

**Locks, Doors & Physical Access**
`door_lock`, `door_unlock`, `actuate_trunk`, `window_control`, `sun_roof_control`, `remote_start_drive`

**Lights, Horn & Attention-Getters**
`flash_lights`, `honk_horn`, `remote_boombox`, `trigger_homelink`

**Media & Audio**
`media_toggle_playback`, `media_next_track`, `media_prev_track`, `media_next_fav`, `media_prev_fav`, `media_volume_up`, `media_volume_down`, `adjust_volume`

**Navigation**
`navigation_request`, `navigation_gps_request`, `navigation_sc_request`, `navigation_waypoints_request`, `upcoming_calendar_entries`

**Security & Access Control**
`set_sentry_mode`, `set_valet_mode`, `reset_valet_pin`, `guest_mode`, `set_pin_to_drive`, `reset_pin_to_drive_pin`, `clear_pin_to_drive_admin`

**Parental & Speed Controls**
`parental_controls_activate`, `parental_controls_deactivate`, `parental_controls_clear_pin_admin`, `parental_controls_enable_setting`, `parental_controls_set_speed_limit`, `speed_limit_activate`, `speed_limit_deactivate`, `speed_limit_set_limit`, `speed_limit_clear_pin`, `speed_limit_clear_pin_admin`

**Software & System**
`schedule_software_update`, `cancel_software_update`, `erase_user_data`, `set_vehicle_name`

**Best candidates to build next, ranked by wow-factor per line of code:**

1. `remote_boombox` — plays a sound from the car's external speaker; no cabin needed, nothing else like it in any other smart-home integration.
2. `honk_horn` + `flash_lights` — no params, trivial to implement, good "where's my car" party trick.
3. `navigation_request` — "JARVIS, send this address to my car," genuinely useful rather than just a gimmick; pairs well with the `follow_up` tool for getting a destination.
4. `remote_seat_heater_request` — natural extension of `prep_car` ("prep my car and turn on my seat heater").
5. `set_sentry_mode` — fits the Iron-Man-security-system persona well.
6. `sun_roof_control` / `window_control` — fun but safety-sensitive (pinch risk); check the API docs' required state checks closely before wiring these up, more so than the others above.
