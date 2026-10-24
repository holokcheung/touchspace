import Foundation

public struct MapError: LocalizedError, Equatable {
    public let message: String
    public init(_ message: String) { self.message = message }
    public var errorDescription: String? { message }
}
public struct Point: Codable, Equatable, Hashable, Sendable {
    public var x: Double
    public var z: Double
    public init(x: Double, z: Double) { self.x = x; self.z = z }
    public func distance(to p: Point) -> Double { hypot(x-p.x, z-p.z) }
}
public struct Manifest: Codable, Equatable, Sendable {
    public var schemaVersion: Int = 1
    public var mapId: String
    public var title: String
    public var floor: String
    public var coverage: String
    public var contributor: String
    public var createdAt: String
    public var updatedAt: String
    public var verification: String = "unverified"
    public var units: String = "meters"
    public var coordinateFrameId: UUID
    public var frameAnchorId: UUID
    public var worldMapIncluded: Bool
    public var synthetic: Bool = false
    public init(mapId: String, title: String, floor: String, coverage: String, contributor: String, coordinateFrameId: UUID, frameAnchorId: UUID, worldMapIncluded: Bool) {
        self.mapId=mapId; self.title=title; self.floor=floor; self.coverage=coverage; self.contributor=contributor
        self.coordinateFrameId=coordinateFrameId; self.frameAnchorId=frameAnchorId; self.worldMapIncluded=worldMapIncluded
        createdAt=ISO8601DateFormatter().string(from: Date()); updatedAt=createdAt
    }
}
public extension Manifest {
    /// Server date serializers may normalize equivalent ISO-8601 timestamp spellings.
    func matchesCatalog(_ other: Manifest) -> Bool {
        func normalized(_ s: String) -> String? {
            let formatter=ISO8601DateFormatter(); formatter.formatOptions=[.withInternetDateTime,.withFractionalSeconds]
            return (formatter.date(from:s) ?? ISO8601DateFormatter().date(from:s)).map { String($0.timeIntervalSince1970) }
        }
        var a=self,b=other
        guard let ac=normalized(a.createdAt),let au=normalized(a.updatedAt),let bc=normalized(b.createdAt),let bu=normalized(b.updatedAt) else{return false}
        a.createdAt=ac; a.updatedAt=au; b.createdAt=bc; b.updatedAt=bu
        return a==b
    }
}
public struct Room: Codable, Identifiable, Equatable, Sendable {
    public var id: String; public var name: String; public var polygon: [Point]
    public init(id: String, name: String, polygon: [Point]) { self.id=id; self.name=name; self.polygon=polygon }
}
public struct Wall: Codable, Identifiable, Equatable, Sendable {
    public var id: String; public var a: Point; public var b: Point
    public init(id: String, a: Point, b: Point) { self.id=id; self.a=a; self.b=b }
}
public struct Obstacle: Codable, Identifiable, Equatable, Sendable {
    public var id: String; public var polygon: [Point]
    public init(id: String, polygon: [Point]) { self.id=id; self.polygon=polygon }
}
// Preserve the complete RoomPlan JSON without coupling this portable library to ARKit.
public enum JSONValue: Codable, Equatable, Sendable {
    case object([String: JSONValue]), array([JSONValue]), string(String), number(Double), bool(Bool), null
    public init(from decoder: Decoder) throws {
        let c=try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let v=try? c.decode(Bool.self) { self = .bool(v) }
        else if let v=try? c.decode(Double.self) { self = .number(v) }
        else if let v=try? c.decode(String.self) { self = .string(v) }
        else if let v=try? c.decode([JSONValue].self) { self = .array(v) }
        else { self = .object(try c.decode([String: JSONValue].self)) }
    }
    public func encode(to encoder: Encoder) throws {
        var c=encoder.singleValueContainer()
        switch self { case .object(let v): try c.encode(v); case .array(let v): try c.encode(v); case .string(let v): try c.encode(v); case .number(let v): try c.encode(v); case .bool(let v): try c.encode(v); case .null: try c.encodeNil() }
    }
}
public struct Geometry: Codable, Equatable, Sendable {
    public var coordinateFrameId: UUID
    public var transform: [Double]
    public var rooms: [Room]
    public var walls: [Wall]
    public var obstacles: [Obstacle]
    public var capturedRoom: JSONValue?
    public static let identity: [Double] = [1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]
    public init(coordinateFrameId: UUID, rooms: [Room], walls: [Wall], obstacles: [Obstacle], capturedRoom: JSONValue? = nil) {
        self.coordinateFrameId=coordinateFrameId; transform=Self.identity; self.rooms=rooms; self.walls=walls; self.obstacles=obstacles; self.capturedRoom=capturedRoom
    }
}
public struct Landmark: Codable, Identifiable, Equatable, Sendable {
    public var id: String; public var name: String; public var type: String; public var position: Point; public var roomId: String; public var nodeId: String?; public var provenance: String
    public init(id: String, name: String, type: String, position: Point, roomId: String, nodeId: String?, provenance: String = "volunteer") {
        self.id=id; self.name=name; self.type=type; self.position=position; self.roomId=roomId; self.nodeId=nodeId; self.provenance=provenance
    }
}
public struct Landmarks: Codable, Equatable, Sendable {
    public var coordinateFrameId: UUID; public var landmarks: [Landmark]
    public init(coordinateFrameId: UUID, landmarks: [Landmark]) { self.coordinateFrameId=coordinateFrameId; self.landmarks=landmarks }
}
public struct Node: Codable, Identifiable, Equatable, Sendable {
    public var id: String; public var position: Point; public var roomId: String
    public init(id: String, position: Point, roomId: String) { self.id=id; self.position=position; self.roomId=roomId }
}
public struct Door: Codable, Identifiable, Equatable, Sendable {
    public var id: String; public var name: String; public var rooms: [String]; public var position: Point; public var width: Double; public var traversable: Bool
    public init(id: String, name: String, rooms: [String], position: Point, width: Double, traversable: Bool = false) {
        self.id=id; self.name=name; self.rooms=rooms; self.position=position; self.width=width; self.traversable=traversable
    }
}
public struct Edge: Codable, Equatable, Sendable {
    public var a: String; public var b: String; public var doorId: String?
    public init(a: String, b: String, doorId: String? = nil) { self.a=a; self.b=b; self.doorId=doorId }
}
public struct Navigation: Codable, Equatable, Sendable {
    public var coordinateFrameId: UUID; public var clearance: Double; public var nodes: [Node]; public var edges: [Edge]; public var doors: [Door]
    public init(coordinateFrameId: UUID, clearance: Double = 0.3, nodes: [Node], edges: [Edge], doors: [Door]) {
        self.coordinateFrameId=coordinateFrameId; self.clearance=clearance; self.nodes=nodes; self.edges=edges; self.doors=doors
    }
}
public enum Tracking: String, Codable, Sendable { case relocalizing, localized, limited, failed }
public struct Pose: Codable, Equatable, Sendable {
    public var coordinateFrameId: UUID; public var position: Point; public var heading: Double; public var tracking: Tracking; public var frameVerified: Bool; public var timestamp: Date
    public init(coordinateFrameId: UUID, position: Point, heading: Double, tracking: Tracking, frameVerified: Bool, timestamp: Date = Date()) {
        self.coordinateFrameId=coordinateFrameId; self.position=position; self.heading=heading; self.tracking=tracking; self.frameVerified=frameVerified; self.timestamp=timestamp
    }
    public func stillMatches(_ submitted: Pose?, for manifest: Manifest, now: Date = Date()) -> Bool {
        guard let submitted, isUsable(for:manifest,now:now), submitted.isUsable(for:manifest,now:now) else {return false}
        let angle=atan2(sin(heading-submitted.heading),cos(heading-submitted.heading))
        return position.distance(to:submitted.position)<=0.5 && abs(angle)<=0.2
    }
    public func isUsable(for manifest: Manifest, now: Date = Date()) -> Bool {
        tracking == .localized && frameVerified && manifest.worldMapIncluded && coordinateFrameId == manifest.coordinateFrameId && now.timeIntervalSince(timestamp) < 10 && now.timeIntervalSince(timestamp) >= -3
    }
}
public struct Route: Codable, Equatable, Sendable {
    public var nodeIds: [String]; public var waypoints: [Point]; public var distanceMeters: Double
    public init(nodeIds: [String], waypoints: [Point], distanceMeters: Double) { self.nodeIds=nodeIds; self.waypoints=waypoints; self.distanceMeters=distanceMeters }
}
