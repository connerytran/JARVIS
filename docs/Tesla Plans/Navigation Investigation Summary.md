# JARVIS — Tesla integration & navigation investigation: state summary

As of 2026-09-19. Written to hand off context to a new session or person. Contains no secrets —
env var *names* only.

## 1. The project in one paragraph

JARVIS is a local voice assistant (Python, Windows, Ollama `qwen2.5:7b`, `statemachine` library:
idle → listening → thinking → executing → speaking). Tools are plain Python functions in
`src/services/*.py`; any module exporting a `TOOLS` list is auto-discovered by
`src/services/__init__.py` (files starting with `_` are skipped). Ollama's Python client turns each
function into a tool schema from its type hints and docstring, and it **flattens every parameter to
just a top-level type plus description** — no nested list/dict structure survives, so the docstring
is the only guidance the model gets for complex parameters. Keep tool parameters simple.

Convention the owner has stated: `src/services/` holds only LLM-callable tools (plus their private
`_`-prefixed config files). Shared infrastructure lives directly in `src/` (`_tesla_proxy.py`,
`_google_maps.py`). Also: prefer in-code defaults over new `.env` entries, and **ask before creating
or deleting functions/files/modules**.

## 2. Repository state

- Branch `4-state-machine`, HEAD `c754018` ("Added in a list of the endpoints"). **Nothing from the
  navigation work is committed.**
- Modified (uncommitted): `.env.example`, `.gitignore`, `scripts/tesla_setup.py`,
  `src/services/tesla.py`.
- Moved: `docs/Tesla Integration Plan.md` → `docs/Tesla Plans/Tesla Integration Plan.md`.
- New, untracked: `docs/Tesla Plans/` (this file and `Navigation Plan.md`), `src/_google_maps.py`.
- Gitignored local-only files: `.env`, `.tesla_token_cache.json`, `bin/` (Go proxy binaries),
  `keys/private-key.pem`, `keys/proxy-tls.key`, `src/services/_HA-config.yaml`,
  `src/services/_tesla-addresses.yaml`.
- Test scripts written during the investigation live in the session scratchpad (a temp directory,
  **not in the repo**) and may be lost. Everything they established is recorded below.

## 3. Tesla integration — what exists

| Piece | Status |
|---|---|
| Developer app, OAuth, partner registration, key hosted on GitHub Pages | Done (`scripts/tesla_setup.py`) |
| Key paired with the car | Done (proxy commands work against the real car) |
| `tesla-http-proxy` (Go, official `vehicle-command` repo) | Built into `bin/`; launched/stopped by `jarvis.py` via `src/_tesla_proxy.py` |
| `prep_car` tool (wake + climate on + optional temp, °F → °C) | Built and registered; not re-verified live in the recent sessions |
| `navigate_car` tool | In progress, see sections 4–6 |
| `_current_location` (car GPS via `vehicle_data?endpoints=location_data`) | Verified live, returns real coordinates |
| Multi-car support (`The Sensei Mobile` default, `parent's tesla`) | Done, VINs from env vars |
| Named address book | `src/services/_tesla-addresses.yaml`, keys lowercased on load |

Things learned that matter later:

- GPS data needs the `vehicle_location` OAuth scope. Tesla silently reuses old consent on re-login,
  so the authorize URL needs `prompt_missing_scopes=true` (added, plus `require_requested_scopes=true`).
- Tesla returns failures as `{"response": null, "error": "..."}` (gateway-level) or
  `{"response": {"result": false, "reason": "..."}}` (vehicle-level). `.get("response", {})` does not
  guard the first shape. `_command_result(r)` in `tesla.py` handles both and is used at the four
  command call sites. **Three unguarded sites remain on purpose**: two in `_wake_and_wait`, one in
  `_current_location`.
- Fleet API billing: default billing limit is $0, so a payment method must be on file. There is a
  $10/month discount for small developers. Throttles: 60 realtime/min, 3 wakes/min, 30 commands/min.
  Per-request prices were not retrievable.
- Google Maps Platform (key in `.env` as `GOOGLE_MAPS_API_KEY`): Geocoding 10k free/mo then $5/1k;
  Places Text/Nearby Search 5k free/mo then $32/1k; Routes 10k free/mo then $5/1k. Free tiers reset monthly.

## 4. Current `navigate_car` code path

`navigate_car(destination, car_name=None, is_address=False)` in `src/services/tesla.py`:

1. Resolve car, get token, wake the car.
2. If `destination` matches an address-book key → `_send_raw_destination` (`navigation_request`,
   free text, through the proxy).
3. Else if `is_address` → same `_send_raw_destination`.
4. Else → `resolve_place()` (Places API Text Search in `src/_google_maps.py`, biased to the car's
   location) → `navigation_gps_request` **called directly on the Fleet API** (bypassing the proxy,
   `FLEET_API_BASE`, TLS verification on) with `{"vin", "lat", "lon", "order": 1}`.

Known problems with path 4, discovered in section 5:

- It shows raw coordinates or an address on the car, not the place name.
- The destination is left **pending**: the driver must press Start on the car.

Path 2/3 (`navigation_request`) auto-starts and shows the resolved name. Whether path 4 should switch
to `navigation_request` with `"<name>, <formatted address>"` text is an **open decision**; that exact
text form has not been tested yet.

## 5. The navigation investigation — findings

### 5.1 Endpoints

| Endpoint | Behavior |
|---|---|
| `navigation_request` | Body `{"type": "share_ext_content_raw", "locale", "timestamp_ms", "value": {"android.intent.extra.TEXT": <free text>}}`. Tesla geocodes server-side. Goes through the local proxy: the proxy's dispatcher returns `ErrCommandUseRESTAPI` for it and forwards to Tesla. |
| `navigation_gps_request` | Body `{"lat", "lon", "order"}`. **Not** in the proxy's command table (~70 commands); via the proxy it returns `400 invalid_command`. Works when called directly on the Fleet API with a plain bearer token. |
| `navigation_waypoints_request` | Documented as "sends a list of waypoints", no schema published. Via the proxy: `400 invalid_command`. Direct: `403 "Tesla Vehicle Command Protocol required"` regardless of body. Needs signing that neither the proxy nor the open-source SDK implements. Dead end for now. |

