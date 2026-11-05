import CoreAudio
import Foundation
import Synchronization // for Atomic

print("ducker: starting on macOS \(ProcessInfo.processInfo.operatingSystemVersionString)")

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
        print("ducker: translating PID \(pid) failed: \(describe(status))")
        return nil
    }
    return object
}

/// Every process Core Audio currently knows about. The list's length isn't known up front, so: ask for its
/// size in bytes, make an array that big, then read into it.
func allProcessObjects() -> [AudioObjectID] {
    var address = propertyAddress(kAudioHardwarePropertyProcessObjectList)
    var size: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(systemObject, &address, 0, nil, &size) == 0 else { return [] }
    var objects = [AudioObjectID](repeating: 0, count: Int(size) / MemoryLayout<AudioObjectID>.size)
    guard AudioObjectGetPropertyData(systemObject, &address, 0, nil, &size, &objects) == 0 else { return [] }
    return objects
}

/// The PID behind a process object.
func pid(of process: AudioObjectID) -> pid_t? {
    var address = propertyAddress(kAudioProcessPropertyPID)
    var pid: pid_t = -1
    var size = UInt32(MemoryLayout<pid_t>.size)
    return AudioObjectGetPropertyData(process, &address, 0, nil, &size, &pid) == 0 ? pid : nil
}


/// The app identifier (e.g. com.spotify.client), or nil for processes that don't have one (command-line tools).
func bundleID(of process: AudioObjectID) -> String? {
    var address: AudioObjectPropertyAddress = propertyAddress(kAudioProcessPropertyBundleID)
    var value: Unmanaged<CFString>? = nil
    var size: UInt32 = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
    guard AudioObjectGetPropertyData(process, &address, 0, nil, &size, &value) == 0 else { return nil }
    let id: String? = value?.takeRetainedValue() as String?  // Core Audio hands over a copy; we take ownership of it
    return id?.isEmpty == false ? id : nil
}

/// Whether the process is currently sending audio to an output device (i.e. playing something).
func isPlaying(_ process: AudioObjectID) -> Bool {
    var address: AudioObjectPropertyAddress = propertyAddress(kAudioProcessPropertyIsRunningOutput)
    var running: UInt32 = 0
    var size = UInt32(MemoryLayout<UInt32>.size)
    return AudioObjectGetPropertyData(process, &address, 0, nil, &size, &running) == 0 && running != 0
}   // uses AudioObjectGetPropertyData to ask the process this question: kAudioProcessPropertyIsRunningOutput.
    // all the other parts like running and size is used for C to write the answer back to, since it doesn't understand Swift objects


/// The audio format a tap delivers (sample rate, channels, sample type), which the callback in piece 4 must match.
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
    return value?.takeRetainedValue() as String?  // a copy, like bundleID(of:); we take ownership
}



// MARK: - Piece 1: who am I?

let myPID: Int32 = ProcessInfo.processInfo.processIdentifier
print("ducker: my PID is \(myPID)")

// The tap must exclude us (piece 2), so without our own process object there's no point continuing.
guard let me: AudioObjectID = processObject(forPID: myPID), me != AudioObjectID(kAudioObjectUnknown) else {
    print("ducker: Core Audio has no process object for me, so I can't exclude myself from a tap")
    exit(1)
}
print("ducker: my Core Audio process object is \(me)")

// Everything Core Audio can see; the tap in piece 2 will catch all of these except us (and later JARVIS).
let processes = allProcessObjects()
print("ducker: Core Audio knows \(processes.count) processes:")
for process in processes {
    let name = bundleID(of: process) ?? "(no bundle ID)"
    let pidText = pid(of: process).map(String.init) ?? "?"
    print("  object \(process)  pid \(pidText)  \(name)\(isPlaying(process) ? "  ← playing" : "")")
}

// MARK: - Piece 2: create the tap

// Step 1: describe the tap. Everything except us, mixed down to stereo. The originals are muted only while
// something reads the tap (piece 4), so you hear our copy instead of both.
let description = CATapDescription(stereoGlobalTapButExcludeProcesses: [me])
description.name = "ducker"
description.isPrivate = true  // only this process can see the tap
description.muteBehavior = .mutedWhenTapped
print("ducker: tap description ready, uuid \(description.uuid)")

