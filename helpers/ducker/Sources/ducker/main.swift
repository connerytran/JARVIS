import CoreAudio
import Foundation
import Synchronization // for Atomic

/// Writes a log line to stderr. stdout is reserved for replies to JARVIS, so a log line can't be mistaken for one.
func log(_ message: String) {
    FileHandle.standardError.write(Data((message + "\n").utf8))
}

/// Writes a reply to JARVIS on stdout. FileHandle writes straight to the pipe (no buffer), so it arrives at once.
func reply(_ message: String) {
    FileHandle.standardOutput.write(Data((message + "\n").utf8))
}

log("ducker: starting on macOS \(ProcessInfo.processInfo.operatingSystemVersionString)")

// MARK: - Core Audio helpers
// Core Audio is a C API: everything is an audio object with a numeric ID, and you ask an object questions by
// reading its properties with AudioObjectGetPropertyData. These helpers wrap that pattern.

/// The root object; system-wide questions ("which process object is PID X?") are asked of it.
let systemObject = AudioObjectID(kAudioObjectSystemObject)

/// Builds the "which property" address. Scope global + element main means "the whole object", which is
/// what every property in this program needs.
func propertyAddress(_ selector: AudioObjectPropertySelector) -> AudioObjectPropertyAddress {
    AudioObjectPropertyAddress(
        mSelector: selector,                            //
        mScope: kAudioObjectPropertyScopeGlobal,        // Output or input side? (here it is everything (global))
        mElement: kAudioObjectPropertyElementMain       // channel 1 (left), channel 2 (right), or main which is all channels (element)
    )
}

/// Core Audio errors are OSStatus codes, usually four ASCII characters packed into a number ('who?' etc.).
/// Shows both forms, since the characters are what you search for.
func describe(_ status: OSStatus) -> String {
    let bytes = withUnsafeBytes(of: status.bigEndian) { Array($0) }
    let printable = bytes.allSatisfy { $0 >= 32 && $0 < 127 }
    return printable ? "\(status) ('\(String(decoding: bytes, as: UTF8.self))')" : "\(status)"
}

/// Asks Core Audio for the process object that represents the process with this PID.
/// Returns nil if the call fails, or kAudioObjectUnknown (0) if that process has no audio object (yet).
func processObject(forPID pid: pid_t) -> AudioObjectID? {
    var address: AudioObjectPropertyAddress = propertyAddress(kAudioHardwarePropertyTranslatePIDToProcessObject) // which propery am i asking about? (the selector, scope, and element)
    var pid: pid_t = pid                                                // the qualifier: the question's extra input
    var object: AudioObjectID = AudioObjectID(kAudioObjectUnknown)      // the answer gets written here
    var size: UInt32 = UInt32(MemoryLayout<AudioObjectID>.size)         // how many bytes the answer may use
    let status: OSStatus = AudioObjectGetPropertyData(
        systemObject, &address,                     // ask whom (systemObject aka the root object) about what (address struct, in this case it's kAudioHardwarePropertyTranslatePIDToProcessObject)
        UInt32(MemoryLayout<pid_t>.size), &pid,     // Extra input (qualifier) and it's size
        &size, &object                              // Where to put the answer and it's size
    )
    guard status == 0 else {  // 0 = noErr
        log("ducker: translating PID \(pid) failed: \(describe(status))")
        return nil
    }
    return object
}



/// The audio format a tap delivers (sample rate, channels, sample type), which the callback in piece 3 must match.
func tapFormat(of tap: AudioObjectID) -> AudioStreamBasicDescription? {
    var address = propertyAddress(kAudioTapPropertyFormat)
    var format = AudioStreamBasicDescription()
    var size = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
    return AudioObjectGetPropertyData(tap, &address, 0, nil, &size, &format) == 0 ? format : nil
}

/// The device the system is currently playing sound through (speakers, headphones, AirPods, ...).
func defaultOutputDevice() -> AudioDeviceID? {
    var address = propertyAddress(kAudioHardwarePropertyDefaultOutputDevice)
    var device = AudioDeviceID(kAudioObjectUnknown)
    var size = UInt32(MemoryLayout<AudioDeviceID>.size)
    guard AudioObjectGetPropertyData(systemObject, &address, 0, nil, &size, &device) == 0,
          device != AudioDeviceID(kAudioObjectUnknown) else { return nil }
    return device
}

