# JARVIS

_Last updated: 2026-10-21_

A locally-run, voice-controlled personal AI assistant (Python, Windows → porting to macOS).
Personal project, not a team codebase — built to learn by doing, not to have code generated
wholesale. Prefer small, explained steps over large autonomous changes.

## Core values

- **Local-first processing and privacy.** Default to running everything on hardware Connery owns.
  Cloud is a fallback, not the default.
- **Modularity.** Every layer (STT, TTS, LLM, tools) should be swappable via config, not hardcoded.
- **The LLM is a selector, not an executor.** It reasons over candidates and picks an action; plain
  Python functions do the actual work. This keeps the system auditable — don't blur this line by
  having the LLM generate code to run, or having tools make decisions the LLM should make.

## Architecture

- Dependency injection with abstract interfaces — any component (STT, TTS, LLM backend) swaps via
  config, not code changes.
- State machine (`statemachine` library) drives the main loop: idle → listening → thinking →
  executing → speaking.
- Tools are plain Python functions, one file per integration, under `src/services/`. Any module
  exporting a `TOOLS` list is auto-discovered by `src/services/__init__.py` (files prefixed `_` are
  skipped).
- Ollama's Python client converts each tool function into a schema from its type hints and
  docstring, and **flattens every parameter to a top-level type + description** — no nested
  list/dict structure survives. The docstring is the only guidance the model gets for complex
  parameters. Keep tool parameters simple and flat.
- `src/services/` holds only LLM-callable tools, plus their private `_`-prefixed config files.
  Shared infrastructure (e.g. `_tesla_client.py`, `_google_maps.py`) lives directly in `src/`.
- Entity/ID abstraction: don't put raw IDs (Home Assistant entity IDs, etc.) in the system prompt.
  A resolver file maps natural-language names to IDs; only a brief summary is exposed to the LLM.

## Conventions

- **Ask before creating or deleting functions, files, or modules.** Don't do this unprompted.
- Prefer in-code defaults over adding new `.env` entries.
- Maintain markdown reference docs for architecture and setup rather than letting context live only
  in chat history.

## Current stack

- LLM: Qwen 2.5 7B via Ollama
- STT: faster-whisper
- TTS: Kokoro
- Wake word: openWakeWord
- Smart home: Home Assistant on a 2012 Mac mini running headless Ubuntu Server (not local to the
  JARVIS host), Tuya/Luvoni lights as the primary device integration
- Music: Spotipy (Spotify)
- Remote access: Tailscale
- Vehicle: Tesla Fleet API (`src/services/tesla.py`) — see `docs/Tesla Plans/` for the navigation
  investigation and open questions on multi-stop routing

## Hardware

- Home dev machine: Thunderobot laptop, RTX 5070 Ti (the RTX 2080 Super PC is retired)
- Personal Mac: MacBook Air, 24GB unified memory, 1TB storage, 10 CPU cores, 10 GPU cores, 16-core
  Neural Engine — target for the Mac port and local benchmarking
- Work Mac: MacBook Pro M5 Max — work machine, light/careful testing only, no personal data
- Under consideration: Mac Studio M5 Max, as the eventual permanent JARVIS host (tied to an
  apartment move, roughly mid-2027, not urgent)

## Where things stand / where to look next

See `docs/ROADMAP.md` for the current phase and what's next. That file changes often; this one shouldn't.
