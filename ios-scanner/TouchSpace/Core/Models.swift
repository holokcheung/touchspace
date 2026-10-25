import Foundation

// All portable coordinates use ARKit X/Z in metres. Heading is clockwise from -Z.
struct MapPoint: Codable, Hashable {
    var x: Double
    var z: Double
    func distance(to p: Self) -> Double { hypot(x-p.x, z-p.z) }
    static func +(a: Self, b: Self) -> Self { .init(x: a.x+b.x, z: a.z+b.z) }
    static func -(a: Self, b: Self) -> Self { .init(x: a.x-b.x, z: a.z-b.z) }
    static func *(a: Self, b: Double) -> Self { .init(x: a.x*b, z: a.z*b) }
}
struct MapTransform: Codable {
    var x = 0.0, z = 0.0, yaw = 0.0, y = 0.0
    func world(_ p: MapPoint) -> MapPoint {
        .init(x: cos(yaw)*p.x-sin(yaw)*p.z+x, z: sin(yaw)*p.x+cos(yaw)*p.z+z)
    }
    func map(_ p: MapPoint) -> MapPoint {
        let a = p.x-x, b = p.z-z
        return .init(x: cos(yaw)*a+sin(yaw)*b, z: -sin(yaw)*a+cos(yaw)*b)
    }
    func mapHeading(_ world: Double) -> Double { normalizedAngle(world-yaw) }
}
func normalizedAngle(_ a: Double) -> Double { atan2(sin(a), cos(a)) }
struct MapRoom: Codable, Identifiable {
    var id: String
    var name: String
    var polygon: [MapPoint]
}
struct MapWall: Codable, Identifiable {
    var id: String
    var start: MapPoint
    var end: MapPoint
    var thickness = 0.15
}
struct MapObstacle: Codable, Identifiable {
    var id: String
    var polygon: [MapPoint]
}
struct MapGeometry: Codable {
    var rooms: [MapRoom]
    var walls: [MapWall]
    var obstacles: [MapObstacle]
    var floorY: Double
    var mapToWorld = MapTransform()
}
struct Landmark: Codable, Identifiable {
    var id: String
    var name: String
    var roomId: String
    var position: MapPoint
    var kind = "destination"
}
struct MapLandmarks: Codable { var landmarks: [Landmark] }
struct MapDoor: Codable, Identifiable {
    var id: String
    var wallId: String
    var roomIds: [String]
    var start: MapPoint
    var end: MapPoint
    var traversability = "unknown"
}
struct MapNode: Codable, Identifiable {
    var id: String
    var position: MapPoint
    var roomId: String
}
struct MapEdge: Codable {
    var source: String
    var target: String
    var confirmed: Bool
    var clearance: Double
}
struct MapNavigation: Codable {
    var resolution = 0.1
    var clearance = 0.3
    var doors: [MapDoor] = []
    var nodes: [MapNode] = []
    var edges: [MapEdge] = []
}
struct MapManifest: Codable, Identifiable {
    var schemaVersion = "1.0"
    var id: UUID
    var venue: String
    var floor: String
    var coverage = "partial"
    var contributor: String
    var verification = "unverified"
    var createdAt: String
    var coordinateFrameId: UUID
    var frameAnchorId: UUID
    var provenance = "roomplan-same-session"
    var isSynthetic: Bool { provenance == "synthetic-fixture" }
    var checksums: [String: String] = [:]
}
struct MapPackage: Codable, Identifiable {
    var manifest: MapManifest
    var geometry: MapGeometry
    var landmarks: MapLandmarks
    var navigation: MapNavigation
    var id: UUID { manifest.id }
}
struct MapSummary: Codable, Identifiable {
    var manifest: MapManifest
    var visibility: String
    var id: UUID { manifest.id }
}
struct VerifiedPose: Codable {
    var position: MapPoint
    var heading: Double
    var coordinateFrameId: UUID
    var observedAt: String
    var verified: Bool
}
struct NavigationAction: Codable {
    var type: String
    var destinationId: String
}
struct ChatReply: Codable {
    var answer: String
    var actions: [NavigationAction]
    var providerUsed: Bool
    var requiresLocalization: Bool
}
/// Chat transports virtual coordinates separately from physical AR verification.
struct SimulatedChatPose: Encodable {
    var position: MapPoint
    var heading: Double
    var coordinateFrameId: UUID
    var observedAt: String
}
struct MapChatRequest: Encodable {
    var mapId: UUID
    var sessionId: UUID
    var message: String
    var pose: VerifiedPose?
    var simulatedPose: SimulatedChatPose?
    var mapPackage: MapPackage

    init(package: MapPackage, session: UUID, message: String, pose: VerifiedPose? = nil, simulatedPose: SimulatedPose? = nil) {
        mapId = package.id; sessionId = session; self.message = message; mapPackage = package
        self.pose = simulatedPose == nil ? pose : nil
        self.simulatedPose = simulatedPose.map {
            SimulatedChatPose(position:$0.position,heading:$0.heading,coordinateFrameId:package.manifest.coordinateFrameId,
                              observedAt:ISO8601DateFormatter().string(from:Date()))
        }
    }
}
struct PlannedRoute {
    var destinationId: String
    var waypoints: [MapPoint]
    var distance: Double { zip(waypoints, waypoints.dropFirst()).reduce(0) { $0+$1.0.distance(to: $1.1) } }
}
enum TouchSpaceError: LocalizedError {
    case invalid(String)
    var errorDescription: String? { if case .invalid(let message) = self { return message }; return nil }
}
