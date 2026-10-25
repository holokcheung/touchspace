import ARKit
import RoomPlan
import SwiftUI

@MainActor final class RoomScanner: NSObject, ObservableObject, RoomCaptureSessionDelegate {
    @Published var scanning = false
    @Published var processing = false
    @Published var package: MapPackage?
    @Published var error: String?
    @Published var instruction = "Scan one contiguous zone. Keep the same capture session when adding rooms."
    @Published var roomCount = 0
    let arSession = ARSession()
    lazy var captureView = RoomCaptureView(frame:.zero,arSession:arSession)
    let frameId = UUID()
    private var frameAnchor: ARAnchor?
    private var rooms: [CapturedRoom] = []
    private var continuityLost = false
    func startRoom() {
        error = nil
        guard RoomCaptureSession.isSupported else { error = "RoomPlan requires a LiDAR iPhone or iPad. You can still import and explore maps."; return }
        if !rooms.isEmpty {
            guard let frame = arSession.currentFrame, case .normal = frame.camera.trackingState,
                  let anchor = frameAnchor, frame.anchors.contains(where: { $0.identifier == anchor.identifier }) else {
                continuityLost = true; error = "The shared AR frame was lost. Save the existing zone or start a new scan; independently scanned rooms cannot be joined."; return
            }
        }
        guard !continuityLost else { error = "Start a new scan to establish a coherent coordinate frame."; return }
        captureView.captureSession.delegate = self
        captureView.isModelEnabled = false
        captureView.captureSession.run(configuration:RoomCaptureSession.Configuration())
        scanning = true
        instruction = "Move slowly to capture walls, furniture and floor. Finish this room before adding the next."
    }
    func finishRoom() {
        guard scanning else { return }
        scanning = false; processing = true
        captureView.captureSession.stop(pauseARSession:false)
    }
    func stop() { captureView.captureSession.stop(pauseARSession:true); arSession.pause() }
    nonisolated func captureSession(_ session:RoomCaptureSession,didStartWith configuration:RoomCaptureSession.Configuration) {
        Task { @MainActor [weak self] in
            guard let self else { return }
            if self.frameAnchor == nil {
                let anchor = ARAnchor(name:"touchspace-frame:\(self.frameId.uuidString.lowercased())",transform:matrix_identity_float4x4)
                self.frameAnchor = anchor; self.arSession.add(anchor:anchor)
            }
        }
    }
    nonisolated func captureSession(_ session:RoomCaptureSession,didEndWith data:CapturedRoomData,error:Error?) {
        Task { @MainActor [weak self] in
            guard let self else { return }
            defer { self.processing = false }
            guard error == nil else { self.continuityLost = true; self.error = "Room capture failed and frame continuity is uncertain. Start a new scan."; return }
            do {
                let room = try await RoomBuilder(options:[.beautifyObjects]).capturedRoom(from:data)
                guard let anchor = self.frameAnchor, self.arSession.currentFrame?.anchors.contains(where: { $0.identifier == anchor.identifier }) == true else {
                    self.continuityLost = true; throw TouchSpaceError.invalid("Coordinate-frame continuity was lost during capture.")
                }
                self.rooms.append(room); self.roomCount = self.rooms.count
                self.package = try self.normalize()
                self.instruction = "Room saved in this session. Add an adjacent room, or review labels and doorway links."
            } catch { self.error = error.localizedDescription }
        }
    }
    nonisolated func captureSession(_ session:RoomCaptureSession,didProvide instruction:RoomCaptureSession.Instruction) {
        Task { @MainActor [weak self] in
            let text: String
            switch instruction {
            case .moveCloseToWall: text = "Move closer to the wall."
            case .moveAwayFromWall: text = "Move away from the wall."
            case .slowDown: text = "Move more slowly."
            case .turnOnLight: text = "More light is needed."
            case .lowTexture: text = "Look toward a more distinctive wall or object."
            default: return
            }
            if self?.instruction != text { self?.instruction = text; UIAccessibility.post(notification:.announcement,argument:text) }
        }
    }
    func snapshot() async throws -> ARWorldMap {
        guard !continuityLost, !scanning, !processing, let frame = arSession.currentFrame,
              case .normal = frame.camera.trackingState,
              frame.worldMappingStatus == .mapped || frame.worldMappingStatus == .extending else {
            throw TouchSpaceError.invalid("Finish the room and look around until AR mapping is stable before saving.")
        }
        let map: ARWorldMap = try await withCheckedThrowingContinuation { continuation in
            arSession.getCurrentWorldMap { map,error in
                if let error { continuation.resume(throwing:error) }
                else if let map { continuation.resume(returning:map) }
                else { continuation.resume(throwing:TouchSpaceError.invalid("No AR world data was captured.")) }
            }
        }
        guard let anchor = frameAnchor, map.anchors.contains(where: { $0.identifier == anchor.identifier }) else { throw TouchSpaceError.invalid("World map is missing its frame anchor.") }
        return map
    }
    private func normalize() throws -> MapPackage {
        guard let frameAnchor else { throw TouchSpaceError.invalid("No frame anchor.") }
        func project(_ t:simd_float4x4,_ p:SIMD3<Float>) -> MapPoint {
            let world = t*SIMD4<Float>(p.x,p.y,p.z,1)
            return .init(x:Double(world.x),z:Double(world.z))
        }
        var geometry = MapGeometry(rooms:[],walls:[],obstacles:[],floorY:0)
        var candidates: [(String,MapPoint,MapPoint)] = []
        var floorHeights: [Double] = []
        for (index,room) in rooms.enumerated() {
            guard !room.floors.isEmpty, room.walls.allSatisfy({ $0.curve == nil }) else { throw TouchSpaceError.invalid("This MVP requires scanned floor polygons and straight walls. Curved walls need a new supported zone.") }
            for (floorIndex,floor) in room.floors.enumerated() {
                guard floor.polygonCorners.count >= 3 else { throw TouchSpaceError.invalid("No scanned floor boundary. Rescan instead of estimating an unscanned polygon.") }
                let polygon = floor.polygonCorners.map { project(floor.transform,$0) }
                let id = room.identifier.uuidString.lowercased()+"-\(floorIndex)"
                geometry.rooms.append(.init(id:id,name:"Room \(index+1)\(floorIndex == 0 ? "" : " area \(floorIndex+1)")",polygon:polygon))
                floorHeights += floor.polygonCorners.map { Double((floor.transform*SIMD4<Float>($0.x,$0.y,$0.z,1)).y) }
            }
            for wall in room.walls {
                geometry.walls.append(.init(id:wall.identifier.uuidString.lowercased(),start:project(wall.transform,[-wall.dimensions.x/2,0,0]),end:project(wall.transform,[wall.dimensions.x/2,0,0])))
            }
            for item in room.objects {
                // Project all eight OBB corners conservatively, preserving rotated furniture.
                let corners = [-1.0,1.0].flatMap { x in [-1.0,1.0].flatMap { y in [-1.0,1.0].map { z in project(item.transform,[Float(x)*item.dimensions.x/2,Float(y)*item.dimensions.y/2,Float(z)*item.dimensions.z/2]) } } }
                geometry.obstacles.append(.init(id:item.identifier.uuidString.lowercased(),polygon:convexHull(corners)))
            }
            for opening in room.doors+room.openings {
                candidates.append((opening.identifier.uuidString.lowercased(),project(opening.transform,[-opening.dimensions.x/2,0,0]),project(opening.transform,[opening.dimensions.x/2,0,0])))
            }
        }
        guard let low = floorHeights.min(), let high = floorHeights.max(), high-low < 0.25 else { throw TouchSpaceError.invalid("Multiple floor levels are not supported in a single zone.") }
        geometry.floorY = floorHeights.reduce(0,+)/Double(floorHeights.count)
        // Stable IDs may repeat along shared walls when adjacent rooms are scanned.
        geometry.walls = Array(Dictionary(geometry.walls.map { ($0.id,$0) },uniquingKeysWith:{ a,_ in a }).values).sorted { $0.id < $1.id }
        geometry.obstacles = Array(Dictionary(geometry.obstacles.map { ($0.id,$0) },uniquingKeysWith:{ a,_ in a }).values).sorted { $0.id < $1.id }
        var doors: [MapDoor] = []
        for (id,a,b) in candidates {
            let center = (a+b)*0.5, d = b-a, length = a.distance(to:b)
            guard length > 0.1 else { continue }
            let normal = MapPoint(x:-d.z/length*0.4,z:d.x/length*0.4)
            let associations = geometry.rooms.filter { polygonContains(center+normal,$0.polygon) || polygonContains(center-normal,$0.polygon) }.map(\.id)
            guard !associations.isEmpty && associations.count <= 2 else { continue }
            for wall in geometry.walls where segmentDistance(a,wall.start,wall.end) <= 0.15 && segmentDistance(b,wall.start,wall.end) <= 0.15 {
                let doorId = id+":"+wall.id
                if !doors.contains(where: { $0.id == doorId }) {
                    doors.append(.init(id:doorId,wallId:wall.id,roomIds:associations,start:a,end:b))
                }
            }
        }
        // Combined IDs use two UUIDs (73 chars), safely within contract limits.
        let manifest = MapManifest(id:UUID(),venue:"New space",floor:"Ground floor",contributor:"Volunteer",
                                   createdAt:ISO8601DateFormatter().string(from:Date()),coordinateFrameId:frameId,frameAnchorId:frameAnchor.identifier)
        let package = MapPackage(manifest:manifest,geometry:geometry,landmarks:.init(landmarks:[]),navigation:.init(doors:doors))
        try PackageCodec.validate(package)
        return package
    }
}

func convexHull(_ input:[MapPoint]) -> [MapPoint] {
    let points = Set(input).sorted { $0.x == $1.x ? $0.z < $1.z : $0.x < $1.x }
    guard points.count > 2 else { return points }
    func cross(_ a:MapPoint,_ b:MapPoint,_ c:MapPoint) -> Double { (b.x-a.x)*(c.z-a.z)-(b.z-a.z)*(c.x-a.x) }
    func half(_ values:[MapPoint]) -> [MapPoint] {
        var result: [MapPoint] = []
        for p in values {
            while result.count >= 2 && cross(result[result.count-2],result.last!,p) <= 0 { result.removeLast() }
            result.append(p)
        }
        return result
    }
    return Array(half(points).dropLast())+Array(half(points.reversed()).dropLast())
}

struct RoomCaptureCamera: UIViewRepresentable {
    let scanner: RoomScanner
    func makeUIView(context:Context) -> RoomCaptureView { scanner.captureView }
    func updateUIView(_ uiView:RoomCaptureView,context:Context) {}
}
