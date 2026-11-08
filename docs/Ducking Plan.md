# Ducking Plan

_Last updated: 2026-10-29_

ROADMAP Phase 1, step 8. JARVIS lowers every other app's audio while it listens and speaks, then
brings it back up smoothly. Built as a small Swift helper program, written piece by piece: Connery
writes each piece, Claude explains it first and reviews it afterwards.

## How it works (the big picture)

```
JARVIS (Python) ──launches──▶ ducker (Swift)
      │                          │
      └── "duck" / "release" ──▶ │  stdin (replies on stdout)
                                 │
   Spotify, Safari, … ──▶ process tap ──▶ aggregate device ──▶ our callback (× gain) ──▶ speakers
   JARVIS + ducker   ──────────────────────────────────────────────────────────────────▶ speakers
```

- **Process tap** (Core Audio, macOS 14.2+): captures the audio of every process except the ones we
  exclude, and mutes their originals (`muteBehavior = .mutedWhenTapped`). So the tapped audio is only
  heard if we play it back ourselves.
- **Aggregate device**: a virtual audio device that combines the tap (as input) with the real speakers
  (as output), so one callback can read the tapped audio and write to the speakers.
- **IOProc callback**: a function Core Audio calls on its real-time audio thread every few
  milliseconds. It copies input to output, multiplied by the current gain. Ducking = lowering that gain.
- **Excluded from the tap:** JARVIS (so its voice stays full volume) and the helper itself (otherwise
  it would capture its own output, a feedback loop).
- **Fail-safe:** the tap belongs to the helper process. If the helper crashes or quits, macOS removes
  the tap and everything plays normally again.

## Decisions (settled)

| Decision | Choice |
| --- | --- |
| What gets ducked | Everything except JARVIS and the helper |
| When | Duck at the wake word; release after JARVIS finishes speaking (immediately if there's no reply) |
| How much | −20 dB by default |
| Ramp | About 200 ms down, about 800 ms back up, in dB with a smoothstep (eased) curve |
| Tap lifetime | Always on while the helper runs: created at start-up, destroyed at exit. Ducking only changes the gain. On demand (create per command) left a short but noticeable gap at every handover between the original audio and our copy |
| Control | JARVIS launches the helper with `subprocess`, passes its PID, and sends `duck` / `release` / `status` as lines on the helper's stdin; replies come back on stdout. Chosen over a Unix socket: no socket file to manage, and stdin closing tells the helper JARVIS is gone. Only JARVIS ever controls it |
| Layout | Swift package in `helpers/ducker/`, release build copied to `bin/`, Python client in `src/_ducking.py` |

## Milestone 1: proof program

Goal: tap all audio, play it back unchanged, clean up. Music should sound exactly the same while
it runs. All in `helpers/ducker/Sources/ducker/main.swift`; run with `swift run` from `helpers/ducker/`.

- [x] **Piece 0: skeleton.** `Package.swift` plus a `main.swift` that prints a line. Proves the
  toolchain builds and runs.
- [x] **Piece 1: who am I?** Ask Core Audio for our own process object, and list every process it
  knows about. Result: we get a process object immediately (no audio needed first), and Spotify shows
  as playing.
- [x] **Piece 2: create the tap.** Describe the tap and ask Core Audio to create it. Needed the
  package minimum raised to macOS 14.2, where taps were introduced (now 15, for `Atomic` in milestone 3).
  - Look up: `CATapDescription(stereoGlobalTapButExcludeProcesses:)`, `muteBehavior`, `uuid`,
    `isPrivate`, `AudioHardwareCreateProcessTap`.
  - Exclude our own process object from piece 1.
  - Done when: it prints a tap ID, and the tap's audio format (`kAudioTapPropertyFormat`, read with
    the same property pattern as piece 1). Music keeps playing normally: `.mutedWhenTapped` only
    mutes while something is actually reading the tap, which starts in piece 4.
