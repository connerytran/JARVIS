# JARVIS Roadmap

_Last updated: 2026-10-21_

Working plan, expected to change as things are learned. No target dates — order is dependency-gated
(can't start X until Y is done), not calendar-gated. Update this file as phases complete or reorder,
and bump the date above when you do.

Stable architecture/conventions live in `CLAUDE.md`, not here.

## Status

**Current phase:** 1 — Mac port

## Phases

- [ ] **1. Port to Mac.** Resolve Windows-specific code paths (file paths, subprocess calls,
      Windows-only libs). Audit which models (STT/TTS/wake word) have Metal/MLX support vs. fall
      back to slow reference code on Apple Silicon. Build the Swift audio-ducking helper: Core
      Audio process taps (macOS 14.4+), ducks any app's audio including browser helper processes,
      smooth gain ramps (fast duck, slower release, eased/decibel curve not linear), controlled
      from JARVIS over a local socket. System-wide volume ducking as a placeholder if this drags.

      Work happens on the `mac-port` branch; merge to `main` once a full voice turn works on the Mac.
      The `windows` branch is a frozen snapshot of the last Windows-working state — no platform
      checks on `mac-port`, Windows code is replaced outright.

      - [ ] 1. Migrate to uv: `pyproject.toml` with direct deps only (no Windows-only packages),
            `uv.lock`, `.python-version` pinned to 3.13. Retire `requirements.txt`.
      - [ ] 2. Strip Windows code (`pycaw`/`comtypes` in `audio.py` and `system.py`) and move the
            heavy models to Metal: STT → mlx-whisper, TTS → Kokoro via mlx-audio. No CPU fallback for
            these. Done when `jarvis.py` reaches Idle.
      - [ ] 3. Point Home Assistant at the Mac mini (currently hardcoded to `localhost:8123`).
      - [ ] 4. Voice smoke test: wake word → listen → Qwen → speak, end to end. Expect mic
            permission / input device / sample rate issues here.
      - [ ] 5. `set_volume` / `get_volume` via `osascript` (the LLM volume tool — not ducking).
      - [ ] 6. Spotify: Mac process name and launch command (`open -a Spotify`).
      - [ ] 7. Model audit: per-state timing logs, then compare Metal options (mlx-whisper vs.
            parakeet-mlx for STT, mlx-audio Kokoro vs. alternatives for TTS). Not tied to the current
            models. Wake word and VAD stay on CPU (tiny, always-on — GPU dispatch would cost more
            than it saves); reassess here if needed.
      - [ ] 8. Swift ducking helper (scope above) — gets its own plan when reached.
      - [ ] 9. Merge `mac-port` to `main`.

- [ ] **2. Benchmark.** Qwen 2.5 7B on the MacBook Air under realistic agentic workloads (not
      generic chat benchmarks). Ollama vs. llama.cpp/MLX directly. Test lower quantization. Measure
      tool-schema size and current `num_ctx`. Goal: find out if the bottleneck is Ollama overhead,
      the model, or the hardware, before spending on either.

- [ ] **3. Core & queue cleanup.** Split core (thinking/executing) from adapters (entry points).
      Add a single FIFO request queue between them. Tools return structured results — success,
      failure, and whether a spoken response is needed — instead of just side effects.

- [ ] **4. Memory.** Small rolling buffer of recent turns for in-conversation continuity. Build a
      crude hand-written fact-extractor first (learn the problem directly), then try Mem0 for
      comparison. Extraction runs in the background, off the response path — measure its latency
      impact before deciding whether it needs batching.

- [ ] **5. LangGraph.** Migrate the thinking/executing loop to LangGraph, one slice at a time.
      Mute flag and "quiet action" logic (skip speech on successful simple actions like turning on
      a light) live in graph state. Do this after Phase 4 — the graph's state shape depends on how
      memory ends up designed.

- [ ] **6. Home voice (LiveKit).** LiveKit console mode — local mic/speakers, no server/room/WebRTC.
      Qwen via Ollama as the LLM. Streaming STT (evaluate a streaming option vs. faster-whisper).
      Streaming Kokoro TTS (not the OpenAI-compatible server route — that breaks streaming).
      Barge-in comes from LiveKit's VAD + turn detector, replacing the hand-built multiprocessing
      version. Home-only — no remote/phone audio.

- [ ] **7. HTTP adapter + iOS app.** Text-in/text-out HTTP endpoint feeding the same FIFO queue.
      iOS app as a thin, protocol-agnostic client — no audio, no LiveKit. Siri integration via an
      App Intent. Results delivered as notifications. Reachable over Tailscale.

- [ ] **8. Experiments — Kev.** Kev 0.8B as a routing/decision layer alongside Qwen. Benchmark
      actual latency on the Air before committing — the 4B+ sizes are likely too slow and too big
      for 24GB alongside Qwen. If the 0.8B earns its place, fine-tune it on real JARVIS logs.
      Exploratory — doesn't need to ship.

- [ ] **9. Features & hardware (backlog).** Not started, no fixed order:
      - On-the-way navigation (Tesla Phase D — Routes API, sample points, search along route)
      - Multi-stop Tesla navigation (currently capped at 2 stops — see navigation investigation doc)
      - Mac Studio M5 Max purchase decision, informed by Phase 2 benchmarks
      - MCP servers for tools (optional — one server per domain: Spotify, Tesla, Home Assistant,
        system controls; purely an interop/sharing upgrade, not a performance one)

## Notes for whoever picks this up next (including future Claude Code sessions)

- Phases are checkpoints, not sprints. The actual unit of work is whatever's small enough to finish
  and commit in one sitting — break a phase into those as you go, don't try to plan them all up
  front.
- Commit directly to `main` in small increments. Use a short-lived branch only for something risky
  enough that `main` might be broken for a while (e.g. mid-port) — merge it back within days.
- This file is expected to be wrong in places. If a phase's scope turns out off, or the order stops
  making sense, edit it — don't preserve a stale plan for consistency's sake.
