import SwiftUI

@MainActor final class NavigationSession: ObservableObject {
    let localization: ARLocalization
    let audio = AudioGuidance()
    let package: MapPackage
    @Published var route: PlannedRoute?
    @Published var destination: Landmark?
    @Published var paused = false
    @Published var planning = false
    @Published var remaining = 0.0
    @Published var nextAction = "Choose a destination after automatic localization."
    @Published var error: String?
    private var guidance: GuidanceEngine?
    private var lastUpdate = 0.0
    private var lastWaypoint: MapPoint?
    private var generation = 0
    init(package:MapPackage,url:URL) throws {
        self.package = package
        localization = try ARLocalization(package:package,worldMap:PackageCodec.worldMap(url,manifest:package.manifest))
        localization.onPose = { [weak self] pose,time in
            DotPadLink.shared.sendMapPose(pose.position,heading:pose.heading)
            self?.update(pose,time:time)
        }
        localization.onSuspended = { [weak self] text in
            DotPadLink.shared.sendNoPose()
            guard let self else { return }
            self.generation += 1; self.planning = false; self.paused = true
            self.audio.stop(); self.audio.say(text,urgent:true)
            self.nextAction = "Guidance suspended. Relocalize, then Resume."
        }
        DotPadLink.shared.sendMap(package)
    }
    func navigate(to target:Landmark) {
        guard let pose = localization.pose, localization.status == .localized else { error = "Verify automatic localization before starting guidance."; return }
        generation += 1; let taskGeneration = generation
        planning = true; paused = true; audio.stop(); localization.clearRoute()
        let package = package
        Task {
            do {
                let planned = try await Task.detached(priority:.userInitiated) { try SpatialEngine(package).route(from:pose.position,to:target.id) }.value
                guard taskGeneration == generation else { return }
                planning = false
                guard let current = localization.pose, localization.status == .localized, current.position.distance(to:pose.position) < 0.5 else { error = "Pose changed while planning. Pause and select the destination again."; return }
                destination = target; route = planned; guidance = GuidanceEngine(route:planned)
                remaining = planned.distance; paused = false; lastWaypoint = nil
                nextAction = "Route ready to \(target.name), \(Int(planned.distance.rounded())) metres."
                audio.say(nextAction,urgent:true); localization.render(planned,next:planned.waypoints.dropFirst().first)
            } catch {
                guard taskGeneration == generation else { return }
                planning = false; route = nil; guidance = nil; self.error = error.localizedDescription
                audio.say(error.localizedDescription,urgent:true)
            }
        }
    }
    private func update(_ pose:VerifiedPose,time:Double) {
        guard !paused, !planning, route != nil, time-lastUpdate > 0.35 else { return }
        lastUpdate = time
        guard let result = guidance?.update(position:pose.position,heading:pose.heading,time:time) else { return }
        remaining = result.remaining
        if let text = result.instruction { nextAction = text; audio.say(text,urgent:result.urgent) }
        if result.shouldReroute, let destination { navigate(to:destination); return }
        if result.arrived { paused = true; localization.clearRoute(); audio.stop(); audio.say("You have reached \(destination?.name ?? "the saved destination").",urgent:true); return }
        if result.waypoint != lastWaypoint, let route {
            localization.render(route,next:result.waypoint); lastWaypoint = result.waypoint
        }
        audio.beacon(relativeBearing:localization.spatial.relativeBearing(from:pose.position,heading:pose.heading,to:result.waypoint))
    }
    func togglePause() {
        if paused {
            guard localization.status == .localized else { error = "Localization is not verified. Retry before resuming."; return }
            if let destination { navigate(to:destination) }
            else { paused = false }
        } else {
            generation += 1; planning = false; paused = true; audio.stop(); localization.clearRoute()
            nextAction = "Guidance paused. You can inspect the map without walking."
            audio.say(nextAction,urgent:true)
        }
    }
    func end() {
        generation += 1; route = nil; guidance = nil; destination = nil; planning = false; paused = true
        audio.stop(); localization.clearRoute(); nextAction = "Navigation ended."
    }
    func stop() { end(); localization.stop(); DotPadLink.shared.sendNoPose() }
    func interruptForQuestion() { audio.stop(); if !paused { togglePause() }; audio.stop() }
}