- [x] **Piece 3: aggregate device.** Build a private aggregate device from the tap plus the current
  output device.
  - Why do we need it? A tap is a source of audio, not a device. An aggregate device is a virtual
    device that has:
    - Input: the tap.
    - Output: the speakers or headphones.
    - One clock: the speakers' clock.
    - One callback: it hands us the tapped audio and the speakers' buffer for the same moment.
      Two separate devices would mean two clocks drifting apart, with a buffer between them (clicks and
      added delay).
  - Look up: `kAudioHardwarePropertyDefaultOutputDevice`, `kAudioDevicePropertyDeviceUID`,
    `AudioHardwareCreateAggregateDevice`, and the dictionary keys `kAudioAggregateDeviceUIDKey`,
    `kAudioAggregateDeviceNameKey`, `kAudioAggregateDeviceIsPrivateKey`,
    `kAudioAggregateDeviceMainSubDeviceKey`, `kAudioAggregateDeviceSubDeviceListKey`,
    `kAudioAggregateDeviceTapListKey`, `kAudioSubTapUIDKey`, `kAudioAggregateDeviceTapAutoStartKey`.
  - Done when: it prints the aggregate device's ID. It's private, so it won't appear in Sound settings.
  - Cleanup tears down in reverse order of creation: aggregate device first, then the tap.
- [x] **Piece 4: callback + start.** Register an IOProc on the aggregate device that copies the
  input buffers to the output buffers, then start the device.
  - Aggregate device has tap as input, but audio only moves when device is running and someone's callback receives it.
    - Callback writes audio to output buffer.
    - Output reads from that buffer.
  - Look up: `AudioDeviceCreateIOProcIDWithBlock`, `AudioBufferList` /
    `UnsafeMutableAudioBufferListPointer`, `AudioDeviceStart`.
  - Rule for the callback: no allocating, no locks, no printing, no Python-style "slow" work. It runs
    on a real-time thread with a deadline of a few milliseconds.
  - Done when: **music plays normally again**, now passing through our code.
  - Result: works. Tap format is 48000 Hz, 2 channels, 32-bit float. There's a short but noticeable
    gap when the device starts and stops: the originals are muted immediately, and our copy reaches
    the speakers a moment later. That gap is why the tap is now always on (see Decisions).
- [x] **Piece 5: cleanup.** Run until Ctrl-C (SIGINT) or SIGTERM, then tear down in reverse order.
  - Look up: `AudioDeviceStop`, `AudioDeviceDestroyIOProcID`, `AudioHardwareDestroyAggregateDevice`,
    `AudioHardwareDestroyProcessTap`, `DispatchSource.makeSignalSource` (for SIGINT and SIGTERM),
    `RunLoop.main.run()`.
  - Done when: both exits leave audio normal, with no leftover devices.
  - `RunLoop.main.run()`, not `dispatchMain()`: `dispatchMain()` ends the main thread, so the handlers
    ran on a worker thread and Swift 6 warned about a data race on main-actor state.
  - SIGKILL (`kill -9`) can't be caught; the fail-safe covers it (macOS removes the private tap and
    aggregate device with the process).
- [x] **Piece 6: permission.** Not needed when run from the terminal: piece 4 played audio with no
  prompt. Revisit in milestone 7, when JARVIS launches `bin/ducker` directly. macOS asks for audio-capture permission before a tap can hear
  anything. Without it, the tapped audio is silent. Add an `Info.plist` with
  `NSAudioCaptureUsageDescription` and embed it in the program.
  - Look up: the `-sectcreate __TEXT __info_plist` linker flag, `linkerSettings: [.unsafeFlags(...)]`
    in `Package.swift`.
  - May have to move earlier: if piece 4 plays silence, it's this.

## Milestone 2: fixed duck

- [x] In the callback, multiply every sample by a fixed gain: −20 dB = `pow(10, -20 / 20)` ≈ 0.1.
  A format guard exits early unless the tap delivers 32-bit floats, since the callback reads the
  bytes as `Float`s.
- [x] Done when: music plays clearly quieter while the helper runs, and returns to normal when it quits.
- The duck is relative: our gain applies before the system volume, which scales JARVIS too, so the
  music always sits the same 20 dB further below JARVIS at any volume setting.

## Milestone 3: smooth ramp

