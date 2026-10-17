# Tesla integration — how it works today

Describes the system as built, as of 2026-10-17. For how it got here (and what was tried and
rejected along the way), see `Navigation Investigation Summary.md`, which is an append-only journal.
For navigation specifics, see `Navigation Plan.md`.

JARVIS controls the car through the **Teslemetry `tesla-fleet-api` Python library** (PyPI
`tesla-fleet-api`, v1.14.0), signing commands locally with the key the car has been paired with.
There is no proxy and no separate process: it is all in-process Python.

## The pieces

| File | Role |
|---|---|
| `src/_tesla_client.py` | All Tesla infrastructure: OAuth token refresh, the background event loop, the signed-command actions. Everything async lives here. |
| `src/services/tesla.py` | The two LLM tools, `prep_car` and `navigate_car`. Pure tool logic — no async, no library imports. |
| `src/_google_maps.py` | Places API lookups, so Google concerns stay out of `tesla.py`. |
| `scripts/tesla_setup.py` | One-time setup: OAuth browser flow, partner registration, prints VINs. Run by hand, never by `jarvis.py`. |
| `keys/private-key.pem` | Signs every command. The car trusts it because of the pairing below. |
| `keys/public-key.pem` | Served from the GitHub Pages `.well-known` URL so Tesla can fetch it. |
| `.tesla_token_cache.json` | Gitignored. Holds `access_token`, `refresh_token`, `expires_at`. |

`_`-prefixed files in `src/` are shared infrastructure, not tools. Only non-underscore modules in
`src/services/` are auto-discovered as LLM tools, which is why the Tesla client sits outside it.

## How a command reaches the car

```text
state_machine.py  TOOL_MAP[name](**args)        (synchronous, no try/except around it)
    |
tesla.py          prep_car / navigate_car       resolve car, resolve places, word the reply
    |
_tesla_client.py  ensure_awake / send_route / start_climate / set_temps
    |                 each is a sync wrapper calling _run(...)
    |             _run  -> hands the coroutine to the background loop, blocks for the result
    |
library           builds a protobuf Action(vehicleAction=...), HMAC-signs it with the private key,
                  POSTs base64 to Fleet API `signed_command`
    |
car               replies {"response": {"result": bool, "reason": str}}
```

Two details that shape everything above:

- **The sync-to-async bridge.** The library is async; JARVIS's tools are synchronous. A daemon thread
  runs one long-lived event loop (`_ensure_loop`), and `_run` submits coroutines to it with
  `asyncio.run_coroutine_threadsafe`, then blocks on the future with a 60 s timeout. The loop must be
  long-lived because the library keeps each car's handshake session and command counters on the objects
  it creates — a fresh loop per call would re-handshake every time. Measured: first command on a cold
  session = 2 round trips, every later command = 1.
- **Signing.** `createSigned(vin)` builds a `VehicleSigned`, which must be cached and reused
  (`_get_vehicle` does this) because calling it again replaces the session. Command signing is
  HMAC over the VIN, epoch, a counter and a 10 s expiry, with up to 3 retries on wait/epoch faults.

## Error handling, and the one real gotcha

The library's `TeslaFleetError` derives from **`BaseException`, not `Exception`**, so a plain
`except Exception` does not catch it. Since `state_machine.py` calls tools with no try/except, an
uncaught one would break JARVIS's turn instead of producing a spoken error.

`_run` therefore translates: it catches `TeslaFleetError` and timeouts and re-raises them as
`TeslaError(Exception)`, keeping the original as `__cause__`. **Consequence: tools in `services/`
use a plain `except Exception as e` and never import anything from the library.** Catching
`BaseException` instead was rejected — it would also swallow Ctrl+C.

Every tool returns an error dict and never raises, because nothing upstream catches.

## Adding a new car command

