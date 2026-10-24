import Foundation

/// The soundscape numbers shared with the web walk-through (shared/soundscape.json, bundled
/// into the app). Not used by any screen yet: it's here so a live LiDAR soundscape maps
/// distance to sound exactly as the web version does. See docs/soundscape.md.
struct SoundscapeSettings: Decodable {
    struct Zone: Decodable {
        let id: String
        let label: String
        let fromDeg: Double
        let toDeg: Double
    }

    struct CameraZones: Decodable {
        /// Slices of the depth image, as fractions of its width: [from, to].
        let left: [Double]
        let ahead: [Double]
        let right: [Double]
        let minConfidence: String
        let staleAfterS: Double
    }

    struct Sensing: Decodable {
        let maxRangeM: Double
        let rayStepDeg: Double
        let lidarCameraZones: CameraZones
    }

    struct Noise: Decodable {
        let color: String
        let level: Double
        let defaultVolume: Double
        let smoothingS: Double
    }

    struct Muffle: Decodable {
        let openAtM: Double
        let muffledAtM: Double
        let curve: Double
        let openCutoffHz: Double
        let muffledCutoffHz: Double
        let openGain: Double
        let muffledGain: Double
        let filterQ: Double
    }

    struct AheadPulse: Decodable {
        let startAtM: Double
        let fastestAtM: Double
        let slowestHz: Double
        let fastestHz: Double
        let tickHz: Double
        let tickS: Double
        let level: Double
    }

    struct Cue: Decodable {
        let freqsHz: [Double]
        let durationS: Double
        let vibrateMs: [Double]
        let repeatS: Double?
    }

    struct Cues: Decodable {
        let bump: Cue
        let doorway: Cue
        let noData: Cue
        let level: Double
    }

    let version: Int
    let zones: [Zone]
    let sensing: Sensing
    let noise: Noise
    let muffle: Muffle
    let aheadPulse: AheadPulse
    let cues: Cues

    static func loadBundled(_ bundle: Bundle = .main) throws -> SoundscapeSettings {
        guard let url = bundle.url(forResource: "soundscape", withExtension: "json") else {
            throw CocoaError(.fileNoSuchFile)
        }
        return try load(from: url)
    }

    static func load(from url: URL) throws -> SoundscapeSettings {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(SoundscapeSettings.self, from: Data(contentsOf: url))
    }

    /// How muffled one ear is for the nearest surface on that side (nil = nothing in range).
    /// Same formula as muffleFor() in frontend/src/lib/soundscape.ts.
    func muffle(forDistance distance: Double?) -> (amount: Double, cutoffHz: Double, gain: Double) {
        let m = muffle
        var t = 0.0
        if let d = distance {
            t = min(1, max(0, (m.openAtM - d) / (m.openAtM - m.muffledAtM)))
        }
        let amount = t == 0 ? 0 : pow(t, m.curve)
        let cutoff = m.openCutoffHz * pow(m.muffledCutoffHz / m.openCutoffHz, amount)
        return (amount, cutoff, m.openGain + (m.muffledGain - m.openGain) * amount)
    }

    /// Ticks per second for something straight ahead, or nil for no ticks. Same as pulseRateFor().
    func pulseRate(forDistance distance: Double?) -> Double? {
        let p = aheadPulse
        guard let d = distance, d <= p.startAtM else { return nil }
        let t = min(1, max(0, (p.startAtM - d) / (p.startAtM - p.fastestAtM)))
        return p.slowestHz + (p.fastestHz - p.slowestHz) * t
    }
}
