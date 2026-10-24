import Foundation

public struct LocalizationGate: Sendable {
    public private(set) var status: Tracking = .relocalizing
    public private(set) var frameVerified = false
    public var canGuide: Bool { status == .localized && frameVerified }
    public init() {}
    public mutating func update(normalTracking: Bool, recoveredFrameAnchor: Bool) {
        frameVerified=recoveredFrameAnchor
        if normalTracking && recoveredFrameAnchor { status = .localized }
        else if status == .localized || status == .limited { status = .limited }
        else { status = .relocalizing }
    }
    public mutating func fail() { status = .failed; frameVerified=false }
    public mutating func reset() { status = .relocalizing; frameVerified=false }
}
public enum GuidanceState: String, Sendable { case idle, navigating, paused, trackingLost, offRoute, arrived }
public struct Guidance: Sendable {
    public private(set) var state: GuidanceState = .idle
    public private(set) var route: Route?
    public private(set) var nextIndex=0
    public private(set) var instruction="Choose a destination to start navigation."
    public private(set) var cue: RelativeDirection?
    public init() {}
    public mutating func start(_ route: Route) {
        self.route=route; nextIndex=0; state = .navigating; cue=nil
        instruction="Route ready. Guidance is relative to the direction your phone faces."
    }
    public mutating func pause() { state = .paused; cue=nil; instruction="Navigation paused." }
    public mutating func end() { self=Guidance() }
    public mutating func update(pose: Pose?, engine: SpatialEngine) {
        guard state == .navigating, let route else { cue=nil; return }
        guard let pose, pose.isUsable(for:engine.package.manifest), engine.room(at:pose.position) != nil else {
            state = .trackingLost; cue=nil; instruction="Position is uncertain. Guidance paused. Relocalize, then resume."; return
        }
        let start=max(0,nextIndex-1), tail=Array(route.waypoints.dropFirst(start))
        let nearest=zip(tail,tail.dropFirst()).map{SpatialEngine.pointSegmentDistance(pose.position,$0,$1)}.min() ?? tail.first.map{pose.position.distance(to:$0)} ?? .infinity
        if nearest>1.0 { state = .offRoute; cue=nil; instruction="You appear off the planned route. Stop and resume to calculate a new route."; return }
        while nextIndex<route.waypoints.count && pose.position.distance(to:route.waypoints[nextIndex])<(nextIndex==route.waypoints.count-1 ? 0.55:0.25) { nextIndex += 1 }
        guard nextIndex<route.waypoints.count else { state = .arrived; cue=nil; instruction="You have reached the mapped destination waypoint. The exact landmark may be nearby."; return }
        guard engine.segmentValid(pose.position,route.waypoints[nextIndex]) else { state = .offRoute; cue=nil; instruction="The next waypoint has no clear mapped connection from your position. Guidance paused. Resume to recalculate."; return }
        let relative=engine.relative(from:pose,to:route.waypoints[nextIndex]); cue=relative
        let movement=relative.direction == "ahead" ? "Continue ahead" : relative.direction == "behind" ? "Turn around with care" : "Turn \(relative.direction)"
        instruction="\(movement). Next waypoint \(String(format:"%.1f",relative.distanceMeters)) meters away, relative to your phone."
    }
}