### 5.2 JSON shapes tried on `navigation_gps_request`

| Shape | Result |
|---|---|
| `{"lat", "lon", "order"}` (single stop) | Works |
| `{"lat", "lon"}` (no `order`) | Works; `order` is optional |
| `{"waypoints": [ {lat,lon,order}, ... ]}` | HTTP 200 / `true`, but car shows **"unknown location"** |
| Bare array of `{lat,lon,order}` (1 or 2 items) | Same "unknown location" |
| Parallel arrays `{"lat":[..],"lon":[..],"order":[..]}` | Did not work |

Every one of those returned HTTP 200 / `result: true`, so **`result: true` says nothing about whether
the car did the right thing.** The endpoint reads only top-level scalar `lat`/`lon`; missing values
appear to default to a bogus location. Still untried: keyless positional `[[lat,lon,order],...]`.
One transient `408 timeout` occurred and did not reproduce.

### 5.3 What `order` actually does

The Teslemetry BLE doc (section 7) says: `1` replaces the trip, `2` prepends a stop, `3` appends a
stop, `0` (default) is unknown. Measured over the cloud/REST path:

- `order=1`, or `navigation_request` with no `order`: **replaces** the whole trip.
- `order=2` and `order=3` behave **identically**: the new stop is inserted at the **front** of the
  route and the previous stop moves to second. It is not a replace, and it is not an append.
- Verified in two independent runs (fresh trip to Fairbanks, then home with `order=2`, then a fresh
  run with `order=3`): both gave home → Fairbanks.

### 5.4 The pending / active rule (the real constraint)

- A destination sent via `navigation_gps_request` is **pending** until the driver presses **Start**
  on the car screen. Sending another before Start **replaces** the pending one, whatever `order` is.
- If the route is active and you insert a stop with `order=2/3`, it goes to the front, but the route
  becomes **inactive again** and needs another Start press.
- Net effect: each inserted stop needs a physical Start press before the next insert, or it is
  overwritten. JARVIS cannot press Start remotely (no such command found).
- A 3-stop attempt with no Start press between inserts ended as Lorie's → Taco Bell: the second
  `gps_request` insert replaced the first. The owner believes the queue can be long if Start is
  pressed between inserts; that was **not tested past 2 stops**.
- To build A → B → C, inserts must be sent in **reverse** (C first, then B, then A), because every
  insert lands at the front. Theory only; unverified beyond 2 stops.

### 5.5 `navigation_request` compared

| Call | `queued` in response | Car behavior |
|---|---|---|
| No `order` | `false` | Replaces trip, **auto-starts**, shows resolved name |
| `order: 1` | `true` | Replaces trip, **auto-starts** |
| `order: 3` | `false` | Inserted at front, route deactivated, **needs Start** |

`queued` is **not** a reliable pending/active signal (the first and third rows both say `false`).
Adding `order` to `navigation_request` makes it behave like `gps_request`'s insert mechanism, which
suggests one shared trip queue behind both endpoints. Using `navigation_request` for both stops of a
2-stop route would keep place names on screen for both; **not yet tested**.

### 5.6 Current conclusion

- Single destination, fully hands-free: `navigation_request` (auto-starts, named).
- Two stops: possible (`navigation_request`, then a second call with `order: 3`), but the driver must
  press Start once. The owner's working position: **JARVIS is capped at 2 stops for now**.
- Three or more stops hands-free: no mechanism found.

## 6. Other design decisions and open items

- **Multi-stop tool shape (decided in discussion, not built):** one revamped `navigate_car` taking a
  plain ordered `list[str]` of destinations (not a dict), list position = order (code assigns the
  Tesla `order`), drop `is_address`, resolve every stop through Google, abort on any failure and
  report which stop failed. Given section 5, this now needs re-scoping to at most 2 stops, and the
  "raw address via `navigation_request`" path may come back, since it is the one that auto-starts.
- **Nearest X (Phase C):** use `resolve_place` with a `rank_by_distance` option that sets
  `rankPreference: "DISTANCE"` (valid for categorical queries) instead of building a separate Nearby
  Search function. Words like "closest" in the query text do not change ranking, so an explicit
  signal is needed, most likely an LLM-set boolean like `is_address`. **Not implemented.**
- **On the way (Phase D):** Routes API route → sample points → search along it → pick least detour.
  Not started. Mixed itineraries (an on-the-way search as one leg of a longer named trip) are
  explicitly deferred; see `Navigation Plan.md`.
- **Untested lead:** the BLE doc lists `navigation_gps_destination_request(lat, lon, destination,
  order)`, which takes a destination *name*. If a cloud equivalent exists it could fix the
  name-display problem for the coordinate-based path. Nothing has been tried against it.
- **Doc drift:** `Tesla Integration Plan.md` still describes the original design (single `TESLA_VIN`,
  Startup-folder proxy). `Navigation Plan.md` still describes `order` as a sequence position and
  `gps_request` as proxy-routed. Both predate the findings above.
- **Small cleanups:** `.env.example` lacks the two VIN variables; `jarvis.py` has an unused `import sys`.

## 7. The repo found, and its maintainer

- Repo: `github.com/Teslemetry/python-tesla-fleet-api`, page `docs/bluetooth_vehicles.md`. It
  documents `navigation_gps_request(lat, lon, order=0)`, `navigation_waypoints_request(waypoints)`,
  `navigation_gps_destination_request(lat, lon, destination, order)`, and the `order` meanings above.
  The commands are described as **ACK-only over BLE**, and the doc claims the same `order` integer
  applies to the cloud path. Our cloud measurements only partly match it (2 and 3 are
  indistinguishable). **It documents BLE, not the Fleet API path used here.**
