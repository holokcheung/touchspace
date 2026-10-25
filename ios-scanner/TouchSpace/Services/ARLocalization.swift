import ARKit
import Combine
import RealityKit
import SwiftUI

@MainActor final class ARLocalization: NSObject, ObservableObject, ARSessionDelegate {
    enum Status: String { case relocalizing = "Relocalizing", localized = "Localized", limited = "Tracking limited", failed = "Failed" }
    @Published private(set) var status = Status.relocalizing
    @Published private(set) var instruction = "Look around slowly at walls and distinctive features in the saved venue."
    @Published private(set) var pose: VerifiedPose?
    @Published var error: String?
    let view = ARView(frame:.zero,cameraMode:.ar,automaticallyConfigureSession:false)
    let package: MapPackage
    let worldMap: ARWorldMap
    let spatial: SpatialEngine
    var onPose: ((VerifiedPose,TimeInterval) -> Void)?
    var onSuspended: ((String) -> Void)?
    private var routeAnchor: AnchorEntity?
    private var watchdog: Timer?
    private var started = 0.0
    private var lastFrame = 0.0
    private var lastProcessed = 0.0
    private var verifier: LocalizationVerifier
    private var sawRelocalizing = false
    private var interrupted = false
    private var running = false
    init(package: MapPackage, worldMap: ARWorldMap) throws {
        guard !package.manifest.isSynthetic else { throw TouchSpaceError.invalid("Synthetic fixtures cannot authorize physical AR navigation.") }
        self.package = package; self.worldMap = worldMap; spatial = try SpatialEngine(package)
        verifier = LocalizationVerifier(frameId:package.manifest.coordinateFrameId,anchorId:package.manifest.frameAnchorId)
        super.init()
        view.session.delegate = self
        view.environment.background = .cameraFeed()
    }
    func start() {
        guard ARWorldTrackingConfiguration.isSupported else { fail("AR tracking is unavailable on this device. Use map-only exploration."); return }
        clearRoute(); pose = nil; verifier.reset()
        sawRelocalizing = false; interrupted = false; running = true
        started = ProcessInfo.processInfo.systemUptime; lastFrame = started; lastProcessed = 0
        setStatus(.relocalizing,"Look around slowly at walls and distinctive features in the saved venue.")
        let configuration = ARWorldTrackingConfiguration()
        configuration.initialWorldMap = worldMap
        configuration.planeDetection = [.horizontal]
        view.session.run(configuration,options:[.resetTracking,.removeExistingAnchors])
        watchdog?.invalidate()
        watchdog = Timer.scheduledTimer(withTimeInterval:0.25,repeats:true) { [weak self] _ in Task { @MainActor in self?.checkFreshness() } }
    }
    func stop() {
        running = false; watchdog?.invalidate(); watchdog = nil; view.session.pause(); clearRoute(); pose = nil
    }
    func retry() { start() }
    private func checkFreshness() {
        guard running else { return }
        let now = ProcessInfo.processInfo.systemUptime
        if now-lastFrame > 0.6 { suspend("Tracking frames are stale. Pause and look around.") }
        if status != .localized && now-started > 45 { fail("Could not verify the saved coordinate frame. Retry at the scanned venue or explore the map.") }
    }
    private func setStatus(_ new: Status, _ text: String) {
        if status != new || instruction != text {
            status = new; instruction = text
            UIAccessibility.post(notification:.announcement,argument:"\(new.rawValue). \(text)")
        }
    }
    private func suspend(_ message: String) {
        let wasLocalized = status == .localized
        pose = nil; verifier.reset(); clearRoute()
        setStatus(.limited,message)
        if wasLocalized { onSuspended?(message) }
    }
    private func fail(_ message: String) {
        pose = nil; clearRoute(); running = false; watchdog?.invalidate(); view.session.pause()
        setStatus(.failed,message); onSuspended?(message)
    }
    nonisolated func session(_ session: ARSession, didUpdate frame: ARFrame) {
        Task { @MainActor [weak self] in self?.process(frame) }
    }
    private func process(_ frame: ARFrame) {
        guard running, !interrupted else { return }
        let now = ProcessInfo.processInfo.systemUptime
        guard now-frame.timestamp < 0.3 && now-frame.timestamp >= -0.1 else { suspend("Waiting for fresh camera tracking."); return }
        lastFrame = now
        switch frame.camera.trackingState {
        case .limited(.relocalizing):
            if status == .localized { onSuspended?("ARKit is relocalizing. Precise guidance is suspended.") }
            sawRelocalizing = true; pose = nil; verifier.reset(); clearRoute()
            setStatus(.relocalizing,"Look around at the saved venue. Matching the coordinate-frame anchor."); return
        case .normal: break
        default:
            suspend("Camera tracking is uncertain. Pause and look around slowly."); return
        }
        guard frame.timestamp-lastProcessed >= 0.1 else { return }
        lastProcessed = frame.timestamp
        guard sawRelocalizing else { suspend("Waiting for ARKit to verify restoration of the saved world map."); return }
        let expectedName = "touchspace-frame:\(package.manifest.coordinateFrameId.uuidString.lowercased())"
        guard let expected = worldMap.anchors.first(where: { $0.identifier == package.manifest.frameAnchorId }),
              let restored = frame.anchors.first(where: { $0.identifier == package.manifest.frameAnchorId && $0.name?.lowercased() == expectedName }) else {
            suspend("The saved frame anchor has not been restored."); return
        }
        let a = expected.transform, b = restored.transform
        let translationError = simd_distance(a.columns.3,b.columns.3)
        let rotationError = simd_length(a.columns.0-b.columns.0)+simd_length(a.columns.2-b.columns.2)
        let camera = frame.camera.transform
        let position = package.geometry.mapToWorld.map(.init(x:Double(camera.columns.3.x),z:Double(camera.columns.3.z)))
        let height = Double(camera.columns.3.y)-package.geometry.mapToWorld.y-package.geometry.floorY
        let evidence = LocalizationVerifier.Evidence(frameTime:frame.timestamp,now:now,didRelocalize:sawRelocalizing,
            trackingNormal:true,anchorId:restored.identifier,anchorName:restored.name,
            translationError:Double(translationError),rotationError:Double(rotationError),position:position,
            cameraHeight:height,insideScannedRoom:spatial.room(at:position) != nil)
        switch verifier.observe(evidence) {
        case .verified: break
        case .waiting(let message):
            // Do not reset the verifier's stability window while collecting evidence.
            if status == .localized { suspend(message) }
            else { setStatus(.relocalizing,message) }
            return
        }
        let heading = package.geometry.mapToWorld.mapHeading(atan2(-Double(camera.columns.2.x),Double(camera.columns.2.z)))
        let verified = VerifiedPose(position:position,heading:heading,coordinateFrameId:package.manifest.coordinateFrameId,
                                    observedAt:ISO8601DateFormatter().string(from:Date()),verified:true)
        pose = verified
        setStatus(.localized,"Saved frame anchor and room alignment verified. Direction uses the phone's facing heading.")
        onPose?(verified,frame.timestamp)
    }
    nonisolated func session(_ session: ARSession, didFailWithError error: Error) {
        Task { @MainActor [weak self] in self?.fail("AR session failed. Retry localization or explore the map.") }
    }
    nonisolated func sessionWasInterrupted(_ session: ARSession) {
        Task { @MainActor [weak self] in self?.interrupted = true; self?.suspend("Camera session interrupted. Precise guidance is suspended.") }
    }
    nonisolated func sessionInterruptionEnded(_ session: ARSession) {
        Task { @MainActor [weak self] in self?.interrupted = false; self?.start() }
    }
    nonisolated func sessionShouldAttemptRelocalization(_ session: ARSession) -> Bool { true }
    func clearRoute() { routeAnchor?.removeFromParent(); routeAnchor = nil }
    func render(_ route: PlannedRoute, next: MapPoint? = nil) {
        clearRoute()
        guard status == .localized else { return }
        let anchor = AnchorEntity(world:.zero)
        let transform = package.geometry.mapToWorld
        let y = Float(package.geometry.floorY+transform.y+0.045)
        func position(_ p: MapPoint) -> SIMD3<Float> { let w = transform.world(p); return [Float(w.x),y,Float(w.z)] }
        let material = SimpleMaterial(color:.systemYellow,isMetallic:false)
        for (a,b) in zip(route.waypoints,route.waypoints.dropFirst()) {
            let start = position(a), end = position(b), length = simd_distance(start,end)
            guard length > 0.005 else { continue }
            let segment = ModelEntity(mesh:.generateBox(size:[0.09,0.035,length]),materials:[material])
            segment.position = (start+end)/2
            segment.orientation = simd_quatf(from:[0,0,1],to:simd_normalize(end-start))
            anchor.addChild(segment)
        }
        if let next {
            let marker = ModelEntity(mesh:.generateSphere(radius:0.12),materials:[SimpleMaterial(color:.cyan,isMetallic:false)])
            marker.position = position(next)+[0,0.12,0]; anchor.addChild(marker)
        }
        if let last = route.waypoints.last {
            let marker = ModelEntity(mesh:.generateBox(size:[0.25,0.5,0.25]),materials:[SimpleMaterial(color:.systemGreen,isMetallic:false)])
            marker.position = position(last)+[0,0.25,0]; anchor.addChild(marker)
        }
        view.scene.addAnchor(anchor); routeAnchor = anchor
    }
}

struct CameraView: UIViewRepresentable {
    let localization: ARLocalization
    func makeUIView(context:Context) -> ARView { localization.view }
    func updateUIView(_ uiView:ARView,context:Context) {}
}
