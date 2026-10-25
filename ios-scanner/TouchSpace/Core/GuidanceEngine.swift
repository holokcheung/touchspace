import Foundation

struct GuidanceUpdate {
    var remaining: Double
    var waypoint: MapPoint
    var instruction: String?
    var urgent = false
    var arrived = false
    var shouldReroute = false
}
/// Route projection is progress measurement only; it never changes the AR pose.
struct GuidanceEngine {
    var route: PlannedRoute
    var lastKey = ""
    var announced: Set<String> = []
    var offRouteSince: TimeInterval?
    var lastReroute = -Double.infinity
    var progress = 0.0
    var arrivalCount = 0
    var approachDistance = 4.0
    var turnThreshold = Double.pi/6
    var substantialTurn = Double.pi/3
    mutating func update(position: MapPoint, heading: Double, time: TimeInterval) -> GuidanceUpdate {
        let points = route.waypoints
        guard let last = points.last, points.count > 1 else {
            return .init(remaining:0,waypoint:route.waypoints.last ?? position,instruction:"You are at the saved destination.",arrived:true)
        }
        var bestDistance = Double.infinity, bestProgress = 0.0, bestIndex = 0, cumulative = 0.0
        for i in 0..<(points.count-1) {
            let a = points[i], b = points[i+1], d = b-a, length = a.distance(to:b)
            guard length > 1e-8 else { continue }
            let q = position-a, t = max(0,min(1,(q.x*d.x+q.z*d.z)/(length*length)))
            let separation = position.distance(to:a+d*t), along = cumulative+length*t
            // Do not jump across a nearby later corridor at self-adjacent route sections.
            if separation < bestDistance && along >= progress-0.75 && along <= progress+max(3,position.distance(to:points[bestIndex])+1) {
                bestDistance = separation; bestProgress = along; bestIndex = i
            }
            cumulative += length
        }
        let remaining = max(0,route.distance-bestProgress)
        var result = GuidanceUpdate(remaining:remaining,waypoint:points[min(bestIndex+1,points.count-1)])
        if bestDistance > 0.8 {
            if offRouteSince == nil { offRouteSince = time }
            if time-offRouteSince! > 2 && time-lastReroute > 5 {
                result.shouldReroute = true; result.urgent = true
                result.instruction = "You have moved away from the route. Pause while a validated route is recalculated."
                lastReroute = time
            }
            return result
        }
        offRouteSince = nil; progress = max(progress,bestProgress)
        if position.distance(to:last) < 0.65 && remaining < 0.8 {
            arrivalCount += 1
            if arrivalCount >= 3 {
                result.arrived = true
                result.instruction = announce("arrival","You have reached the saved destination.")
            }
            return result
        }
        arrivalCount = 0
        // Find the next substantive maneuver, beyond short grid and doorway samples.
        let currentHeading = atan2(points[bestIndex+1].x-points[bestIndex].x,-(points[bestIndex+1].z-points[bestIndex].z))
        var toTurn = position.distance(to:points[bestIndex+1])
        for index in (bestIndex+1)..<(points.count-1) {
            let nextHeading = atan2(points[index+1].x-points[index].x,-(points[index+1].z-points[index].z))
            let angle = normalizedAngle(nextHeading-currentHeading)
            // Tiny alternating 45-degree grid steps are not human maneuvers.
            let outgoingLength = points[index].distance(to:points[index+1])
            if abs(angle) >= turnThreshold && (outgoingLength >= 0.5 || abs(angle) >= substantialTurn) {
                let direction = angle > 0 ? "right" : "left"
                let action = abs(angle) >= substantialTurn ? "Turn \(direction)" : "Bear \(direction)"
                if toTurn < 0.75 { result.instruction = announce("now-\(index)","\(action) now. Phone direction may differ from your body.") }
                else if toTurn <= approachDistance { result.instruction = announce("approach-\(index)","In \(Int(toTurn.rounded())) metres, \(action.lowercased()).") }
                break
            }
            toTurn += points[index].distance(to:points[index+1])
        }
        let bearing = normalizedAngle(atan2(result.waypoint.x-position.x,-(result.waypoint.z-position.z))-heading)
        if result.instruction == nil && abs(bearing) > substantialTurn && position.distance(to:result.waypoint) > 0.6 {
            result.instruction = announce("heading-\(bestIndex)","The next waypoint is to the \(bearing > 0 ? "right" : "left") of the phone's facing direction.")
        }
        if result.instruction == nil && lastKey.isEmpty { result.instruction = announce("start","Follow the saved route for \(Int(remaining.rounded())) metres. Remain aware of your surroundings.") }
        return result
    }
    private mutating func announce(_ key: String, _ text: String) -> String? {
        guard !announced.contains(key) else { return nil }
        announced.insert(key); lastKey = key
        return text
    }
}
