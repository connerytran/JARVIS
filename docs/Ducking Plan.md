# Ducking Plan

_Last updated: 2026-10-29_

ROADMAP Phase 1, step 8. JARVIS lowers every other app's audio while it listens and speaks, then
brings it back up smoothly. Built as a small Swift helper program, written piece by piece: Connery
writes each piece, Claude explains it first and reviews it afterwards.

## How it works (the big picture)

```
JARVIS (Python) ──launches──▶ ducker (Swift)
      │                          │
      └── "duck" / "release" ──▶ │  Unix socket
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
| Control | JARVIS launches the helper with `subprocess`, passes its PID, sends `duck` / `release` / `status` over a Unix socket |
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
  package minimum raised to macOS 14.2 (`platforms: [.macOS("14.2")]`), where taps were introduced.
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

- [ ] In the callback, multiply every sample by a fixed gain: −20 dB = `pow(10, -20 / 20)` ≈ 0.1.
- [ ] Done when: music plays clearly quieter while the helper runs, and returns to normal when it quits.

## Milestone 3: smooth ramp

- [ ] Hold the target gain (ducked or not) in an atomic value the callback can read without a lock
  (look up the `Synchronization` module's `Atomic`).
- [ ] Ramp in the callback: move through dB space over about 200 ms (down) or 800 ms (up), shaped
  with smoothstep (`t * t * (3 - 2 * t)`), and convert to a linear gain per sample.
- [ ] Temporary test trigger: duck after 3 s, release after 6 s.
- [ ] Done when: the fade sounds smooth, with no clicks or jumps.

## Milestone 4: control socket

- [ ] Command-line arguments: `--exclude-pid <JARVIS PID>`, `--socket <path>`, optional `--duck-db`.
- [ ] Unix socket server: accept `duck`, `release`, `status`; reply `ok` / `error <reason>` / current state.
- [ ] Set up the tap, aggregate device and callback once at start-up; `duck` / `release` only set the
  target gain. If setup fails, exit with an error so JARVIS can log it and carry on without ducking.
- [ ] Graceful shutdown on SIGINT/SIGTERM: release, tear down, remove the socket file.
- [ ] Exit if JARVIS dies (watch the parent PID), so the helper never outlives it.
- [ ] Done when: `duck` / `release` sent by hand (e.g. with `nc -U`) work repeatedly.

## Milestone 5: Python client and JARVIS integration

- [ ] `src/_ducking.py`: launch `bin/ducker` with JARVIS's PID, connect to the socket, `duck()` /
  `release()` functions with short timeouts.
- [ ] If the helper is missing or crashes: log a warning and carry on without ducking. Ducking must
  never stop JARVIS from working.
- [ ] Hook it into the state machine: duck at the wake word, release after speaking (or straight
  away when there's nothing to say).
- [ ] Shut the helper down cleanly when JARVIS exits (including Ctrl-C).
- [ ] Done when: a full voice command over playing music ducks and recovers, several times in a row.

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

- [ ] Release build (`swift build -c release`) copied to `bin/ducker`, with a short script or
  documented command for rebuilding.
- [ ] Setup notes: building the helper, the audio-capture permission prompt.
- [ ] Tick ROADMAP Phase 1, step 8 and commit on `mac-port`.

## Open questions

- Which app does the permission prompt name: the helper, or the terminal / VS Code that launched it?
  (Settles in piece 6.)
- Does Core Audio give the tap and the output device the same sample rate in practice? The tap
  reports 48000 Hz; the built-in speakers' rate hasn't been checked yet. (Milestone 6.)
