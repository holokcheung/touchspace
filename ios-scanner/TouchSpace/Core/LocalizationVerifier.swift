import Foundation

/// Evidence policy kept independent of ARKit for repeatable failure/recovery tests.
/// A decoded archive or normal tracking alone can never authorize guidance.
struct LocalizationVerifier {
    struct Evidence {
        var frameTime: Double
        var now: Double
        var didRelocalize: Bool
        var trackingNormal: Bool
        var anchorId: UUID?
        var anchorName: String?
        var translationError: Double
        var rotationError: Double
        var position: MapPoint
        var cameraHeight: Double
        var insideScannedRoom: Bool
    }
    enum Result: Equatable { case verified, waiting(String) }
    let frameId: UUID
    let anchorId: UUID
    private var stableSince: Double?
    private var previous: (MapPoint,Double)?
    mutating func reset() { stableSince=nil; previous=nil }
    mutating func observe(_ evidence: Evidence) -> Result {
        func reason() -> String? {
            guard evidence.frameTime.isFinite && evidence.now.isFinite && evidence.now-evidence.frameTime < 0.3 && evidence.now-evidence.frameTime >= -0.1 else { return "Waiting for fresh camera tracking." }
            guard evidence.didRelocalize && evidence.trackingNormal else { return "Waiting for ARKit to verify restoration of the saved world map." }
            guard evidence.anchorId == anchorId && evidence.anchorName?.lowercased() == "touchspace-frame:\(frameId.uuidString.lowercased())" else { return "The expected coordinate-frame anchor has not been restored." }
            guard evidence.translationError.isFinite && evidence.rotationError.isFinite && evidence.translationError < 0.08 && evidence.rotationError < 0.08 else { return "Coordinate-frame anchor alignment is inconsistent. Retry localization." }
            guard evidence.insideScannedRoom && evidence.cameraHeight > 0.35 && evidence.cameraHeight < 2.8 else { return "The camera pose does not match the saved room and floor." }
            if let previous {
                let delta = evidence.frameTime-previous.1
                guard delta > 0 else { return "Waiting for a new camera frame." }
                if delta > 0.6 { return "Tracking frames were interrupted. Verify alignment again." }
                if evidence.position.distance(to:previous.0)/delta > 3 { return "An unexpected tracking jump was detected. Pause to verify alignment." }
            }
            return nil
        }
        if let message = reason() {
            stableSince=nil
            // A jump becomes a new candidate, never a corrected or snapped pose.
            previous=(evidence.position,evidence.frameTime)
            return .waiting(message)
        }
        previous=(evidence.position,evidence.frameTime)
        if stableSince == nil { stableSince=evidence.frameTime }
        guard evidence.frameTime-stableSince! >= 1.2 else { return .waiting("Verifying consistent pose and room alignment. Hold the phone steadily.") }
        return .verified
    }
}
