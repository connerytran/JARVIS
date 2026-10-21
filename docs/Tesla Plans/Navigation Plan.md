# Tesla navigation — how it works today

Describes `navigate_car` as built, as of 2026-10-17, plus the two features that are still only
designed. For the investigation that produced this design, see `Navigation Investigation Summary.md`
(append-only journal). For the Tesla plumbing underneath it, see `Tesla Integration Plan.md`.

## What it does

"JARVIS, take me to Chipotle on Hillsborough, then Carmichael gym" sends **one** signed command and
the car starts navigating. Multiple stops appear in the order spoken, labelled by name, with an
**active** route — no Start press on the screen. Verified live with 1, 2 and 3 stops.

## The command that makes it work

`navigation_waypoints_request("refId:<place id>,refId:<place id>,...")`, signed, where each place id
is a **Google place ID** from Places API Text Search.

This was the whole discovery of the investigation. The alternatives all fall short:

| Command | Why not |
|---|---|
| `navigation_gps_destination_request` | Signed, takes coordinates + a name, but leaves the route **pending** — the user must press Start. Signing alone does not remove that; the waypoints command does. |
| `navigation_request` (share-to-car text) | Single destination only, and Tesla geocodes server-side so there is no control over which branch of a chain is chosen. |
| `navigation_gps_request` (per-stop, with `order`) | Multi-stop, but coordinates only, so stops show as raw addresses rather than names. |

The Go proxy had no case for `navigation_waypoints_request` at all, which is a large part of why the
project moved to the Python library.

Still unexplained: the library's `navigation_route()` takes no arguments and is documented only as
"Triggers vehicle route navigation". Untested.

## Flow

```text
navigate_car(destinations: list[str], car_name=None)
  |
  resolve the car name -> VIN
  ensure_awake(vin)                      only wakes if the car isn't already online
  locate(vin)                            (lat, lon) or None; never wakes the car
  |
  for each destination:
      if it matches a saved name in src/services/_tesla-addresses.yaml
            -> resolve_place(<that exact address>)      unbiased: the address is already exact
      else  -> resolve_place(<spoken text>, lat, lon)   biased toward the car
      nothing found -> return an error naming that stop, send NOTHING
  |
  send_route(vin, [place ids])           one signed waypoints command
  |
  build the spoken reply from what Google actually returned
```

Two deliberate properties:

- **All-or-nothing.** If any stop fails to resolve, nothing is sent. A half-sent itinerary would be
  worse than none, and the error names the stop that failed.
- **The reply quotes the resolved place, not the request.** `"<name> at <street>"`, falling back to
  just the street when the place *is* an address (Google names such records after their street, so
  printing both would read "123 Example Rd at 123 Example Rd"). Only the street is used, not the full
  formatted address, since the city and state are noise out loud.

## Place resolution (`src/_google_maps.py`)

`resolve_place(query, bias_lat=None, bias_lon=None)` calls Places API (New) Text Search and returns
`{"place_id", "name", "formatted_address", "lat", "lon"}`, or `None`.

- The **field mask** must include `places.id` — that is the place ID the car needs. Asking for fewer
  fields is also what keeps the call in the cheaper tier.
- **Location bias** is a 20 km circle around the car, which is what makes "chipotle on hillsborough"
  pick the right branch.
- Ranking is by **relevance, not distance**. Putting "closest" in the query text has no effect.
  `rankPreference=DISTANCE` is the real lever, and is not wired up — see Not built, below.
- An address-only query resolves to the street-address record, so the car shows the address. A
  business can exist at the same address as a separate record.

## The saved address book

`src/services/_tesla-addresses.yaml` maps a spoken name to an exact address. Keys are lowercased on
load, and `navigate_car` looks up `destination.strip().lower()`. The tool's docstring is built with an
f-string at import time so the saved names are listed for the LLM, which is why adding a place needs
no code change.

**Known limitation, deferred by choice.** The lookup is exact. `qwen2.5:7b` does not reliably pass the
saved key when the user speaks loosely — a saved friend's house, spoken as "so-and-so's house in
such-a-town", went to Google as spoken and
resolved to a different place at a similar address. Docstring wording and a system-prompt rule were
both replay-tested and neither fixed it. A `difflib` fuzzy match with an ambiguity guard was proposed
and declined for now; a YAML alias list is the other option.

**Second model issue, also open.** The model re-labels the returned place with the name the user asked
for when it speaks the result (the friend's name, for a place the tool reported as something else). A
prompt rule instructing it to quote the tool result exactly did not fix it.

## Error handling

Every failure returns `{"status": "error", "message": ...}` — `state_machine.py` wraps tool calls in
no try/except, so a raised exception would break the turn. The cases, each with its own wording:

| Case | Behavior |
|---|---|
| Unknown car name | Error listing the known cars; nothing sent |
| Empty destination list | Error; nothing sent |
| A lone string instead of a list | Accepted and wrapped — the model sometimes does this |
| Car unreachable / won't wake | Error; no Google calls, nothing sent |
| Google lookup fails or finds nothing | Error naming the stop; nothing sent |
| Car rejects the route | Error including the car's own `reason` |

`TeslaFleetError` never reaches here as itself — `_tesla_client._run` converts it to `TeslaError`,
which a plain `except Exception` catches. See `Tesla Integration Plan.md`.

## Google API costs

Checked against Google's pricing after the old $200/month blanket credit was retired in March 2025 in
favor of per-SKU free tiers. Free quotas reset monthly.

| API | Used for | Free/month | After |
|---|---|---|---|
| Places API (New) — Text Search | resolving every spoken destination (**in use**) | 5,000 | $32 / 1,000 |
| Places API (New) — Nearby Search | "nearest X", and the repeated search in "on the way" | 5,000 | $32 / 1,000 |
| Routes API — Compute Routes | route polyline for "on the way" | 10,000 | $5 / 1,000 |
| Geocoding API | not used — Text Search handles addresses too | 10,000 | $5 / 1,000 |

Text Search and Nearby Search share one Places quota, not two. At one user asking a few times a day,
none of these free tiers is realistically reachable. Places is the one to watch if usage grows, at
roughly 6× the per-call cost of the others.

## Not built

**Nearest X** — "take me to the nearest Taco Bell" currently relies on Text Search relevance, which
usually but not always returns something close. The fix is `rankPreference=DISTANCE` (or Nearby
Search) centered on `locate(vin)`, which already exists. This needs an ambiguity decision: relevance
and distance disagree, and silently preferring distance would change today's behavior for every query.

**On the way** — "find a gas station on the way to X" needs: resolve X, Routes API `computeRoutes`
for the polyline, sample points along it, Nearby Search at each, then pick the match with the least
added detour. All five stops would then go out in one waypoints call, which the current design already
supports.

**Mixed itineraries** — a dynamic search *between two fixed waypoints* ("Chipotle, then a gas station
on the way to Carmichael, then Taco Bell"). A real generalization of "on the way"; not designed.

**Itinerary memory** — a second `navigate_car` call **replaces** the route rather than appending, so
"add a stop" is not possible without JARVIS tracking the current itinerary. Replace-versus-merge for a
mid-route send was never tested.

## Still untested

- More than 3 stops; where the ceiling is.
- Behavior while the car is asleep, or already driving a route.
- The live failure path — error branches are covered offline only.
- `navigation_route()`.
- One early 3-stop call returned `success` but never appeared on the car. Unexplained, and not
  reproduced since.