/// A device's UID: a string name for it that stays the same across reboots, unlike its object ID. Aggregate devices
/// refer to their parts by UID.
func deviceUID(of device: AudioDeviceID) -> String? {
    var address = propertyAddress(kAudioDevicePropertyDeviceUID)
    var value: Unmanaged<CFString>? = nil
    var size = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
    guard AudioObjectGetPropertyData(device, &address, 0, nil, &size, &value) == 0 else { return nil }
    return value?.takeRetainedValue() as String?  // Core Audio hands over a copy; we take ownership of it
}

/// The output half of the setup: an aggregate device (tap in, real device out) and our callback running on it.
/// Rebuilt whenever the output device changes; the tap stays.
typealias Output = (aggregate: AudioDeviceID, ioProc: AudioDeviceIOProcID)

/// Builds the output half on `device`: creates the aggregate device, registers the callback, starts it.
/// On failure, undoes whatever it made and returns nil; it never exits, so it's safe to call at runtime.
func startOutput(on device: AudioDeviceID, tapUUID: UUID, ioBlock: @escaping AudioDeviceIOBlock) -> Output? {
    guard let uid = deviceUID(of: device) else {
        log("ducker: couldn't read the UID of output device \(device)")
        return nil
    }

    // The aggregate device as a dictionary: the tap as its input, the output device as its output and its clock.
    let description: [String: Any] = [
        kAudioAggregateDeviceNameKey: "ducker",             // a label for debugging tools; nothing depends on it
        kAudioAggregateDeviceUIDKey: UUID().uuidString,     // fresh each time, so neither a crashed run's leftover nor
                                                            // the device we're replacing can clash with it
        kAudioAggregateDeviceIsPrivateKey: true,            // invisible to other apps and Sound settings; removed when we exit
        kAudioAggregateDeviceMainSubDeviceKey: uid,         // whose clock the whole device follows: the output device's
        kAudioAggregateDeviceSubDeviceListKey: [            // the real devices inside: a list of dictionaries, one per device
            [kAudioSubDeviceUIDKey: uid],                   // just the output device, by its UID
        ],
        kAudioAggregateDeviceTapListKey: [                  // the taps inside: also a list of dictionaries
            [kAudioSubTapUIDKey: tapUUID.uuidString,        // our tap, by its UUID as text
             kAudioSubTapDriftCompensationKey: true],       // Core Audio keeps the tap in step with the main clock
        ],
        kAudioAggregateDeviceTapAutoStartKey: true,         // the tap starts delivering audio when the device starts
    ]
    var aggregate = AudioObjectID(kAudioObjectUnknown)
    let createStatus = AudioHardwareCreateAggregateDevice(description as CFDictionary, &aggregate)
    guard createStatus == 0 else {
        log("ducker: failed to create aggregate device: \(describe(createStatus))")
        return nil
    }

    // Register the callback; Core Audio writes a registration ticket into procID, which start/stop/unregister need.
    var procID: AudioDeviceIOProcID? = nil
    let procStatus = AudioDeviceCreateIOProcIDWithBlock(&procID, aggregate, nil, ioBlock)
    guard procStatus == 0, let ioProc = procID else {
        log("ducker: failed to register the callback: \(describe(procStatus))")
        AudioHardwareDestroyAggregateDevice(aggregate)
        return nil
    }

    // Start it. From here its clock ticks and Core Audio calls ioBlock every few milliseconds. The tap auto-starts
    // with it, and the originals are now muted, so what you hear is our copy.
    let startStatus = AudioDeviceStart(aggregate, ioProc)
    guard startStatus == 0 else {
        log("ducker: failed to start the device: \(describe(startStatus))")
        AudioDeviceDestroyIOProcID(aggregate, ioProc)
        AudioHardwareDestroyAggregateDevice(aggregate)
        return nil
    }

    log("ducker: output running on device \(device) (\(uid)), aggregate \(aggregate)")
    return (aggregate, ioProc)
}

