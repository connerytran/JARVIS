# JARVIS Roadmap

_Last updated: 2026-10-24_

Working plan, expected to change as things are learned. No target dates — order is dependency-gated
(can't start X until Y is done), not calendar-gated. Update this file as phases complete or reorder,
and bump the date above when you do.

Stable architecture/conventions live in `CLAUDE.md`, not here.

## Status

**Current phase:** 2 — Test mode + baseline

## Phases

- [x] **1. Port to Mac.** Get JARVIS working on the Mac the way it worked on Windows — porting only,
      no tuning. Resolve Windows-specific code paths (file paths, subprocess calls, Windows-only
      libs) and rebuild the audio ducking as a Swift helper: Core Audio process taps (macOS 14.4+),
      ducks any app's audio including browser helper processes, smooth gain ramps (fast duck, slower
      release, eased/decibel curve not linear), controlled from JARVIS over a local socket.
      System-wide volume ducking as a placeholder if this drags.

  Work happens on the `mac-port` branch; merge to `main` once the port is complete (step 10).
  The `windows` branch is a frozen snapshot of the last Windows-working state — no platform checks
  on `mac-port`, Windows code is replaced outright.

  - [x] 1. Migrate to uv: `pyproject.toml` with direct deps only (no Windows-only packages),
    `uv.lock`, `.python-version` pinned to 3.13. Retire `requirements.txt`.
  - [x] 2. Strip Windows code (`pycaw`/`comtypes` in `audio.py` and `system.py`) and move the heavy
    models to Metal. Both run through mlx-audio, so swapping models is a model-ID change: STT →
    Whisper large-v3-turbo, TTS → Kokoro-82M (`bm_george`, same voice as before). openWakeWord
    models now live in `models/openwakeword/` (gitignored, downloaded on startup if missing).
    Wake word and VAD stay on CPU (tiny, always-on — GPU dispatch would cost more than it saves).
    `set_volume`/`get_volume` are stubs until step 5; ducking removed until step 8.
  - [x] 3. Point Home Assistant at the Mac mini: `HA_URL` in `.env`, LAN IP only.
    Works at home; unreachable away from home. Tailscale-first with LAN fallback is the upgrade
    path if JARVIS travels (and avoids sending the HA token to whatever owns that IP elsewhere).
  - [x] 4. Voice smoke test: wake word → listen → Qwen → speak, end to end. Works, with low
    latency. Light control, volume and Spotify verified.
  - [x] 5. `set_volume` / `get_volume` via `osascript` (the LLM volume tool — not ducking). Clamps to
    0–100, unmutes when set above 0. Verified by voice.
  - [x] 6. Spotify: Mac process name and launch command (`open -a Spotify`). Token cache pinned to
    the repo-root `.cache`. The Web API's `start_playback` is silently ignored by the Mac app (stops
    the current song, never loads the new one), so `play_song` starts tracks via AppleScript
    (`src/_macos.py`), validates the URI first (it goes into the script), and confirms playback
    before reporting success. Search/pause/resume/skip/previous still use the Web API. Artist
    queueing is commented out for now. Needs macOS Automation permission for whichever app runs
    JARVIS. Device choice is unchanged (`devices[0]`); picking a device is a later feature.
  - [x] 7. Tesla: the code was already portable; only its gitignored local files needed to come
    over (`.tesla_token_cache.json`, `src/services/_tesla-addresses.yaml`). If the token ever goes
    stale, re-run `scripts/tesla_setup.py` (Tesla rotates the refresh token on every use).
    `prep_car` and `navigate_car` verified by voice.
  - [x] 8. Swift ducking helper (scope above). Plan and progress: `docs/Ducking Plan.md`. Controlled
    over stdin/stdout pipes rather than a socket; process taps need macOS 14.2+ (the helper targets 15).
    Ducks while listening and speaking, follows output-device changes; robustness extras (safety
    timeout, latency check, log tidying) deferred in the plan.
  - [x] 9. Audio devices: survive device changes. `sounddevice` (PortAudio) snapshots the devices at
    start-up, so JARVIS's mic and voice stay on the start-up defaults, and unplugging one mid-stream
    (e.g. wired earbuds with a mic) hangs JARVIS: `stream.read()` waits forever on a device that's gone.
    Fix in `audio.py`: callback streams with a read timeout to notice a dead device, then refresh
    PortAudio's device list and reopen on the current default; refresh before each stream opens too.
    Found while testing ducking (milestone 6, step 2); independent of the helper.
    Done: an unplugged mic is noticed within 0.25 s (3 s for the first chunk, for Bluetooth start-up)
    and reopened on the new default; a new device is picked up at the next stream open; replies play
    on the current default output, with a deadline guard in place of `sd.wait()`.
    Known issue: turning off a Bluetooth speaker while JARVIS is speaking crashes him (segfault in
    native code, cause not pinned down: PortAudio itself or `sd.stop()` on the dead stream). Re-run
    with `PYTHONFAULTHANDLER=1` to see where. Unplugging a wired mic and switching output devices are fine.
  - [x] 10. Merge `mac-port` to `main` (PR #21).

- [ ] **2. Test mode + baseline.** Instrumentation, so every later phase can be measured. Do this
      before anything changes the pipeline — it captures the "before" for the Phase 7 comparison.
  - `--test` flag on `jarvis.py` (argparse → `setup_logger()`). Normal runs stay as they are.
  - Test mode: millisecond timestamps; logs to the terminal *and* `tests/logs/<timestamp>.log`
    (gitignored — contains transcripts). Only JARVIS's own loggers go verbose, not every library's.
  - Timings: STT (end of speech → transcript), TTS (time to first audio + total), LLM (per call,
    plus Ollama's own stats: prompt/output tokens, tokens/s, load time).
  - `timings.jsonl` next to the log: one line of numbers per turn, so comparing runs is trivial.
  - Record a baseline on the freshly ported pipeline, and keep it.
  - Also: pin Hugging Face model revisions (STT/TTS model IDs currently track each repo's latest).

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
      Qwen via Ollama as the LLM. Barge-in comes from LiveKit's VAD + turn detector, replacing the
      hand-built multiprocessing version (and the fixed 1.2 s silence wait). Home-only — no
      remote/phone audio.
  - Keep the models from Phase 1 at first, so Phase 7 can measure what LiveKit alone gains.
  - STT: LiveKit can wrap a non-streaming model with VAD (roughly today's behaviour); native
    streaming STT is the real latency win (transcript ready as you stop talking). Streaming
    candidates that run on Metal: Parakeet TDT 0.6B v3 (`parakeet-mlx` has a streaming
    transcriber; people already run it with LiveKit on Apple Silicon), NVIDIA Nemotron streaming
    ASR (supported by mlx-audio), Moonshine (tiny, less accurate on names). Whisper isn't natively
    streaming — keep it only as an accuracy reference.
  - TTS: Kokoro works via LiveKit's sentence splitting (speech starts after the first sentence,
    not the whole reply). Not via the OpenAI-compatible server route — that breaks streaming —
    so likely a small custom plugin around mlx-audio. Qwen3-TTS 0.6B streams natively (and can
    clone a voice) but is much bigger.
  - VAD: LiveKit's Silero plugin replaces ours. Note: torch stays installed regardless — `misaki[en]`
    pulls it in via spaCy's transformer extras.
  - Metal caveat: the most complete community local plugin (sherpa-onnx) is CPU-only; Metal-native
    streaming means MLX models + our own plugin.

- [ ] **7. Benchmark.** Realistic agentic workloads on the MacBook Air (not generic chat benchmarks),
      using Phase 2's test mode. Change one variable at a time so each gain is attributable:
  1. Phase 2 baseline vs. LiveKit with the same models — what LiveKit alone buys.
  2. Swap speech models one at a time (Phase 6 candidates).
  3. Swap the LLM. Candidates (all in Ollama with tool calling; several have `-mlx` builds):
     Qwen 2.5 7B (current), Qwen3.5 9B (direct successor — main challenger), Qwen3.5 4B (speed
     option), Gemma 4 12B, Gemma 4 E4B (accepts audio input directly), gpt-oss-20b (strong tool
     calling; check it fits in 24 GB next to the speech models). Thinking/reasoning off or low
     for voice.
  4. Ollama vs. llama.cpp/MLX directly; lower quantization; tool-schema size and `num_ctx`.
  - Goal: find out whether the bottleneck is Ollama overhead, the model, or the hardware, before
    spending on either.

- [ ] **8. HTTP adapter + iOS app.** Text-in/text-out HTTP endpoint feeding the same FIFO queue.
      iOS app as a thin, protocol-agnostic client — no audio, no LiveKit. Siri integration via an
      App Intent. Results delivered as notifications. Reachable over Tailscale.

- [ ] **9. Experiments — Kev.** Kev 0.8B as a routing/decision layer alongside Qwen. Benchmark
      actual latency on the Air before committing — the 4B+ sizes are likely too slow and too big
      for 24GB alongside Qwen. If the 0.8B earns its place, fine-tune it on real JARVIS logs.
      Exploratory — doesn't need to ship.

- [ ] **10. Features & hardware (backlog).** Not started, no fixed order:

  - On-the-way navigation (Tesla Phase D — Routes API, sample points, search along route)
  - Multi-stop Tesla navigation (currently capped at 2 stops — see navigation investigation doc)
  - Mic choice and following (after Phase 1 step 9). Two linked decisions, design them together:
    - Bluetooth mics: while JARVIS has the AirPods mic open (almost always — the wake word listens
      constantly), AirPods drop to call quality, so music on them sounds like a phone call. Option:
      ignore Bluetooth mics, or pick the input in config.
    - Switch mid-stream to a new default input (today JARVIS only switches when the mic dies, or at
      the next stream open). Can't ask PortAudio (its device list is a start-up snapshot, and
      refreshing closes all streams), so ask Core Audio directly: poll the default input ID via
      `ctypes` (~every 0.5 s, between chunks) and reopen when it changes. Not via the ducker (its
      stdout is one reply per command, and it would tie mic-following to ducking). Groundwork for
      following Connery between rooms.
  - Mac Studio M5 Max purchase decision, informed by Phase 7 benchmarks
  - MCP servers for tools (optional — one server per domain: Spotify, Tesla, Home Assistant,
    system controls; purely an interop/sharing upgrade, not a performance one)

## Notes for whoever picks this up next (including future Claude Code sessions)

- Phases are checkpoints, not sprints. The actual unit of work is whatever's small enough to finish
  and commit in one sitting — break a phase into those as you go, don't try to plan them all up
  front.
- Commit directly to `main` in small increments. Use a short-lived branch only for something risky
  enough that `main` might be broken for a while (e.g. mid-port) — merge it back within days.
- Once Phase 2 exists, re-run test mode after any change that could affect runtimes (new model,
  pipeline restructure, memory, LangGraph, LiveKit) and compare against the previous run, so a
  slowdown is caught in the phase that caused it.
- This file is expected to be wrong in places. If a phase's scope turns out off, or the order stops
  making sense, edit it — don't preserve a stale plan for consistency's sake.