- Maintainer: GitHub user **Bre77**, the only author in the last 10 commits to that doc (roughly
  July–September 2026). A recent commit references `NavigationSuperchargerRequest.order` →
  `remote_nav_trip_order`. The repo sits under the Teslemetry org. The owner found a LinkedIn profile.
  Public repo contact routes: GitHub Issues/Discussions.

### Questions worth asking

1. Do `order` 1/2/3 behave the same over the cloud Fleet API as over BLE? Over cloud, 2 and 3 both
   inserted at the front.
2. Is there any remote way to activate a pending route, or to add a 3rd+ stop without a physical
   Start press?
3. Is the `navigation_waypoints_request` schema known, and is it reachable only via signed commands?
4. Does a cloud equivalent of `navigation_gps_destination_request` exist, so the coordinate path can
   show a place name?

### Draft message (short, for LinkedIn)

> Hi, I'm building a personal voice assistant that sends destinations to my Tesla through the Fleet
> API, and I came across your `python-tesla-fleet-api` docs on the navigation `order` values. I have
> a few specific questions about how `order` behaves over the cloud path versus BLE (over cloud,
> `order=2` and `3` both insert at the front for me, and each insert leaves the route waiting for a
> Start press). If you have a minute to point me in the right direction, I'd really appreciate it.
> Happy to share exactly what I've tested.

---
---

# Journal entry 2 — 2026-09-19 (later the same day): signed waypoints works

Everything above this line is the record as of entry 1 and is intentionally left unedited. **Where
entry 2 contradicts entry 1, entry 2 wins.** Superseded points are listed in section J2.6.

## J2.1 What prompted this

The user asked whether JARVIS is using `python-tesla-fleet-api` (it is not; JARVIS calls the Fleet
API with plain `requests` plus the official Go `tesla-http-proxy`), then asked what the library is and
how it could fit. Reading its source turned up a **mistake in entry 1**: sections 5.1 and 7 say no
open-source SDK implements signed `navigation_waypoints_request`. That is wrong for this library.

## J2.2 The library (`Teslemetry/python-tesla-fleet-api`, PyPI `tesla-fleet-api` 1.14.0)

- Python client for the Tesla Fleet API, Teslemetry, Tessie, and Bluetooth (BLE). Apache-2.0.
- **Signs vehicle commands natively in Python** (protobuf, HMAC/AES-GCM session, handshake with the
  car). No Go proxy needed. This is the thing the proxy was doing for us.
- Fully async (`aiohttp`); JARVIS tools are sync, so a tool would wrap calls in `asyncio.run(...)`.
- **Requires Python >= 3.13.** Dependencies: `aiohttp`, `aiofiles`, `aiolimiter`, `cryptography`,
  `protobuf`, `tesla-protocol`, `bleak` (+ `winrt-*` on Windows).
- All commands are methods of the `Commands` class in
  `tesla_fleet_api/tesla/vehicle/commands.py` (GitHub:
  `github.com/Teslemetry/python-tesla-fleet-api/blob/main/tesla_fleet_api/tesla/vehicle/commands.py`).
  Each builds a protobuf message and calls `_sendInfotainment`. Local copy line numbers (v1.14.0):
  `navigation_gps_request` 1410, `navigation_request` 1431, `navigation_sc_request` 1441,
  `navigation_waypoints_request` 1453, `navigation_gps_destination_request` 2616,
  `navigation_route` 2936. Signing lives in `signed.py` next to it.
- Usage shape (from the source, confirmed working): `TeslaFleetApi(session, access_token=<callable>,
  region="na")`, `await api.get_private_key(path)`, `vehicle = api.vehicles.createSigned(vin)`,
  then `await vehicle.<command>(...)`. The handshake happens automatically on the first command.
- **Safety trap:** `get_private_key(path)` silently **generates a new key** if `path` does not exist.
  A wrong path would create a key that is not the one paired with the car.
- Unexplained: `navigation_route()` ("Triggers vehicle route navigation", no arguments). It might be
  a remote "start navigation" action. Untested and undocumented.

## J2.3 The experiment

Set up outside the repo, in the session scratchpad: `tesla_exp_venv` (Python 3.13.12) and
`signed_nav_experiment.py` (subcommands `check`, `placeids`, `dest`, `waypoints`). The script reuses the
repo's own `_get_valid_access_token()` (run in the repo venv) so refresh-token rotation stays in the
code that already handles it, and refuses to run if `keys/private-key.pem` is missing. The scratchpad is
temporary and may be cleaned up; everything it established is recorded here.

Place IDs come from the Places API (New) Text Search with `places.id` added to the field mask
(`resolve_place` in `src/_google_maps.py` does not request it yet). A place ID is Google's permanent
identifier for one specific place (`ChIJ...`). Google notes IDs can occasionally change, so fetch them
fresh rather than storing them long-term.

Results, all verified on the car by the user:

| # | Command | Sent | Car showed |
|---|---|---|---|
| 1 | (Google only) | `placeids` for three places | IDs returned; "Carmichael Gym Chapel Hill" resolved to the NC State one in Raleigh |
| 2 | `navigation_gps_destination_request` (signed) | Taco Bell coordinates + name, `order=1`, sent twice | Route to Taco Bell in Chapel Hill, **inactive, needed a Start press**. Signing did not remove the Start press. Whether the *name* was displayed was not explicitly confirmed. |
| 4a | `navigation_waypoints_request` (signed) | `refId:<Chipotle>` | Active route to Chipotle on Hillsborough St, **no Start press** |
| 4b | `navigation_waypoints_request` (signed) | `refId:<Chipotle>,refId:<Carmichael>` | Both stops, in order, **shown by name, route active** |
| 4c | `navigation_waypoints_request` (signed) | three `refId:` entries (Chipotle, Carmichael, Taco Bell) | All three, in order, by name, active |

Every call returned `{"response": {"result": true, "reason": ""}}`. As before, that field alone proves
nothing; the car screen was the real result.

**The working format:** `navigation_waypoints_request("refId:<placeid1>,refId:<placeid2>,...")`, a
comma-separated string of `refId:` + Google place ID, sent **signed**. The `refId:` format was a
recollection, not documented by Tesla, and it turned out to be right.

