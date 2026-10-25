import Foundation

struct ExplorationReply {
    var answer: String
    var destinationId: String? = nil
}

/// Saved-map exploration works without an uploaded catalog entry or an API key.
/// Simulation coordinates are never converted into physical tracking confidence.
enum OfflineMapAssistant {
    static func answer(_ message: String, package: MapPackage, simulatedPose: SimulatedPose? = nil) throws -> ExplorationReply {
        let text = message.folding(options:[.caseInsensitive,.diacriticInsensitive],locale:.current)
        let places = package.landmarks.landmarks
        let rooms = Dictionary(package.geometry.rooms.map { ($0.id,$0.name) },uniquingKeysWith:{ a,_ in a })
        let prefix = simulatedPose != nil ? "In this simulation, " : "On the saved map, "
        let matches = places.filter { text.contains($0.name.lowercased()) || text.contains($0.id.lowercased()) }
        let specific = matches.filter { text.contains(rooms[$0.roomId,default:""] .lowercased()) || text.contains($0.roomId.lowercased()) }
        let resolved = specific.count == 1 ? specific : matches
        if resolved.count > 1 {
            return .init(answer:"Which destination do you mean? " + resolved.map { "\($0.name) in \(rooms[$0.roomId,default:$0.roomId]) (\($0.id))" }.joined(separator:"; "))
        }
        if let place = resolved.first {
            let wantsRoute = ["route","directions","navigate","take me","guide me","walk to","go to","how far"].contains { text.contains($0) }
            if wantsRoute {
                guard let simulatedPose else { return .init(answer:"\(place.name) is in \(rooms[place.roomId,default:place.roomId]). Use Preview route to choose a saved starting point, or open the 3D walkthrough to simulate navigation.") }
                let route = try SpatialEngine(package).route(from:simulatedPose.position,to:place.id)
                let wantsAction = ["navigate","take me","guide me","walk to","go to"].contains { text.contains($0) }
                    && !["don't","do not","stop","cancel"].contains { text.contains($0) }
                return .init(answer:"Simulation route to \(place.name): \(String(format:"%.1f",route.distance)) metres through validated doorways.",destinationId:wantsAction ? place.id : nil)
            }
            if ["left","right","ahead","behind","bearing"].contains(where:{ text.contains($0) }) {
                guard let simulatedPose else { return .init(answer:"A direction needs a position and heading. Open the 3D walkthrough to test simulated left/right bearings.") }
                let angle = normalizedAngle(atan2(place.position.x-simulatedPose.position.x,-(place.position.z-simulatedPose.position.z))-simulatedPose.heading)
                let direction = abs(angle) <= .pi/6 ? "ahead" : abs(angle) >= .pi*5/6 ? "behind" : angle > 0 ? "right" : "left"
                return .init(answer:prefix+"\(place.name) is \(String(format:"%.1f",simulatedPose.position.distance(to:place.position))) metres \(direction) of the virtual camera's facing direction.")
            }
            if text.contains("near") { return nearby(package,origin:place.position,excluding:place.id,prefix:prefix) }
            return .init(answer:prefix+"\(place.name) is in \(rooms[place.roomId,default:place.roomId]).")
        }
        if text.contains("near"), let simulatedPose { return nearby(package,origin:simulatedPose.position,excluding:nil,prefix:prefix) }
        if text.contains("where am") || text.contains("my location") {
            guard let simulatedPose else { return .init(answer:"Map exploration has no live position. The 3D walkthrough provides an explicitly simulated position.") }
            let room = try SpatialEngine(package).room(at:simulatedPose.position)?.name ?? "unknown area"
            return .init(answer:"Your virtual position is in \(room). This is not a physical location fix.")
        }
        let matchingRooms = package.geometry.rooms.filter { text.contains($0.name.lowercased()) || text.contains($0.id.lowercased()) }
        if let room = matchingRooms.first, text.contains("connect") || text.contains("door") {
            let links = Set(package.navigation.doors.filter { $0.traversability == "confirmed" && $0.roomIds.contains(room.id) }.flatMap(\.roomIds).filter { $0 != room.id })
            return .init(answer:prefix+"\(room.name) has confirmed door links to \(links.sorted().map { rooms[$0,default:$0] }.joined(separator:", ")). Unknown and blocked doors remain closed to routing.")
        }
        return .init(answer:"\(package.manifest.isSynthetic ? "Synthetic" : "Saved") map of \(package.manifest.venue). Coverage: \(package.manifest.coverage). Rooms: \(package.geometry.rooms.map(\.name).joined(separator:", ")). Destinations: \(places.map(\.name).joined(separator:", ")). Ask where a destination is, what's nearby, or choose it to preview a route.")
    }
    private static func nearby(_ package: MapPackage, origin: MapPoint, excluding: String?, prefix: String) -> ExplorationReply {
        let nearby = package.landmarks.landmarks.filter { $0.id != excluding && origin.distance(to:$0.position) <= 5 }.sorted { origin.distance(to:$0.position) < origin.distance(to:$1.position) }
        return .init(answer:prefix+"nearby destinations within 5 metres are " + (nearby.isEmpty ? "none" : nearby.map { "\($0.name), \(String(format:"%.1f",origin.distance(to:$0.position))) metres" }.joined(separator:"; ")) + ". Distances are straight-line map distances.")
    }
}