// Step 2: submit the description. Core Audio creates the tap and writes its object ID into tapID.
var tapID: AudioObjectID = AudioObjectID(kAudioObjectUnknown)
let status: OSStatus = AudioHardwareCreateProcessTap(description, &tapID)
guard status == 0 else {
    print("ducker: failed to create tap: \(describe(status))")
    exit(1)
}

print("ducker: tap created, tapID: \(tapID)")

// Step 3: ask the tap what its audio looks like. The callback (piece 4) has to handle exactly this format.
guard let format: AudioStreamBasicDescription = tapFormat(of: tapID) else {
    print("ducker: couldn't read the tap's format")
    AudioHardwareDestroyProcessTap(tapID)
    exit(1)
}
let isFloat = format.mFormatFlags & kAudioFormatFlagIsFloat != 0
let isInterleaved = format.mFormatFlags & kAudioFormatFlagIsNonInterleaved == 0 // means L and R are in one buffer, not split into separate buffers
print("ducker: tap format: \(format.mSampleRate) Hz, \(format.mChannelsPerFrame) channels, " +
      "\(format.mBitsPerChannel) bits, float: \(isFloat), interleaved: \(isInterleaved)")

// The callback treats every 4 bytes as one Float sample, so anything else would come out as noise. It also expects
// L and R in one buffer (L, R, L, R…); split into separate buffers, the ramp would advance once per buffer.
guard isFloat, format.mBitsPerChannel == 32, isInterleaved else {
    print("ducker: expected interleaved 32-bit float samples; can't process this format")
    AudioHardwareDestroyProcessTap(tapID)
    exit(1)
}

// MARK: - Piece 3: Aggregate Device

// Step 1: find the output device the system is playing through, and its UID (the aggregate's dictionary needs the UID).
guard let outputDevice = defaultOutputDevice(), let outputUID = deviceUID(of: outputDevice) else {
    print("ducker: couldn't find the default output device")
    AudioHardwareDestroyProcessTap(tapID)
    exit(1)
}
print("ducker: output device \(outputDevice), uid \(outputUID)")

// Step 2: describe the aggregate device as a dictionary: the tap as its input, the output device as its output and its clock.
let aggregateDescription: [String: Any] = [
    kAudioAggregateDeviceNameKey: "ducker",             // a label for debugging tools; nothing depends on it
    kAudioAggregateDeviceUIDKey: UUID().uuidString,     // our own ID; fresh each run so a crashed run's leftover can't clash
    kAudioAggregateDeviceIsPrivateKey: true,            // invisible to other apps and Sound settings; removed when we exit
    kAudioAggregateDeviceMainSubDeviceKey: outputUID,   // whose clock the whole device follows: the output device's
    kAudioAggregateDeviceSubDeviceListKey: [            // the real devices inside: a list of dictionaries, one per device
        [kAudioSubDeviceUIDKey: outputUID],             // just the output device, by its UID
    ],
    kAudioAggregateDeviceTapListKey: [                  // the taps inside: also a list of dictionaries
        [kAudioSubTapUIDKey: description.uuid.uuidString,   // our tap, by its UUID as text
         kAudioSubTapDriftCompensationKey: true],           // Core Audio keeps the tap in step with the main clock
    ],
    kAudioAggregateDeviceTapAutoStartKey: true,         // the tap starts delivering audio when the device starts (piece 4)
]

// Step 3: create it. Same pattern as the tap: Core Audio writes the new device's object ID into aggregateID.
var aggregateID = AudioObjectID(kAudioObjectUnknown)
let aggregateStatus = AudioHardwareCreateAggregateDevice(aggregateDescription as CFDictionary, &aggregateID)
guard aggregateStatus == 0 else {
    print("ducker: failed to create aggregate device: \(describe(aggregateStatus))")
    AudioHardwareDestroyProcessTap(tapID)
    exit(1)
}
print("ducker: aggregate device created, aggregateID: \(aggregateID)")

// MARK: - Piece 4: callback + start

// How far to duck, relative to what's playing: −20 dB = one tenth of the amplitude. 10^(dB/20) turns decibels into
// the number each sample is multiplied by. (Milestone 4 makes this the --duck-db option.)
let duckDB: Float = -20
print("ducker: duck depth \(duckDB) dB")