## J2.4 What is and is not established about mid-route sends

Established: sending a new waypoints list **while a route is active** is accepted and yields exactly
the list sent, still active, with no Start press (4a to 4b to 4c were each sent over an active route).

**Not established: whether it replaces or merges.** Every list sent contained the previous list's
stops, so "replace" and "merge without duplicates" look identical. The deciding test (send one place
that is *not* on the route, such as an Arby's, and see whether the route becomes just that place) was
proposed and **has not been run**. The user's expectation is "replace", which would mean JARVIS must
keep the current itinerary itself and re-send the whole list to add a stop. That is a hypothesis, not a
finding. Also untested: the maximum stop count (3 worked), whether the car can report its route back
(so JARVIS would not need to remember it), waypoints with the car asleep or while driving, and other
string formats (plain addresses, coordinates).

## J2.5 Environment migration (Python 3.12.9 to 3.13.12)

The library needs 3.13, so the JARVIS environment was migrated, non-destructively.

- **Tooling found:** the project used plain `venv` + `pip` (`.venv\pyvenv.cfg` records
  `python -m venv`), Python 3.12.9 from python.org. `uv` 0.10.7 was already installed on the machine.
- **Which Python:** every installed package (113 checked against PyPI wheels per version) has a 3.13
  wheel. 3.14 is blocked because `spacy` 3.8.14 has no 3.14 wheels. 3.13 is the version that satisfies
  both the library and the existing stack.
- **`requirements.txt` was stale and UTF-16.** It listed ~34 packages while the working venv had ~113
  (missing faster-whisper, kokoro, torch, spacy, silero-vad, ctranslate2, sounddevice,
  python-statemachine, and more). It was **regenerated** from the new venv: 138 packages, UTF-8, with a
  header comment naming the Python version and the recreate command. A dry-run install from it reports
  "Would make no changes".
- **New venv `.venv313`** created with `uv venv --python 3.13` **next to** the old `.venv`, which is
  untouched. The name is kept deliberately so the Python version is visible. `.venv313/` was added to
  `.gitignore`. Packages were installed pip-style (`uv pip install -r`), same pinned versions as before;
  only the interpreter changed. Project mode (`pyproject.toml` + `uv.lock`) is deferred.
- **Gotcha:** `openwakeword` downloads its `.onnx` models into its own package folder, so a fresh venv
  lacks them and JARVIS fails at import with `NO_SUCHFILE ... hey_jarvis_v0.1.onnx`. The seven files in
  `openwakeword\resources\models\` were copied from the old venv. Any rebuild must repeat this.
- **Verified:** the full stack imports on 3.13 (Whisper on `cuda`, Silero VAD, Kokoro, wake word; all 11
  tools registered including `prep_car` and `navigate_car`), and the user ran JARVIS on `.venv313` and
  confirmed it works.
- `tesla-fleet-api` 1.14.0 was then installed into `.venv313`: 24 packages added, **no existing pinned
  version changed** (including `protobuf`).

## J2.6 Conclusions in entry 1 that are now superseded

- **5.1 / section 7:** "no open-source SDK implements signed `navigation_waypoints_request`" is wrong.
  It is a dead end only for the Go proxy; the Python library signs it. The "dead end for now" verdict on
  waypoints no longer holds.
- **5.6 / section 6:** "JARVIS is capped at 2 stops" and "three or more hands-free: no mechanism found"
  no longer hold. Three stops worked hands-free, in order, named, active. The two-call
  `navigation_request` + `order:3` idea and the Start-press constraint apply only to the old unsigned
  paths.
- **Section 4 (current `navigate_car` code path)** still describes what is in `src/services/tesla.py`
  today. That code has **not** been changed; it still uses `navigation_request` / direct
  `navigation_gps_request`.
- **Section 7, questions for Bre77:** Q3 is largely answered (signed, string argument, format works).
  Remaining useful questions: the maximum waypoint count, whether the string accepts anything besides
  place IDs, replace-versus-merge behavior, and what `navigation_route` does.
- **Section 6 "untested lead" (`navigation_gps_destination_request`)** was tested: it takes a name but
  still leaves the route pending, so it is not the way.
- The draft LinkedIn message in section 7 is now out of date and would need rewording before use.

## J2.7 Repository state at the end of entry 2

- Branch `4-state-machine`, HEAD `c754018`. **Still nothing from the navigation or migration work is
  committed.**
- Changed this entry: `.gitignore` (+`.venv313/`) and `requirements.txt` (regenerated). `src/` is
  unchanged since entry 1.
- Still uncommitted from entry 1: `.env.example`, `scripts/tesla_setup.py`, `src/services/tesla.py`,
  `docs/Tesla Plans/`, `src/_google_maps.py`, and the moved `docs/Tesla Integration Plan.md`.
- `.venv` (Python 3.12.9) is kept as a fallback. `.venv313` (Python 3.13.12) is the environment to use.
- Memory file `project_signed_waypoints_works.md` records the finding for future sessions.

## J2.8 What comes next (nothing below is built; each needs the user's go-ahead)

1. Design `navigate_car` around **one signed waypoints call**: resolve each stop through Places to a
   place ID, join as `refId:` entries, send. One path would serve single and multi-stop trips and
   replace the raw-address and coordinate paths.
2. Add `places.id` to the field mask in `resolve_place` (`src/_google_maps.py`).
3. Decide how the library fits `tesla.py`: sync-to-async wrapper; whether to keep the existing token
   cache logic (recommended, it already handles rotation) or adopt the library's; whether `prep_car`
   stays on the Go proxy for now.
4. Run the deciding replace-versus-merge test, and decide how JARVIS remembers the current itinerary
   ("also stop at Arby's" would need the full list re-sent if replace is confirmed).
5. Phase C (nearest X) and Phase D (on the way) become simpler: each only has to produce a place ID and
   place it in the list, which also makes the deferred mixed-itinerary idea feasible.
6. Update `Navigation Plan.md` and `Tesla Integration Plan.md`, which predate all of this.
7. Read-only follow-up: look at the `NavigationRouteAction` protobuf definition to see what
   `navigation_route` does.
8. Walk through the library at a high level, including how the sub-commands work (the user wants to
   understand it in full, after the migration).

---
---

# Journal entry 3 — 2026-09-20: `navigate_car` rebuilt on signed waypoints

Entry 3 records the implementation of the plan in J2.8. **Where it contradicts entries 1 or 2, entry 3
wins.** No addresses, VIN, or account IDs are recorded here on purpose (this file is committed).

## J3.1 Design decisions (each one the user's choice)

| Question | Decision | Alternative considered |
|---|---|---|
| Where does the shared library plumbing live? | New file `src/_tesla_client.py` (shared infrastructure outside `services/`, like `_tesla_proxy.py` and `_google_maps.py`) | Keep it inside `tesla.py` |
| How do sync tools reach the async library? | One **long-lived background event loop** plus a `run()` bridge | `asyncio.run()` per call (simpler, but a fresh session and handshake every call) |
| Who refreshes the access token? | **The existing code**, moved into `_tesla_client.py` | The library's `TeslaFleetOAuth` class (see J3.3 for why not) |
| Migration order | `navigate_car` first, `prep_car` later | Both at once |

Defaults adopted without objection: saved-address entries go through Places search like every other
stop; the tool takes `destinations: list[str]`; if any stop fails to resolve, **nothing is sent** and the
message names the stop; remembering the current itinerary ("add a stop") is deferred.

## J3.2 What was built

- **`src/_tesla_client.py` (new).**
  - The token functions (load, save, rotate, refresh) moved here unchanged. The public one is renamed
    `get_valid_access_token`. The constants `CLIENT_ID`, `AUTH_BASE`, `FLEET_API_BASE`,
    `TOKEN_CACHE_PATH` and the private-key path live here too, so the key and the token are owned in one place.
  - `_ensure_loop()` starts the background thread (`tesla-loop`, daemon) lazily on first use and
    registers an `atexit` shutdown. `run(coro, timeout_s=60)` hands a coroutine to that loop with
    `asyncio.run_coroutine_threadsafe(...)` and blocks on the returned future; on timeout it cancels
    the coroutine and raises `TimeoutError`.
  - `_get_api()` builds one `TeslaFleetApi` (server from `FLEET_API_BASE`, the token via a callable that
    calls `get_valid_access_token` in a thread). It **refuses to run if `keys/private-key.pem` is
    missing**, because the library's `get_private_key()` would silently generate a new key that the
    car does not trust.
  - `get_vehicle(vin)` returns a **cached** signed vehicle. Caching matters: `createSigned()` replaces the
    stored vehicle, discarding its handshake sessions.
  - `wake_and_wait(vehicle)` checks the state first and only sends `wake_up` if the car is not online
    (Tesla allows 3 wakes per minute). `current_location(vehicle)` reads `vehicle_data(["location_data"])`.
- **`src/_google_maps.py`:** `resolve_place` now requests `places.id` and returns a `place_id` key.
- **`src/services/tesla.py`:**
  - `navigate_car(destinations: list[str], car_name=None)`. Flow: resolve the car; accept a lone string as
    one stop; wake the car and read its location (`_wake_and_locate`, async); resolve each stop
    (a saved name matches by exact lowercase key and resolves by its address text, unbiased; anything
    else is a name search biased toward the car); **abort before sending if any stop fails**; send one
    `navigation_waypoints_request("refId:<id1>,refId:<id2>,...")` (`_send_route`, async); check
    `response.result`; return a message naming the stops in order.
  - Two `run()` crossings, not one, because the search bias needs the car awake first and the send
    needs the search finished.
  - **Removed:** `_send_raw_destination`, `_current_location`, the `is_address` parameter, and the direct
    `gps_request` call. (The old `is_address` branch also contained a typo, `destinaon`, that would have
    crashed it.)
  - **Unchanged:** `prep_car` still runs through the Go proxy with its own `_wake_and_wait` and
    `_command_result`. The similar names `_wake_and_wait` (proxy) and `wake_and_wait` (library)
    coexist until `prep_car` migrates.
- **`src/prompts/jarvis-prompt.txt`:** one added rule about repeating tool-reported place names exactly
  (it did not work, see J3.6).
- Success message format went through three iterations at the user's request: the stop names; then
  `Name at <full formatted address>`; then `Name at <street>` where the street is the formatted address
  cut at the first comma, and just the street when the place is named after its own address. The user
  also made the stops join with `", then \n"` so each stop lands on its own line in the log.

## J3.3 What was learned about the library along the way

- **Objects.** One `TeslaFleetApi` client (session, token callable, private key) plus one vehicle object
  per car from `api.vehicles.createSigned(vin)`. Everything car-related goes through the vehicle.
  Signed commands for a second car need JARVIS's key paired with *that* car too (not checked for the
  second car).
- **Commands.** Each command builds a protobuf `Action` containing a `VehicleAction`, which is a menu of
  129 alternatives of which exactly one is filled in (`hvacAutoAction`, `ping`,
  `navigationWaypointsRequest`, and so on). It is passed to `_sendInfotainment` (climate, navigation,
  media) or `_sendVehicleSecurity` (locks, trunk, charge port). The car has two "domains" and each has
  its own session.
- **Wire format.** `set_temps(20, 20)` is 14 bytes; `auto_conditioning_start` is 6; a `ping` payload is 5.
  These are wrapped in a `RoutableMessage` with the signature data and sent base64-encoded inside a
  small JSON body to the `signed_command` endpoint. Tesla's cloud only relays a sealed blob.
- **Session.** First contact in a domain does a handshake (a `session_info_request` carrying JARVIS's
  public key; the car answers with its own key, an epoch, a counter and a clock value, plus a tag proving
  it is authentic). Each command is then stamped with an HMAC over the metadata (VIN, epoch, expiry,
  counter) and the command bytes; the counter must always rise and a command expires after 10 seconds.
  The library retries up to 3 times on wrong-epoch or wait replies (its own docstring warns a
  non-repeatable command could apply twice).
- **`TeslaFleetError` derives from `BaseException`, not `Exception`.** A plain `except Exception` misses
  it. The state machine calls tools with no `try`, so every failure path in `navigate_car` catches
  `(Exception, TeslaFleetError)` and returns an error dict.
- **Why the library's OAuth class was not used.** It refreshes tokens fine but keeps the rotated
  refresh token **only in memory**. Tesla invalidates the old refresh token on every refresh, so a crash
  before saving would leave `.tesla_token_cache.json` holding a dead token. Using it would need a subclass
  that saves after every refresh. It also refreshes at a different host (`fleet-auth...`) than the
  existing code (`auth.tesla.com`); compatibility with tokens from the existing login flow was not tested.
- **The library's debug logging prints identifiers** (VIN, display name, account IDs) in wake and vehicle
  responses. Scrub any trace before sharing it.

## J3.4 Verification

All tests ran in `.venv313`. The test scripts lived in the session scratchpad (temporary) and are not in
the repo.

| Step | Test | Result |
|---|---|---|
| 1 | Client module: loop, timeout, token, vehicle cache, wake, location, persistent session, error crossing | 15 of 15 |
| 1 | Persistent session proof: first `ping()` = 2 messages (handshake + command), second = 1 | Confirmed. Measured 0.75 s vs 0.63 s, one run, so the handshake costs about 0.1 s, less than expected. |
| 1 | A fake VIN raises `TeslaFleetError`, and it is **not** caught by `except Exception` | Confirmed |
| 2 | `resolve_place` returns `place_id` for every saved address and three named places | 11 of 11; every street number matched what was typed |
| 3 | `navigate_car` offline with stubs (every branch: bad car, empty list, lone string, order kept, stop unresolvable sends nothing, Google failure, car will not wake, Tesla errors and timeouts, vehicle rejection, null response, location bias) | 23 of 23 |

Live results on the car (the user checked the screen each time):

| Call | Outcome |
|---|---|
| One saved stop (a street address) | Success in 4.2 s. Route active, shown as the **address**, not a business name. |
| "closest taco bell" | Resolved to the actual business. Active. See J3.5. |
| Two stops (a business, then a saved home address) | Call succeeded in 4.8 s. **The user's confirmation of what the car showed was not recorded.** |
| Three stops (a saved house, a business, a saved home) | First attempt returned success (5.7 s) but **the user did not see it on the car**. Identical second attempt (4.7 s) worked: all three stops, in order, active. The first miss is unexplained. |

Observation: a saved entry that is only a street address resolves to Google's *street-address place*, so the
car shows the address. Google also has a separate business record at the same address that returns the
business name when the search text is `Business Name, street, city, state ZIP`. Changing such a YAML value
to that form would make the car show the name. The user chose not to bother. A house cannot get a custom
label like "My house"; the car shows Google's name for the place.

## J3.5 "Nearest X": what the comparison showed

Read-only comparison of Google's ranking, distances measured from the car:

- The text `"closest taco bell"` and `"taco bell"` return the **same results**: the word "closest" has no effect.
- Relevance-ranked results are **not distance-sorted** (one sample order was 0.8, 2.6, 7.8, 5.4, 8.4 miles).
- `rankPreference=DISTANCE` sorted correctly (0.8, 2.6, 5.4, 7.5, 7.8 miles).
- The tool picked the truly nearest branch in the live test only because the car was already sitting next
  to it; with several branches nearby, relevance ranking could pick the 2nd or 3rd nearest.

This is direct evidence for the `rank_by_distance` option planned for Phase C. **Not built.**

## J3.6 Voice test: the model, saved names, and the read-back

The first real voice run: the user said a saved house by a loose phrase (a different spelling from the
saved key, plus the city). The 7B model passed a proper list (the array schema works), but passed the
**user's wording** instead of the saved key, so the exact-match lookup missed, the text went to Google,
Google returned a different venue, the car navigated there, and JARVIS then **said it was going to the
saved house**. Two separate faults: (1) the model does not map loose phrases to saved names; (2) it
relabels the tool's returned place to match what the user asked for.

Replay of phrases through the real model with the real system prompt and tool schemas (2 to 3 runs each, so
small samples), before and after wording changes to the docstring:

| Case | Before | After |
|---|---|---|
| Loose phrase for a saved house, with city | passed raw 3/3 | passed raw 3/3 |
| Saved friend's house, ambiguous between two | city dropped, 2/2 | city dropped, 2/2 |
| "Take me home" | `my house` 3/3 | 2/3, and run 1 **claimed to navigate without calling the tool** |
| Multi-stop ending in "home" | `home` left as `home` | same |
| "nearest Taco Bell" | kept "nearest" 2/2 | one run dropped "nearest" |
| Read-back of a different venue's name | relabeled 3/3 | relabeled 3/3 |

Conclusion: rewording the docstring and adding a prompt rule did **not** fix either fault. Whether the
extra no-tool-call run was caused by the edit or by ordinary variance is unknowable at this sample size.
Not tried, but designed and measured: inline fuzzy matching of saved names in `navigate_car` using
`difflib.get_close_matches` with a cutoff near 0.6 (measured scores: correct matches 0.65 to 1.00; the
ambiguous phrase 0.51; unrelated business names 0.42 to 0.46; "home" to "my house" only 0.50), plus an
ambiguity guard that sends nothing and lists the candidates when two saved names fit about equally.
**The user declined this for now** and will find a workaround later. Zero-code aliases: add extra keys
to the YAML (for example `home:` with the same address as the house entry).

Also seen: the schema Ollama generates lists `car_name` as required even though it has a default; the same
is true of `prep_car`, so this is Ollama's converter, not a regression.

## J3.7 Superseded or updated conclusions

- Entry 1, section 4 (current `navigate_car` code path) is obsolete: see J3.2.
- J2.8 items 1 to 3 are done (design, `place_id`, library fit). Item 4 is **partly** answered: sending a
  new list while a route is active works, but **replace versus merge is still unresolved**. Item 8 was
  covered at a high level (trace, protobuf, command flow).
- The J2.4 unknowns still stand: replace versus merge, the stop-count ceiling (3 tested), behavior with the
  car asleep or driving, other string formats, and what `navigation_route` does.
- Not yet run live: the failure path (an unresolvable second stop leaves the car's route untouched).
  That behavior is covered offline only.

## J3.8 Repository state at the end of entry 3

- Branch `4-state-machine`, HEAD `c754018`. **Nothing is committed.**
- New: `src/_tesla_client.py`, `src/_google_maps.py`, `docs/Tesla Plans/`.
- Modified: `src/services/tesla.py`, `src/prompts/jarvis-prompt.txt`, `requirements.txt` (regenerated),
  `.gitignore` (+`.venv313/`), `.env.example`, `scripts/tesla_setup.py`; `docs/Tesla Integration Plan.md`
  moved into `docs/Tesla Plans/`.
- **The old 3.12 `.venv` can no longer start JARVIS**: `services/__init__.py` imports every tool module
  and `tesla.py` now needs the library, which that venv lacks. `.venv313` is the only working environment.
- Memory file `project_signed_waypoints_works.md` carries the status for future sessions.

## J3.9 What comes next (nothing below is built; each needs the user's go-ahead)

1. **Migrate `prep_car`** to the library, then retire the Go proxy (`src/_tesla_proxy.py`, `bin/`, the
   proxy TLS keys, the start/stop code in `jarvis.py`). The library has both commands it needs
   (`auto_conditioning_start`, `set_temps(driver_temp, passenger_temp)`), but they have **not** been run
   through it on the car; verify first in a scratch script, as was done for navigation. Also check whether
   the key is paired with the second car.
2. **Distance ranking** for reliable "nearest X" (Phase C), then Phase D (on the way) as one more stop in
   the same list.
3. **A workaround for saved-name mapping** (fuzzy match with an ambiguity guard, or YAML aliases), and
   possibly a guard for unsaved places whose top Google result looks nothing like the request.
4. The live failure-path test, and the replace-versus-merge test.
5. Update `Navigation Plan.md` and `Tesla Integration Plan.md`, which still describe the pre-library
   design; reword the LinkedIn draft in section 7 or drop it.
6. Commit, ideally split into a few logical commits (environment migration, the Tesla client and
   `navigate_car`, docs).


# Journal entry 4 — 2026-09-20 (later): async code moved into the client

A small refactor, done before starting the `prep_car` migration so that `prep_car` would not become a
third async function inside `tesla.py`. No behavior change was intended, and none was seen.

## J4.1 What changed

- **`tesla.py` no longer contains any async code.** `_wake_and_locate` and `_send_route` moved into
  `_tesla_client.py`, which now exposes two plain synchronous functions for the tools:
  `wake_and_locate(vin)` and `send_route(vin, place_ids)`. The `refId:` string format (a Tesla detail)
  is built inside `send_route`, not by `navigate_car`.
- **`run()` became private (`_run()`).** `tesla.py` no longer imports it, or anything from the library.
- **New `TeslaError(Exception)`.** `_run()` catches the library's `TeslaFleetError` and re-raises it as
  `TeslaError` (the original stays attached as the cause). Timeouts are also converted, with a readable
  message ("timed out after 60 s") instead of the empty text a bare `TimeoutError` has.

## J4.2 Why the error type matters

`TeslaFleetError` derives from `BaseException`, a sibling of `Exception` rather than a child, so
`except Exception` does not catch it. `state_machine.py` calls tools with no try/except, so an uncaught
one would break JARVIS's turn instead of producing a spoken error. Before this change `navigate_car`
worked around it with `except (Exception, TeslaFleetError)`, which every future tool author would have
to remember. Now the client is the only place that knows about the quirk, and tools use a plain
`except Exception as e` (catching `BaseException` instead would also swallow Ctrl+C). This replaces the
"callers must catch `TeslaFleetError` explicitly" advice in J3.3.

## J4.3 Verification

- Offline: 27 of 27 checks pass. The test now stubs only the client's two async cores, so the real
  `_run()` and background loop are exercised. New checks: a real `TeslaFleetError` comes out as
  `TeslaError` and is caught by a plain `except Exception`; a real timeout gives a readable
  `TeslaError`; a normal result passes straight through.
- One bug found by that test and fixed: the timeout text used `:.0f`, so a 0.2 s timeout read
  "timed out after 0 s". It now uses `:g`.
- Live: one single-stop `navigate_car(["closest taco bell"])` returned `success` in 2.4 s, and the user
  confirmed an active route on the car. So the loop, session and signing all survived the move.

## J4.4 Repository state and next step

- Still nothing committed. Changed since entry 3: `src/_tesla_client.py` and `src/services/tesla.py`.
- `prep_car` is untouched and still on the Go proxy. Next is J3.9 item 1 (migrate it), which should now
  be one new `start_climate` wrapper in the client file plus a thin tool function. At that point
  `send_route`'s raw-dict return is worth normalizing to `(ok, reason)`, since two call sites will share it.

## J4.5 Follow-up: waking and locating split into separate functions

`wake_and_locate` was glue that existed only because `navigate_car` needed both, and it would have forced
every other tool (`prep_car`) to look up the car's position just to wake it. It is now two independent
functions in `_tesla_client.py`: `ensure_awake(vin) -> bool` (sends a wake only if the car isn't already
online) and `locate(vin) -> (lat, lon) | None` (never wakes; a sleeping car also returns `None`).
`navigate_car` calls `ensure_awake`, then `locate` only if the car is awake.

The alternative, having every command call `ensure_awake` itself, was considered and rejected for now:
each call would add a state-check request (`navigate_car` would make 3 instead of 1, `prep_car` 2 instead
of 1), it would hide the wake step and its error wording inside the client, and a "get location" function
that sometimes sends a wake is surprising. If wake-forgetting ever becomes a real problem, the fix would be
a short per-car "known awake" cache (about 30 s) inside `ensure_awake`, so every function could call it cheaply.

Verified: offline 29 of 29 (two new checks: location is never requested when the car won't wake, and it is
requested exactly once when it does), and one live single-stop `navigate_car` returned `success` in 2.1 s.

Later the same day the layers were collapsed too. `wake_and_wait(vehicle)` and `current_location(vehicle)` had
been kept underneath one-line `_ensure_awake(vin)` / `_locate(vin)` adapters that only fetched the vehicle;
that was leftover from how the file grew, not a design. Each Tesla action is now exactly two functions: one
async core that takes a `vin` and does the whole job (`_ensure_awake`, `_locate`, `_send_route`), and one sync
wrapper that bridges it with `_run`. `get_vehicle` became private (`_get_vehicle`). Same tests, same live result
(29 of 29 offline; live single-stop `success` in 2.4 s). New actions such as `start_climate` should follow this shape.


# Journal entry 5 — 2026-10-17: `prep_car` migrated, the Go proxy is gone

The last step of J3.9 item 1. With this, nothing in JARVIS talks to the Go proxy, and the proxy and
its files have been deleted from the repo.

## J5.1 What was built

Two new actions in `_tesla_client.py`, following the shape settled in entry 4 (one async core taking
a `vin`, one sync wrapper calling `_run`):

- `start_climate(vin, on=True) -> (ok, reason)` wrapping `auto_conditioning_start` / `auto_conditioning_stop`
- `set_temps(vin, driver_c, passenger_c) -> (ok, reason)`
- A shared `_result(body)` helper parses the reply. Confirmed by reading the library: `_sendInfotainment`
  returns `{"response": {"result": bool, "reason": str}}`, the same shape the navigation command returns,
  so one parser covers every signed command.

`prep_car` in `tesla.py` is now `ensure_awake` -> `start_climate` -> `set_temps`, with the
Fahrenheit-to-Celsius conversion still in the tool (the car works in Celsius, the user speaks Fahrenheit).
The spoken error wording was kept exactly as the user had written it.

## J5.2 How the command parameters were found

Worth recording as the general method, since the library's own docs are thin. Two ways, both used here:

1. Read the `def` line in `.venv313/Lib/site-packages/tesla_fleet_api/tesla/vehicle/commands.py`
   (`auto_conditioning_start` at ~line 1189, `set_temps` at ~1914).
2. Ask Python: `inspect.signature(VehicleSigned.set_temps)`.

Result: `auto_conditioning_start()` takes **no arguments** — it hardcodes `HvacAutoAction(power_on=True)`,
and `auto_conditioning_stop` is the same call with `False`. `set_temps(driver_temp, passenger_temp)` takes
both temperatures, required, in **Celsius**. The protobuf `HvacAutoAction` has a second field,
`manual_override`, that the library never sets, so it can't be reached through this wrapper.

## J5.3 Deleted with the proxy

- `src/_tesla_proxy.py` and `keys/proxy-tls.crt` (both were tracked, so restorable from git)
- `keys/proxy-tls.key` (untracked -- gone, but regenerable with openssl)
- `bin/tesla-http-proxy.exe` (gitignored -- gone; rebuild with
  `go install github.com/teslamotors/vehicle-command/cmd/tesla-http-proxy@latest`)
- The proxy start/stop from `jarvis.py`, whose `try/finally` existed only to stop it. `main()` is now
  `setup_logger()` then `JarvisMachine()`.
- Dead code inside `tesla.py`: `_wake_and_wait`, `_command_result`, the `PROXY_BASE` and
  `get_valid_access_token` imports, and the now-unused `import time`.

Deliberately kept: `keys/private-key.pem` (the library signs with it) and `keys/public-key.pem` (what the
car trusts, served from the GitHub Pages `.well-known` URL). Also kept `bin/tesla-control.exe`, Tesla's
ad-hoc CLI, which is useful for poking the car by hand and is not part of the proxy path. The
`.gitignore` line for `keys/proxy-tls.key` was left in place on purpose, so a regenerated key could never
be committed by accident.

## J5.4 Verification

| Check | Result |
|---|---|
| `prep_car` offline, stubbing only the client's async cores | 15 of 15 |
| `navigate_car` offline, same approach | 16 of 16 |
| `jarvis` and `services` import after the proxy deletion; all 11 tools load | pass |
| Live `prep_car(temp=72)` on the car | `success` in 2.9 s, confirmed by the user |

The live call is the first time these two climate commands have run against the car through the library,
which settles the "not yet verified on the car" caveat carried since entry 3.

Caveat on the test numbers: the original 29-check navigation suite was lost when the session scratchpad
was cleared between sessions. The 16-check suite is a compact rebuild covering the same paths, not that file.
Also still untested since entry 4: the asleep path inside `_ensure_awake` (send a wake, then poll) has never
been exercised live, because the car has been online for every call.

## J5.5 Repository state

- Still nothing committed. Branch `4-state-machine`, HEAD `c754018`.
- Changed since entry 4: `src/_tesla_client.py` (+2 actions, `_result`), `src/services/tesla.py`
  (`prep_car` rewritten, proxy code removed), `src/jarvis.py` (proxy launch removed), plus the deletions in J5.3.
- The working tree now holds four separable pieces of work: the Python 3.13 environment migration, the Tesla
  client and `navigate_car`, the `prep_car` migration and proxy removal, and the docs.

## J5.6 What comes next

1. **Commit.** This is now the largest outstanding risk -- a lot of unsaved work in one tree.
2. Open navigation items, unchanged from J3.9: saved-name mapping for loose speech, the model relabelling
   returned place names, distance ranking for "nearest X", "on the way", the live failure path, and
   replace-versus-merge for mid-route sends.
3. `Navigation Plan.md` and `Tesla Integration Plan.md` were rewritten in this same session to describe the
   system as built rather than the plan that preceded it.