- [x] Hold whether we're ducked in an `Atomic<Bool>` the callback can read without a lock (the
  `Synchronization` module, which raised the package minimum to macOS 15). The callback loads it once
  per callback.
- [x] Ramp in `Ramp.swift`: move through dB space over 200 ms (down) or 800 ms (up), shaped with
  smoothstep (`t * t * (3 - 2 * t)`), and convert to a linear gain once per frame, so L and R get the
  same gain. A new fade starts from the current dB, so a release mid-duck reverses smoothly.
  The format guard also requires interleaved audio: in separate L and R buffers, the ramp would advance
  twice per frame.
- [x] Temporary test trigger: duck after 3 s, release after 6 s (`DispatchQueue.main.asyncAfter`).
- [x] Done when: the fade sounds smooth, with no clicks or jumps.

## Milestone 4: control pipe

- [x] **Step 1: arguments.** `--exclude-pid <JARVIS PID>` (added to the tap's exclude list next to our
  own process) and `--duck-db <dB>`. Defaults (exclude no one else, −20 dB) keep `swift run` working.
  Result: Core Audio only knows a process once it has connected to the audio system (any audio API
  call), not only once it plays. Mail (never used audio) had no process object; Safari (silent, but
  connected) did. So JARVIS must initialise its audio before launching the helper (milestone 5).
  Tested with JARVIS idle at the wake word: its Python process was found and excluded; the `uv run`
  launcher above it was not (it never touches audio), so pass the Python PID (`os.getpid()`).
- [x] **Step 2: logs to stderr.** stdout carries only replies, so JARVIS never reads a log line as one.
  `log()` writes through `FileHandle.standardError` (C's `stderr` is a global var Swift 6 flags).
- [x] **Step 3: `ready`.** Printed on stdout once setup succeeds. If setup fails, exit with an error on
  stderr so JARVIS can log it and carry on without ducking (exit code 1 = setup, 2 = bad arguments).
- [x] **Step 4: command loop.** A dedicated `Thread` reads stdin with `readLine()`: `duck` / `release`
  set the flag and reply `ok`; `status` replies `ducked` / `released` (the flag, not the fade);
  anything else replies `error <reason>`. Every line in gets exactly one line out. Replies go through
  `reply()` (`FileHandle.standardOutput`), which writes straight to the pipe, so no `fflush(stdout)` is
  needed. The thread starts after `ready`, so no reply can come before it.
- [x] **Step 5: end of input = shut down.** `readLine()` returning `nil` (JARVIS exited or crashed, or
  Ctrl-D in the terminal) makes the helper send itself SIGTERM; the existing handler tears down on the
  main thread. One tear-down path for all exits, and the command thread never touches the Core Audio IDs
  (Swift 6 rejected sending `ioProc` across threads).
- [x] **Step 6:** removed the test trigger.
- [x] Done when: typing `duck` / `release` / `status` into `swift run` works repeatedly, and Ctrl-D
  exits cleanly. Also works piped: `printf 'status\nduck\n…' | swift run ducker 2> /dev/null`.

## Milestone 5: Python client and JARVIS integration

- [x] `src/_ducking.py`: launch `bin/ducker` with JARVIS's PID (`stdin`/`stdout` as pipes), wait for
  `ready`, `duck()` / `release()` functions that write a line and read the reply with a short timeout.
  Launch it only after JARVIS's audio is set up (so Core Audio knows JARVIS's process), and pass the
  PID of the process that actually plays the voice (if TTS ever plays from a child process, that one).
  - Each read waits with `select.select` first (5 s for `ready`, 0.5 s for a reply), so a hung helper
    can't freeze JARVIS. `bufsize=1` sends each command line immediately.
  - Tested from a bare Python process: without `import sounddevice` it has no process object (like Mail),
    and `start()` takes the failure path cleanly.
- [x] If the helper is missing or crashes: log a warning and carry on without ducking. Ducking must
  never stop JARVIS from working. An `error …` reply only warns; no reply or a broken pipe turns
  ducking off and stops the helper (a late reply would put every later reply one step behind).
