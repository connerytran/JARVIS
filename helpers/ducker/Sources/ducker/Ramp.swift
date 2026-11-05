import Foundation  // pow()

/// The duck/release fade. The audio callback asks it for a gain once per frame; it remembers where the fade is
/// between frames and callbacks. Only the audio thread may use it, which is the promise @unchecked Sendable makes.
final class Ramp: @unchecked Sendable {
    // Settings, fixed when the ramp is created.
    private let duckDB: Float     // how far down a duck goes, e.g. -20
    private let downStep: Float   // fade progress per frame while ducking (1 ÷ the frames in 200 ms)
    private let upStep: Float     // fade progress per frame while releasing (1 ÷ the frames in 800 ms)

    // State, carried from one frame to the next.
    private var currentDB: Float = 0   // where the gain is now; 0 dB = full volume
    private var startDB: Float = 0     // where the current fade began
    private var targetDB: Float = 0    // where it's heading: 0 or duckDB
    private var progress: Float = 1    // 0 to 1 through the current fade; 1 = finished
    private var currentGain: Float = 1 // currentDB as a multiplier, e.g. 1 for 0 dB, 0.1 for -20 dB

    init(sampleRate: Float, duckDB: Float, downSeconds: Float = 0.6, upSeconds: Float = 0.8) {
        self.duckDB = duckDB
        downStep = 1 / (downSeconds * sampleRate)
        upStep = 1 / (upSeconds * sampleRate)
    }

    /// The gain to multiply the next frame by, moving toward full volume or ducked.
    func nextGain(ducked: Bool) -> Float {

        // 1. start a new fade from wherever we are now.
        let wantedDB: Float = ducked ? duckDB : 0 // if ducked, then duckDB, else 0 dB (full volume)
        if wantedDB != targetDB {
            startDB = currentDB
            targetDB = wantedDB
            progress = 0
        }

        // 2. fade finished: nothing to compute
        if progress >= 1 {return currentGain}

        // 3. One frame step forward. Ducking uses fast step. Releasing uses slow step.
        progress = min(progress + (ducked ? downStep : upStep), 1)

        // 4. Smoothstep: slow at both ends, faster in middle
        let eased = progress * progress * (3 - 2 * progress)

        // 5. Interpolate (estimate) in dB, then convert to multiplier.
        currentDB = startDB + (targetDB - startDB) * eased
        currentGain = pow(10, currentDB / 20)

        return currentGain
    }
}