public struct AssistantAnswer: Equatable, Sendable {
    public var reply: String
    public var sourceIds: [String]
    public var destinationId: String?
    public init(reply: String, sourceIds: [String] = [], destinationId: String? = nil) { self.reply=reply; self.sourceIds=sourceIds; self.destinationId=destinationId }
}
/// Deterministic offline fallback. Connected conversational interpretation lives on the backend.
public struct LocalAssistant: Sendable {
    public private(set) var lastTargetId: String?
    public init() {}
    public mutating func answer(_ message: String, package: MapPackage, pose: Pose?) -> AssistantAnswer {
        let text=message.lowercased(), engine=SpatialEngine(package:package)
        let matches=package.landmarks.landmarks.filter { text.contains($0.name.lowercased()) || text.contains($0.id.lowercased()) || ($0.type != "other" && text.contains($0.type)) }
        let refers=["there","it","that","this"].contains { text.split(whereSeparator:{!$0.isLetter}).contains(Substring($0)) }
        var target=matches.count==1 ? matches.first : nil
        if target==nil, refers, let id=lastTargetId { target=package.landmarks.landmarks.first{$0.id==id} }
        if let target { lastTargetId=target.id }
        if text.contains("connect") {
            let facts=package.navigation.doors.map { d in
                let names=d.rooms.compactMap { rid in package.geometry.rooms.first{$0.id==rid}?.name }.joined(separator:" and ")
                return "\(d.name) links \(names). \(d.traversable ? "Volunteer marked traversable; current conditions are unknown." : "Traversability is unknown; routes cannot use it.")"
            }
            return AssistantAnswer(reply:facts.isEmpty ? "No room connections are recorded." : facts.joined(separator:" "),sourceIds:package.navigation.doors.map(\.id))
        }
        let wantsRoute=["route","get to","navigate","go to","take me","how far"].contains{text.contains($0)}
        let directions=["right","left","ahead","behind"], direction=directions.first{text.contains($0)}
        if wantsRoute || direction != nil || text.contains("where am i") || text.contains("nearby") {
            guard let pose, pose.isUsable(for:package.manifest), engine.room(at:pose.position) != nil else { return AssistantAnswer(reply:"Position is uncertain. Live directions are paused. You can ask about the map's rooms, landmarks, and connections.") }
            if wantsRoute {
                guard let target else { return AssistantAnswer(reply:"Choose a recorded landmark by name. I do not know that destination.") }
                do {
                    let route=try engine.route(from:pose,to:target)
                    return AssistantAnswer(reply:"The mapped route to \(target.name) is \(String(format:"%.1f",route.distanceMeters)) meters to its waypoint. Start navigation to follow it. Current obstacles and door conditions are unknown.",sourceIds:[target.id]+route.nodeIds,destinationId:target.id)
                } catch { return AssistantAnswer(reply:error.localizedDescription,sourceIds:[target.id]) }
            }
            if text.contains("where am i"), let room=engine.room(at:pose.position) { return AssistantAnswer(reply:"Your phone is mapped in \(room.name). This does not establish the direction your body faces.",sourceIds:[room.id]) }
            let nearby=package.landmarks.landmarks.map { ($0,engine.relative(from:pose,to:$0.position)) }.filter { direction==nil || $0.1.direction==direction }.sorted{$0.1.distanceMeters<$1.1.distanceMeters}.prefix(5)
            return AssistantAnswer(reply:nearby.isEmpty ? "No recorded landmarks are \(direction ?? "nearby") relative to your phone." : nearby.map{"\($0.0.name), \(String(format:"%.1f",$0.1.distanceMeters)) meters \($0.1.direction) relative to your phone (straight-line map distance)."}.joined(separator:" "),sourceIds:nearby.map{$0.0.id})
        }
        if let target, !["open","closed","color","colour","hours","safe","accessible","crowded"].contains(where:{text.contains($0)}) {
            let room=package.geometry.rooms.first{$0.id==target.roomId}?.name ?? "unknown room"
            return AssistantAnswer(reply:"\(target.name) is recorded in \(room), with a \(target.provenance == "scan" ? "scan-derived" : "volunteer-provided") label. Its current condition is unknown.",sourceIds:[target.id,target.roomId])
        }
        if ["overview","rooms","describe","landmarks","map","space","hello"].contains(where:{text.contains($0)}) {
            return AssistantAnswer(reply:"\(package.manifest.title) covers \(package.geometry.rooms.map(\.name).joined(separator:", ")). Recorded landmarks: \(package.landmarks.landmarks.map(\.name).joined(separator:", ")). Verification: \(package.manifest.verification). \(package.warnings.joined(separator:" "))",sourceIds:package.geometry.rooms.map(\.id)+package.landmarks.landmarks.map(\.id))
        }
        return AssistantAnswer(reply:"That is unknown from this map. Ask about recorded rooms, landmark names, connections, or routes. Current obstacles, opening hours, and door conditions are not recorded.")
    }
}
