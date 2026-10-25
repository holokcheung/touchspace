import Foundation

/// Deliberately cannot be encoded as VerifiedPose or sent as physical tracking.
struct SimulatedPose: Equatable {
    var position: MapPoint
    var heading: Double
}

struct SimulationEngine {
    let package: MapPackage
    let spatial: SpatialEngine
    private(set) var pose: SimulatedPose
    private(set) var route: PlannedRoute?
    private(set) var destinationId: String?
    private(set) var following = false
    private(set) var arrived = false
    private var waypointIndex = 1
    private var guidance: GuidanceEngine?
    private var time = 0.0
    private let initialPose: SimulatedPose

    init(package: MapPackage, currentPose: SimulatedPose? = nil) throws {
        guard package.manifest.isSynthetic else { throw TouchSpaceError.invalid("Virtual walkthroughs require an explicitly synthetic map.") }
        self.package = package
        let engine = try SpatialEngine(package)
        spatial = engine
        let candidates = package.landmarks.landmarks.sorted { ($0.kind == "entrance" ? 0 : 1) < ($1.kind == "entrance" ? 0 : 1) }
        guard let start = candidates.first(where: { engine.walkable($0.position) }) else { throw TouchSpaceError.invalid("This map has no clear starting location for the simulation.") }
        let startPose = SimulatedPose(position:start.position,heading:.pi/2)
        if let currentPose, !engine.walkable(currentPose.position) { throw TouchSpaceError.invalid("Virtual position lacks scanned clearance.") }
        pose = currentPose ?? startPose; initialPose = startPose
    }
    mutating func plan(to id: String) throws {
        following = false; arrived = false
        // Clear any previous route before a potentially impossible request.
        route = nil; guidance = nil; destinationId = nil
        let planned = try spatial.route(from:pose.position,to:id)
        route = planned; destinationId = id; guidance = GuidanceEngine(route:planned); waypointIndex = 1
    }
    mutating func follow() throws {
        guard let destinationId else { throw TouchSpaceError.invalid("Choose a destination first.") }
        // Reuse a fresh preview. Replan after manual movement or paused playback.
        if route?.waypoints.first != pose.position || waypointIndex != 1 || arrived { try plan(to:destinationId) }
        following = true
    }
    mutating func pause() { following = false }
    mutating func clearRoute() { route = nil; guidance = nil; destinationId = nil; following = false; arrived = false }
    mutating func reset() {
        pose = initialPose; route = nil; guidance = nil; destinationId = nil; following = false; arrived = false; waypointIndex = 1; time = 0
    }
    mutating func turn(_ radians: Double) { following = false; pose.heading = normalizedAngle(pose.heading+radians) }
    @discardableResult mutating func move(_ metres: Double) -> Bool {
        following = false; arrived = false
        let next = pose.position+MapPoint(x:sin(pose.heading),z:-cos(pose.heading))*metres
        guard spatial.clearSegment(pose.position,next) else { return false }
        pose.position = next
        return true
    }
    /// Advance a virtual walker along validated segments; no teleporting or body-pose inference.
    mutating func tick(seconds: Double) -> GuidanceUpdate? {
        let dt = max(0,min(0.25,seconds)); time += dt
        guard let route, !arrived else { return nil }
        if following {
            var budget = 0.9*dt
            while budget > 1e-8 && waypointIndex < route.waypoints.count {
                let target = route.waypoints[waypointIndex], delta = target-pose.position
                let distance = pose.position.distance(to:target)
                if distance < 1e-6 { waypointIndex += 1; continue }
                let step = min(budget,distance), next = pose.position+delta*(step/distance)
                guard spatial.clearSegment(pose.position,next) else { following = false; return .init(remaining:0,waypoint:target,instruction:"Simulation paused: the next segment is blocked.",urgent:true) }
                pose.heading = atan2(delta.x,-delta.z); pose.position = next; budget -= step
                if step >= distance-1e-7 { waypointIndex += 1 }
            }
        }
        guard var update = guidance?.update(position:pose.position,heading:pose.heading,time:time) else { return nil }
        if update.shouldReroute, let destinationId {
            do { try plan(to:destinationId); update.instruction = "Simulation route recalculated." }
            catch { update.instruction = error.localizedDescription }
        }
        if update.arrived { arrived = true; following = false }
        return update
    }
}