/// Takes the output half down: stop, unregister the callback, destroy the aggregate device. Logs failures and
/// carries on (after an unplug, Core Audio may complain about stopping a device that's gone).
func stopOutput(_ output: Output) {
    let stopStatus = AudioDeviceStop(output.aggregate, output.ioProc)
    log(stopStatus == 0 ? "ducker: device stopped" : "ducker: stopping device failed: \(describe(stopStatus))")
    let unregisterStatus = AudioDeviceDestroyIOProcID(output.aggregate, output.ioProc)
    log(unregisterStatus == 0 ? "ducker: callback unregistered"
                              : "ducker: unregistering callback failed: \(describe(unregisterStatus))")
    let destroyStatus = AudioHardwareDestroyAggregateDevice(output.aggregate)
    log(destroyStatus == 0 ? "ducker: aggregate device destroyed"
                           : "ducker: destroying aggregate device failed: \(describe(destroyStatus))")
}

// MARK: - Arguments

// --exclude-pid <PID>: another process to leave out of the tap (JARVIS, so its voice stays full volume).
// --duck-db <dB>: how far to duck. Both optional, so a bare `swift run` still works.
var excludePID: Int32? = nil
var duckDB: Float = -20

var arguments = CommandLine.arguments.dropFirst()   // [0] is the program's own path
while let flag = arguments.popFirst() {
    switch flag {
    case "--exclude-pid":
        guard let text = arguments.popFirst(), let value = Int32(text) else {
            log("ducker: --exclude-pid needs a process ID")
            exit(2)
        }
        excludePID = value
    case "--duck-db":
        guard let text = arguments.popFirst(), let value = Float(text), value < 0 else {
            log("ducker: --duck-db needs a negative number, e.g. -20")
            exit(2)
        }
        duckDB = value
    default:
        log("ducker: unknown argument \(flag)")
        exit(2)
    }
}

// MARK: - Piece 1: who am I?

let myPID: Int32 = ProcessInfo.processInfo.processIdentifier
log("ducker: my PID is \(myPID)")

// The tap must exclude us (piece 2), so without our own process object there's no point continuing.
guard let me: AudioObjectID = processObject(forPID: myPID), me != AudioObjectID(kAudioObjectUnknown) else {
    log("ducker: Core Audio has no process object for me, so I can't exclude myself from a tap")
    exit(1)
}
log("ducker: my Core Audio process object is \(me)")

// Everyone the tap leaves out: us (or we'd capture our own output) and, if given, JARVIS (so its voice isn't ducked).
var excluded: [AudioObjectID] = [me]
if let excludePID {
    guard let other = processObject(forPID: excludePID), other != AudioObjectID(kAudioObjectUnknown) else {
        log("ducker: Core Audio has no process object for PID \(excludePID), so I can't exclude it")
        exit(1)
    }
    excluded.append(other)
    log("ducker: also excluding PID \(excludePID) (process object \(other))")
}

// MARK: - Piece 2: create the tap

// Step 1: describe the tap. Everything except the excluded processes, mixed down to stereo. The originals are muted
// only while something reads the tap (piece 4), so you hear our copy instead of both.
let description = CATapDescription(stereoGlobalTapButExcludeProcesses: excluded)
description.name = "ducker"
description.isPrivate = true  // only this process can see the tap
description.muteBehavior = .mutedWhenTapped
log("ducker: tap description ready, uuid \(description.uuid)")

// Step 2: submit the description. Core Audio creates the tap and writes its object ID into tapID.
var tapID: AudioObjectID = AudioObjectID(kAudioObjectUnknown)
let status: OSStatus = AudioHardwareCreateProcessTap(description, &tapID)
guard status == 0 else {
    log("ducker: failed to create tap: \(describe(status))")
    exit(1)
}

log("ducker: tap created, tapID: \(tapID)")