1. Find the library method and its parameters — read
   `.venv313/Lib/site-packages/tesla_fleet_api/tesla/vehicle/commands.py`, or run
   `inspect.signature(VehicleSigned.<command>)`. Do not guess; several commands take no arguments
   because the library hardcodes the protobuf field (e.g. `auto_conditioning_start`).
2. In `_tesla_client.py`, add an **async core taking a `vin`** that does the whole job, and a
   **sync wrapper** that calls `_run` on it. Return `(ok, reason)` via the shared `_result()` helper.
   Do not add extra layers between the two — that was deliberately collapsed (journal entry 4).
3. Commands do **not** wake the car themselves. The tool calls `ensure_awake(vin)` first, so it can
   word its own "didn't wake up" message. (`ensure_awake` only sends a wake if the car isn't already
   online, to avoid burning rate limits.)
4. In `services/tesla.py`, add the thin tool: resolve the car, call the client, return a
   `{"status", "message"}` dict. Set `__doc__` post-hoc with an f-string if it needs runtime config
   (saved names, car names) — that docstring is what the LLM reads. Add it to `TOOLS`.
5. Test offline by stubbing the client's async cores (not `_run`), so the real loop and error
   translation are exercised. Then one live call.

## `prep_car`

`prep_car(car_name=None, temp=None)` → `ensure_awake` → `start_climate(vin)` → `set_temps` if a
temperature was given. Fahrenheit-to-Celsius conversion happens in the tool: the car works in
Celsius, the user speaks Fahrenheit. Verified live at 72 °F.

The error messages distinguish the partial-failure case on purpose: if climate starts but the
temperature can't be set, the message says climate *is* on, so JARVIS doesn't report a total failure.

## Setup (one-time, manual — already done)

These steps are history, kept because they would need redoing on a new machine or Tesla account.

1. **Tesla developer app** at developer.tesla.com, using the account that owns the car (they must
   match — there is no separate consent flow at the free tier). Redirect URI
   `http://localhost:8585/callback`, domain `<username>.github.io`, scopes
   `openid offline_access vehicle_device_data vehicle_cmds vehicle_charging_cmds`.
   Later addition: `vehicle_location` is required for GPS data (Tesla added it Nov 2024) — a token
   cached before that scope existed returns no location.
2. **Public key hosting**: `https://<domain>/.well-known/appspecific/com.tesla.3p.public-key.pem`
   is fetched with no path prefix, so it must be a GitHub Pages *user* site, not a project site.
3. **OAuth + partner registration**: `scripts/tesla_setup.py` gets a partner token, calls
   `POST /api/1/partner_accounts` with the domain, runs the browser flow, and writes the token cache.
4. **Pair the key with the car**: QR code encoding `https://tesla.com/_ak/<domain>`, then in the
   Tesla app near the car, Locks → Add Key → Set Up Using QR Code. This is about the car trusting the
   *signing key* and is independent of OAuth.

**Refresh-token rotation is the most likely "worked yesterday, broken today" failure.** Tesla issues a
new refresh token on every refresh and invalidates the old one, so `_tesla_client.py` writes the cache
file immediately on each refresh. A lost rotated token means re-running `tesla_setup.py`'s browser flow.
The library's own `TeslaFleetOAuth` was deliberately not used: it keeps the rotated token in memory only.

**Region** must match the car: `TESLA_FLEET_API_BASE` defaults to the NA host. A mismatch fails
confusingly later, not at auth time.

## Environment

Python **3.13** is required by the library. `.venv313` is the only working environment — the old 3.12
`.venv` can no longer start JARVIS, since `services/__init__.py` imports every tool module. The name
keeps the version visible. 3.14 is blocked by spacy. A rebuilt venv needs the openwakeword `.onnx`
model files copied in by hand. Recreate with:

```powershell
uv venv --python 3.13 .venv313
uv pip install --python .venv313\Scripts\python.exe -r requirements.txt
```

## Retired: the Go `vehicle-command` proxy