// This flag is for whether we should be ducked or not
let ducked = Atomic<Bool>(false)        // `let` because it's changed with store(), never replaced
let ramp = Ramp(sampleRate: Float(format.mSampleRate), duckDB: duckDB)

// Step 1: the callback. Core Audio calls this on its real-time thread every few milliseconds, handing us the
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

// Step 2: register the callback with the aggregate device. Core Audio writes a registration ticket into procID;
// start, stop, and unregister all need it.
var procID: AudioDeviceIOProcID? = nil
let procStatus = AudioDeviceCreateIOProcIDWithBlock(&procID, aggregateID, nil, ioBlock)
guard procStatus == 0, let ioProc = procID else {
    print("ducker: failed to register the callback: \(describe(procStatus))")
    AudioHardwareDestroyAggregateDevice(aggregateID)
    AudioHardwareDestroyProcessTap(tapID)
    exit(1)
}
print("ducker: callback registered")

// Step 3: start the device. From here its clock ticks and Core Audio calls ioBlock every few milliseconds.
// The tap auto-starts with it, and the originals are now muted, so what you hear is our copy.
let startStatus = AudioDeviceStart(aggregateID, ioProc)
guard startStatus == 0 else {
    print("ducker: failed to start the device: \(describe(startStatus))")
    AudioDeviceDestroyIOProcID(aggregateID, ioProc)
    AudioHardwareDestroyAggregateDevice(aggregateID)
    AudioHardwareDestroyProcessTap(tapID)
    exit(1)
}
print("ducker: device started; audio is flowing through the callback")

// MARK: - Cleanup

/// Stops the aggregate device, unregisters the callback, destroys the aggregate device, and destroys the tap.
func tearDown(aggregateID: AudioDeviceID, ioProc: AudioDeviceIOProcID, tapID: AudioObjectID) {
    let stopStatus = AudioDeviceStop(aggregateID, ioProc)
    print(stopStatus == 0 ? "ducker: device stopped" : "ducker: stopping device failed: \(describe(stopStatus))")
    let unregisterStatus = AudioDeviceDestroyIOProcID(aggregateID, ioProc)
    print(unregisterStatus == 0 ? "ducker: callback unregistered"
                                : "ducker: unregistering callback failed: \(describe(unregisterStatus))")
    let aggregateDestroyStatus = AudioHardwareDestroyAggregateDevice(aggregateID)
    print(aggregateDestroyStatus == 0 ? "ducker: aggregate device destroyed"
                                    : "ducker: destroying aggregate device failed: \(describe(aggregateDestroyStatus))")
    let destroyStatus = AudioHardwareDestroyProcessTap(tapID)
    print(destroyStatus == 0 ? "ducker: tap destroyed" : "ducker: destroying tap failed: \(describe(destroyStatus))")
}

signal(SIGINT, SIG_IGN)     // ignore ctrl-c for this program; DispatchSourceSignal will handle it instead
let sigint: any DispatchSourceSignal = DispatchSource.makeSignalSource(signal: SIGINT, queue: .main)
sigint.setEventHandler(handler: {
    print("ducker: ctrl-c received, tearing down")
    tearDown(aggregateID: aggregateID, ioProc: ioProc, tapID: tapID)
    exit(0)
})
sigint.resume()              // start listening for ctrl-c; when it happens, tearDown() will run

signal(SIGTERM, SIG_IGN)    // skip the default quit-at-once on SIGTERM (`kill`); DispatchSourceSignal will handle it instead
let sigterm: any DispatchSourceSignal = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
sigterm.setEventHandler(handler: {
    print("ducker: SIGTERM received, tearing down")
    tearDown(aggregateID: aggregateID, ioProc: ioProc, tapID: tapID)
    exit(0)
})
sigterm.resume()             // start listening for SIGTERM; when it happens, tearDown() will run

// MARK: - Test trigger (temporary: milestone 4 replaces it with duck/release commands over the socket)

DispatchQueue.main.asyncAfter(deadline: .now() + 3) {
    print("ducker: duck")
    ducked.store(true, ordering: .relaxed)
}
DispatchQueue.main.asyncAfter(deadline: .now() + 6) {
    print("ducker: release")
    ducked.store(false, ordering: .relaxed)
}

// Keep the main thread alive to run the signal handlers and the test trigger. Never returns; the callback keeps
// running on its own thread until the process exits.
RunLoop.main.run()
