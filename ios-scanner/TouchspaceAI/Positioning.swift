import SwiftUI
import ARKit
import SceneKit
import TouchspaceCore

/// Device validation is mandatory even when a server has checked the package structure.
enum WorldMapValidator {
    static func decode(_ package: MapPackage) throws -> ARWorldMap {
        guard package.manifest.worldMapIncluded, let data=package.worldData,
              let map=try NSKeyedUnarchiver.unarchivedObject(ofClass:ARWorldMap.self,from:data) else { throw MapError("This map has no valid AR world data. Use map-only exploration.") }
        let name="touchspace-frame:"+package.manifest.coordinateFrameId.uuidString.lowercased()
        guard let anchor=map.anchors.first(where:{$0.identifier==package.manifest.frameAnchorId && $0.name==name}), identity(anchor.transform) else { throw MapError("Saved frame anchor is missing or misaligned. Live positioning is unavailable.") }
        guard map.rawFeaturePoints.points.count>=10 else { throw MapError("Saved world data has too few visual features for relocalization.") }
        return map
    }
    static func validate(_ package: MapPackage) throws { if package.manifest.worldMapIncluded { _=try decode(package) } }
    static func identity(_ transform: simd_float4x4) -> Bool {
        for c in 0..<4 { for r in 0..<4 { if !transform[c][r].isFinite || abs(transform[c][r] - (c==r ? 1:0))>0.02 { return false } } }
        return true
    }
}
@MainActor final class Positioning: NSObject, ObservableObject, @preconcurrency ARSessionDelegate {
    let session=ARSession()
    @Published private(set) var status: Tracking = .failed
    @Published private(set) var pose: Pose?
    @Published private(set) var explanation="Map-only exploration. Start live exploration to position your phone."
    private var package: MapPackage?
    private var gate=LocalizationGate()
    private var deadline: Date?
    private var timer: Timer?
    private var lastFrame=Date.distantPast
    private var running=false
    private var generation=0
    override init() { super.init(); session.delegate=self; session.delegateQueue = .main }
    func start(_ package: MapPackage) async {
        stop(); let ticket=generation; self.package=package
        guard ARWorldTrackingConfiguration.isSupported else { fail("AR world tracking is not supported on this device. Map-only exploration is available."); return }
        let authorized=await AVCaptureDevice.requestAccess(for:.video)
        guard ticket==generation else{return}
        guard authorized else { fail("Camera access is required for automatic positioning. Enable it in Settings or explore the map without positioning."); return }
        do {
            let world=try WorldMapValidator.decode(package)
            gate.reset(); status = .relocalizing; pose=nil; running=true
            explanation="Slowly pan your camera around the scanned space. Position is uncertain until the saved map is recovered."
            let config=ARWorldTrackingConfiguration(); config.initialWorldMap=world; config.worldAlignment = .gravity
            deadline=Date().addingTimeInterval(45)
            session.delegate=self; session.delegateQueue = .main
            session.run(config,options:[.resetTracking,.removeExistingAnchors])
            timer=Timer.scheduledTimer(withTimeInterval:0.5,repeats:true) { [weak self] _ in
                MainActor.assumeIsolated { self?.checkTimeout() }
            }
        } catch { fail(error.localizedDescription) }
    }
    func stop() {
        generation += 1; timer?.invalidate(); timer=nil; session.pause(); running=false; pose=nil; gate.fail(); status = .failed
    }
    private func checkTimeout() {
        if let deadline, Date()>deadline, status != .localized { fail("Automatic positioning failed. The space may have changed or the camera may not see enough familiar features. Retry or continue map-only.") }
        if status == .localized, Date().timeIntervalSince(lastFrame)>2 { loseTracking("Camera updates stopped. Guidance is paused.") }
    }
    private func fail(_ message:String) { stop(); explanation=message }
    private func loseTracking(_ message:String) {
        guard running else { return }
        gate.update(normalTracking:false,recoveredFrameAnchor:false); status = .limited; pose=nil; explanation=message
        if deadline==nil { deadline=Date().addingTimeInterval(45) }
    }
    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        guard running,let package,Date().timeIntervalSince(lastFrame)>0.12 else { return }
        lastFrame=Date()
        let normal: Bool
        if case .normal=frame.camera.trackingState { normal=true } else { normal=false }
        let anchorName="touchspace-frame:"+package.manifest.coordinateFrameId.uuidString.lowercased()
        let recovered=frame.anchors.contains{$0.identifier==package.manifest.frameAnchorId && $0.name==anchorName && WorldMapValidator.identity($0.transform)}
        gate.update(normalTracking:normal,recoveredFrameAnchor:recovered)
        status=gate.status
        if gate.canGuide {
            deadline=nil
            let t=frame.camera.transform
            // ARKit camera looks down local -Z. Project this direction onto the horizontal plane.
            let fx = -Double(t.columns.2.x), fz = -Double(t.columns.2.z)
            guard hypot(fx,fz)>0.25 else { loseTracking("Camera is pointing too far toward the floor or ceiling; horizontal heading is uncertain. Tilt it toward the room."); return }
            let p=Point(x:Double(t.columns.3.x),z:Double(t.columns.3.z))
            guard SpatialEngine(package:package).room(at:p) != nil else { loseTracking("Your phone is outside the surveyed rooms. Guidance is paused."); return }
            pose=Pose(coordinateFrameId:package.manifest.coordinateFrameId,position:p,heading:atan2(fx,-fz),tracking:.localized,frameVerified:true)
            explanation="Localized in the saved map. Directions follow your phone, which may face differently from your body."
        } else {
            pose=nil
            explanation=status == .limited ? "Tracking is limited. Precise guidance is paused; slowly pan the camera to recover the map." : "Relocalizing. Slowly pan your camera around familiar scanned features."
            if deadline==nil { deadline=Date().addingTimeInterval(45) }
        }
    }
    func session(_ session:ARSession,didFailWithError error:Error) { fail("Tracking failed: "+error.localizedDescription) }
    func sessionWasInterrupted(_ session:ARSession) { loseTracking("Camera session interrupted. Guidance is paused.") }
    func sessionInterruptionEnded(_ session:ARSession) { loseTracking("Camera resumed. Retry live exploration to verify your position.") }
}
import AVFoundation
struct CameraPreview: UIViewRepresentable {
    var session: ARSession
    func makeUIView(context:Context) -> ARSCNView { let view=ARSCNView(frame:.zero); view.session=session; view.automaticallyUpdatesLighting=true; return view }
    func updateUIView(_ view:ARSCNView,context:Context) {}
}