Until 2026-10-17 the signing was delegated to Tesla's official `tesla-http-proxy` (Go), launched as a
subprocess by `jarvis.py`, with `tesla.py` POSTing to `https://localhost:4443` using `verify=False` for
its self-signed cert. The Python library replaced it: same signing, one less process, one less language,
and it supports `navigation_waypoints_request`, which the proxy had no case for.

Deleted: `src/_tesla_proxy.py`, `keys/proxy-tls.crt`, `keys/proxy-tls.key`,
`bin/tesla-http-proxy.exe`, and the launch code in `jarvis.py`. Kept: `bin/tesla-control.exe`, Tesla's
ad-hoc CLI, still handy for poking the car by hand. If the proxy is ever needed again:
`go install github.com/teslamotors/vehicle-command/cmd/tesla-http-proxy@latest`.

## Appendix — vehicle-command catalog (for future tools)

Originally collected as proxy endpoint names; the library exposes the same set as methods on
`VehicleSigned` (check the exact signature before use — see "Adding a new car command").

**Climate & cabin comfort**
`auto_conditioning_start`, `auto_conditioning_stop`, `set_temps`, `set_preconditioning_max`,
`set_climate_keeper_mode`, `set_cop_temp`, `set_cabin_overheat_protection`, `set_bioweapon_mode`,
`remote_seat_heater_request`, `remote_seat_cooler_request`, `remote_auto_seat_climate_request`,
`remote_steering_wheel_heater_request`, `remote_steering_wheel_heat_level_request`,
`remote_auto_steering_wheel_heat_climate_request`, `add_precondition_schedule`,
`remove_precondition_schedule`

**Charging**
`charge_start`, `charge_stop`, `charge_standard`, `charge_max_range`, `set_charge_limit`,
`set_charging_amps`, `charge_port_door_open`, `charge_port_door_close`, `add_charge_schedule`,
`remove_charge_schedule`, `set_scheduled_charging`, `set_scheduled_departure`

**Locks, doors & physical access**
`door_lock`, `door_unlock`, `actuate_trunk`, `window_control`, `sun_roof_control`, `remote_start_drive`

**Lights, horn & attention-getters**
`flash_lights`, `honk_horn`, `remote_boombox`, `trigger_homelink`

**Media & audio**
`media_toggle_playback`, `media_next_track`, `media_prev_track`, `media_next_fav`, `media_prev_fav`,
`media_volume_up`, `media_volume_down`, `adjust_volume`

**Navigation**
`navigation_request`, `navigation_gps_request`, `navigation_sc_request`,
`navigation_waypoints_request` (the one in use), `upcoming_calendar_entries`

**Security & access control**
`set_sentry_mode`, `set_valet_mode`, `reset_valet_pin`, `guest_mode`, `set_pin_to_drive`,
`reset_pin_to_drive_pin`, `clear_pin_to_drive_admin`

**Parental & speed controls**
`parental_controls_activate`, `parental_controls_deactivate`, `parental_controls_clear_pin_admin`,
`parental_controls_enable_setting`, `parental_controls_set_speed_limit`, `speed_limit_activate`,
`speed_limit_deactivate`, `speed_limit_set_limit`, `speed_limit_clear_pin`,
`speed_limit_clear_pin_admin`

**Software & system**
`schedule_software_update`, `cancel_software_update`, `erase_user_data`, `set_vehicle_name`

**Candidates worth building next**, by effect per line of code:

1. `remote_boombox` — plays a sound from the external speaker; nothing else like it in any other
   smart-home integration.
2. `honk_horn` + `flash_lights` — no parameters, trivial, a good "where's my car".
3. `remote_seat_heater_request` — natural extension of `prep_car`.
4. `set_sentry_mode` — fits the persona.
5. `sun_roof_control` / `window_control` — fun but safety-sensitive (pinch risk); read the required
   state checks closely first.

Note that a few commands route through `_sendVehicleSecurity` rather than `_sendInfotainment` (locks
and trunk, broadly), which the library handles internally but which can behave differently on retry.