// Step 3: ask the tap what its audio looks like. The callback (piece 3) has to handle exactly this format.
guard let format: AudioStreamBasicDescription = tapFormat(of: tapID) else {
    log("ducker: couldn't read the tap's format")
    AudioHardwareDestroyProcessTap(tapID)
    exit(1)
}
let isFloat = format.mFormatFlags & kAudioFormatFlagIsFloat != 0
let isInterleaved = format.mFormatFlags & kAudioFormatFlagIsNonInterleaved == 0 // means L and R are in one buffer, not split into separate buffers
log("ducker: tap format: \(format.mSampleRate) Hz, \(format.mChannelsPerFrame) channels, " +
      "\(format.mBitsPerChannel) bits, float: \(isFloat), interleaved: \(isInterleaved)")

// The callback treats every 4 bytes as one Float sample, so anything else would come out as noise. It also expects
// L and R in one buffer (L, R, L, R…); split into separate buffers, the ramp would advance once per buffer.
guard isFloat, format.mBitsPerChannel == 32, isInterleaved else {
    log("ducker: expected interleaved 32-bit float samples; can't process this format")
    AudioHardwareDestroyProcessTap(tapID)
    exit(1)
}

// MARK: - Piece 3: callback

// How far to duck (--duck-db), relative to what's playing: −20 dB = one tenth of the amplitude. 10^(dB/20) turns
// decibels into the number each sample is multiplied by; the ramp does that conversion.
log("ducker: duck depth \(duckDB) dB")

// This flag is for whether we should be ducked or not
let ducked = Atomic<Bool>(false)        // `let` because it's changed with store(), never replaced
let ramp = Ramp(sampleRate: Float(format.mSampleRate), duckDB: duckDB)

// The callback. Core Audio calls this on its real-time thread every few milliseconds, handing us the
// tap's audio (input) and the output device's buffer to fill (output) for the same moment. It writes each input
// frame to the output multiplied by the ramp's gain. Real-time rules: no printing, no allocating, no locks.
let ioBlock: AudioDeviceIOBlock = { _, inInputData, _, outOutputData, _ in
    let isDucked = ducked.load(ordering: .relaxed)  // read once per callback; every frame in this buffer agrees
    let inputs = UnsafeMutableAudioBufferListPointer(UnsafeMutablePointer(mutating: inInputData))
    let outputs = UnsafeMutableAudioBufferListPointer(outOutputData)

    for index in 0..<outputs.count {
        guard let outData = outputs[index].mData else { continue }
        let outBytes = Int(outputs[index].mDataByteSize)
        memset(outData, 0, outBytes)  // start from silence, so anything we don't write is quiet, not garbage

        if index < inputs.count, let inData = inputs[index].mData {
            let inBytes = Int(inputs[index].mDataByteSize)
            let channels = Int(inputs[index].mNumberChannels)              // 2: samples go L, R, L, R…
            let frames = min(inBytes, outBytes) / MemoryLayout<Float>.size / channels  // bytes → samples → frames
            let inSamples = inData.assumingMemoryBound(to: Float.self)    // safe: the format guard checked
            let outSamples = outData.assumingMemoryBound(to: Float.self)
            for frame in 0..<frames {
                let gain = ramp.nextGain(ducked: isDucked)                 // one gain per frame…
                for channel in 0..<channels {                              // …applied to L and R alike
                    let i = frame * channels + channel                     // position in the flat L, R, L, R… list
                    outSamples[i] = inSamples[i] * gain
                }
            }
        }
    }
}

// MARK: - Piece 4: output

// Build the output half on whatever the system is playing through right now. Unlike a later rebuild, failing
// here is fatal: JARVIS reads no `ready`, logs why, and runs without ducking.
guard let firstDevice = defaultOutputDevice(),
      let firstOutput = startOutput(on: firstDevice, tapUUID: description.uuid, ioBlock: ioBlock) else {
    log("ducker: couldn't start output on the default device")
    AudioHardwareDestroyProcessTap(tapID)
    exit(1)
}
var output: Output? = firstOutput              // nil = no output right now: nothing reads the tap, so apps play normally
var outputDevice: AudioDeviceID = firstDevice  // the device `output` was built on, to ignore repeat notifications

// MARK: - Output changes