- [x] Hook it into the state machine: `start()` in `__init__` before `super().__init__()` (which enters
  idle and never returns), `duck()` at the top of `on_enter_listening` (repeats on follow-ups are
  no-ops), `release()` at the top of `on_enter_idle` (after speaking, or straight after no speech).
- [x] Shut the helper down cleanly when JARVIS exits (including Ctrl-C): `atexit` closes its stdin and
  waits up to 2 s (then kills it), so its tear-down finishes before JARVIS exits.
- [x] Done when: a full voice command over playing music ducks and recovers, several times in a row.
  Also tested: no speech, follow-up, missing helper (one warning, JARVIS unaffected), Ctrl-C, and
  wake-word-to-listening timing unchanged.

## Milestone 6: robustness

- [ ] Output device changes at any time, not only mid-duck, since the tap is always on (headphones
  plugged in, AirPods connect): rebuild the aggregate device on the new output
  (`kAudioHardwarePropertyDefaultOutputDevice` listener).
- [ ] Measure the delay the tap adds to other apps' audio: read `kAudioDevicePropertyBufferFrameSize`,
  `kAudioDevicePropertyLatency` and `kAudioDevicePropertySafetyOffset` on the aggregate device (frames
  ÷ 48000 = seconds). Estimate is about 10–25 ms at the default 512-frame buffer. Check lip-sync with a
  video (noticeable from around 45 ms).
- [ ] Only if the delay is noticeable: lower the aggregate device's buffer size (256 is a common middle
  ground). Trade-offs: more callbacks per second (still tiny CPU), a tighter deadline per callback,
  and it may lower the speakers' buffer size for every app (check before and after).
- [ ] Optional, low priority (matters on the MacBook Air's battery, not on the Mac Studio): stop the
  device while nothing is playing (`kAudioProcessPropertyIsRunningOutput` listeners) and restart it
  when something plays. The handover gap is inaudible when there's no sound.
- [ ] Sample-rate mismatch between the tap and the output device.
- [ ] Safety timeout: if no `release` arrives within, say, 60 s, release anyway.
- [ ] Kill the helper mid-duck: audio comes back.
- [ ] Kill JARVIS mid-duck: the helper exits, audio comes back.

## Milestone 7: ship it

- [x] Release build copied to `bin/ducker` (brought forward to milestone 5, so `_ducking.py` points
  there from the start). Rebuild command under "Commands to remember".
- [ ] Setup notes: building the helper, the audio-capture permission prompt.
- [ ] Tick ROADMAP Phase 1, step 8 and commit on `mac-port`.

## Later improvements

- Pipe the helper's stderr into Python's `logging`: a reader thread in `_ducking.py` turns each
  `ducker:` line into a `logger.info(...)` call, so it matches JARVIS's log format. For now stderr is
  inherited, so the lines print raw in JARVIS's terminal.
- Trim the helper's ~12 start-up log lines to one summary line (e.g. `ducker: ready (excluding PID …, -20 dB)`).

## Commands to remember

All from the repo root.

| What | Command |
| --- | --- |
| Rebuild the helper after any Swift change (JARVIS runs `bin/ducker`, not the source) | `cd helpers/ducker && swift build -c release && cp .build/release/ducker ../../bin/` |
| Run the helper during development (logs and replies) | `cd helpers/ducker && swift run ducker` |
| Only replies (hide logs) / only logs (hide replies) | append `2> /dev/null` / `> /dev/null` |
| Send a scripted set of commands, then end input | `printf 'status\nduck\nrelease\n' \| bin/ducker` |
| Exclude a running app (e.g. to test exclusion) | `bin/ducker --exclude-pid $(pgrep -x Spotify)` |
| Find JARVIS's Python PID (not the `uv run` one) | `pgrep -fl jarvis.py` |

## Open questions

- Which app does the permission prompt name: the helper, or the terminal / VS Code that launched it?
  (Settles in piece 6.)
- Does Core Audio give the tap and the output device the same sample rate in practice? The tap
  reports 48000 Hz; the built-in speakers' rate hasn't been checked yet. (Milestone 6.)