// When the system's default output changes (AirPods connect, headphones unplugged…), move the output half to the
// new device; the tap, the flag and the ramp stay, so a duck carries over. Registered once here; Core Audio calls the
// block on every change. It runs on the main queue, like the signal handlers, so a rebuild and a tear-down never
// overlap. It must stay on .main: Swift doesn't check this closure's threading, so that guarantee is ours to keep.
var defaultOutputAddress = propertyAddress(kAudioHardwarePropertyDefaultOutputDevice)
let listenStatus = AudioObjectAddPropertyListenerBlock(systemObject, &defaultOutputAddress, .main) { _, _ in
    guard let newDevice = defaultOutputDevice(), newDevice != outputDevice else { return }  // Core Audio may repeat itself
    log("ducker: default output changed to device \(newDevice), rebuilding")
    if let old = output { stopOutput(old) }
    outputDevice = newDevice
    output = startOutput(on: newDevice, tapUUID: description.uuid, ioBlock: ioBlock)  // nil on failure: apps play normally
}
if listenStatus != 0 {
    log("ducker: can't watch for output changes (\(describe(listenStatus))); staying on device \(firstDevice)")
}

// MARK: - Cleanup

/// Takes down the output half (if there is one right now), then destroys the tap.
func tearDown(output: Output?, tapID: AudioObjectID) {
    if let output { stopOutput(output) }   // there may be none, if the last rebuild failed
    let destroyStatus = AudioHardwareDestroyProcessTap(tapID)
    log(destroyStatus == 0 ? "ducker: tap destroyed" : "ducker: destroying tap failed: \(describe(destroyStatus))")
}

signal(SIGINT, SIG_IGN)     // ignore ctrl-c for this program; DispatchSourceSignal will handle it instead
let sigint: any DispatchSourceSignal = DispatchSource.makeSignalSource(signal: SIGINT, queue: .main)
sigint.setEventHandler(handler: {
    log("ducker: ctrl-c received, tearing down")
    tearDown(output: output, tapID: tapID)
    exit(0)
})
sigint.resume()              // start listening for ctrl-c; when it happens, tearDown() will run

signal(SIGTERM, SIG_IGN)    // skip the default quit-at-once on SIGTERM (`kill`); DispatchSourceSignal will handle it instead
let sigterm: any DispatchSourceSignal = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
sigterm.setEventHandler(handler: {
    log("ducker: SIGTERM received, tearing down")
    tearDown(output: output, tapID: tapID)
    exit(0)
})
sigterm.resume()             // start listening for SIGTERM; when it happens, tearDown() will run

// MARK: - Commands

// Reads one command per line from stdin (JARVIS, or you typing in the terminal) and answers each with exactly one
// line on stdout. readLine() waits until a whole line arrives, so this runs on its own thread, not the main one.
let commandThread = Thread {
    while let line = readLine() {
        let command = line.trimmingCharacters(in: .whitespacesAndNewlines)
        switch command {
        case "duck":
            ducked.store(true, ordering: .relaxed)
            reply("ok")
        case "release":
            ducked.store(false, ordering: .relaxed)
            reply("ok")
        case "status":
            reply(ducked.load(ordering: .relaxed) ? "ducked" : "released")
        default:
            reply("error unknown command: \(command)")
        }
    }

    // readLine() returned nil: stdin closed (JARVIS exited or crashed, or Ctrl-D in the terminal). Send ourselves a
    // SIGTERM rather than tearing down here: its handler does it on the main thread, so a real SIGTERM at the same
    // moment can't tear down twice, and this thread never touches the Core Audio IDs.
    log("ducker: stdin closed")
    kill(getpid(), SIGTERM)
}

// Setup succeeded: tell JARVIS it can send commands. Every failure above exits with a reason on stderr instead,
// so JARVIS either reads `ready` or sees the helper exit without it.
reply("ready")
commandThread.start()   // after `ready`, so no reply can arrive before it

// Keep the main thread alive to run the signal handlers and the end-of-input tear-down. Never returns; the callback
// and the command thread keep running on their own threads until the process exits.
RunLoop.main.run()
