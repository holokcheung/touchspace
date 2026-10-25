import Foundation

func segmentDistance(_ p: MapPoint, _ a: MapPoint, _ b: MapPoint) -> Double {
    let d = b-a, q = p-a
    let t = max(0, min(1, (q.x*d.x+q.z*d.z) / max(1e-20, d.x*d.x+d.z*d.z)))
    return p.distance(to: a+d*t)
}
func polygonContains(_ p: MapPoint, _ polygon: [MapPoint]) -> Bool {
    guard polygon.count >= 3 else { return false }
    var result = false
    for i in polygon.indices {
        let a = polygon[i], b = polygon[(i+1)%polygon.count]
        if segmentDistance(p, a, b) < 1e-7 { return true }
        if (a.z > p.z) != (b.z > p.z), p.x < (b.x-a.x)*(p.z-a.z)/(b.z-a.z)+a.x { result.toggle() }
    }
    return result
}

struct GridCell: Hashable, Comparable {
    var x: Int, z: Int
    static func <(a: Self, b: Self) -> Bool { a.x == b.x ? a.z < b.z : a.x < b.x }
}
private struct QueueItem: Comparable {
    var score: Double
    var cell: GridCell
    static func <(a: Self, b: Self) -> Bool { a.score == b.score ? a.cell < b.cell : a.score < b.score }
}
private struct MinHeap {
    var values: [QueueItem] = []
    mutating func push(_ item: QueueItem) {
        values.append(item)
        var i = values.count-1
        while i > 0 {
            let parent = (i-1)/2
            if !(values[i] < values[parent]) { break }
            values.swapAt(i,parent); i = parent
        }
    }
    mutating func pop() -> QueueItem? {
        guard !values.isEmpty else { return nil }
        if values.count == 1 { return values.removeLast() }
        let first = values[0]; values[0] = values.removeLast()
        var i = 0
        while i*2+1 < values.count {
            var child = i*2+1
            if child+1 < values.count, values[child+1] < values[child] { child += 1 }
            if !(values[child] < values[i]) { break }
            values.swapAt(i,child); i = child
        }
        return first
    }
}

/// Same occupancy predicates, grid, tie ordering and A* costs as app.touchspace.spatial.
final class SpatialEngine {
    let package: MapPackage
    private let minX: Int, maxX: Int, minZ: Int, maxZ: Int
    private var passages: [(MapDoor,[MapPoint])] = []
    private var wallSegments: [(MapPoint,MapPoint,Double)] = []
    private var cache: [GridCell: Bool] = [:]
    var visibleWallSegments: [(MapPoint,MapPoint,Double)] { wallSegments }
    init(_ package: MapPackage) throws {
        self.package = package
        let all = package.geometry.rooms.flatMap(\.polygon)
        guard !all.isEmpty, all.allSatisfy({ $0.x.isFinite && $0.z.isFinite && abs($0.x) <= 1000 && abs($0.z) <= 1000 }),
              package.navigation.resolution == 0.1, (0.2...0.8).contains(package.navigation.clearance) else {
            throw TouchSpaceError.invalid("Invalid geometry or grid settings.")
        }
        minX = Int(floor(all.map(\.x).min()!/0.1)); maxX = Int(ceil(all.map(\.x).max()!/0.1))
        minZ = Int(floor(all.map(\.z).min()!/0.1)); maxZ = Int(ceil(all.map(\.z).max()!/0.1))
        guard (maxX-minX+1)*(maxZ-minZ+1) <= 300_000 else { throw TouchSpaceError.invalid("Zone exceeds the supported grid size.") }
        for door in package.navigation.doors where door.traversability == "confirmed" && door.roomIds.count == 2 {
            guard let wall = package.geometry.walls.first(where:{ $0.id == door.wallId }),
                  let a = package.geometry.rooms.first(where:{ $0.id == door.roomIds[0] }),
                  let b = package.geometry.rooms.first(where:{ $0.id == door.roomIds[1] }) else { continue }
            let d = door.end-door.start, length = door.start.distance(to:door.end)
            guard length > 1e-6 else { continue }
            let reach = wall.thickness/2+0.2, center = (door.start+door.end)*0.5
            let normal = MapPoint(x:-d.z/length*reach,z:d.x/length*reach)
            guard (polygonContains(center+normal,a.polygon) && polygonContains(center-normal,b.polygon)) ||
                  (polygonContains(center-normal,a.polygon) && polygonContains(center+normal,b.polygon)) else { continue }
            passages.append((door,[door.start+normal,door.end+normal,door.end-normal,door.start-normal]))
        }
        for wall in package.geometry.walls {
            let d = wall.end-wall.start, length = wall.start.distance(to: wall.end)
            guard length > 1e-6 else { throw TouchSpaceError.invalid("Zero-length wall.") }
            var cuts: [(Double,Double)] = [(0,1)]
            for door in package.navigation.doors where door.wallId == wall.id && door.traversability == "confirmed" {
                let ts = [door.start,door.end].map { p in ((p.x-wall.start.x)*d.x+(p.z-wall.start.z)*d.z)/(length*length) }.sorted()
                let lo = max(0,ts[0]), hi = min(1,ts[1])
                cuts = cuts.flatMap { a,b -> [(Double,Double)] in [(a,min(b,lo)),(max(a,hi),b)].filter { $0.1-$0.0 > 1e-6 } }
            }
            wallSegments += cuts.map { (wall.start+d*$0.0,wall.start+d*$0.1,wall.thickness) }
        }
        let nodes = Dictionary(package.navigation.nodes.map { ($0.id,$0) }, uniquingKeysWith: { a,_ in a })
        for edge in package.navigation.edges where edge.confirmed {
            guard let a = nodes[edge.source], let b = nodes[edge.target], edge.clearance >= package.navigation.clearance,
                  clearSegment(a.position,b.position) else { throw TouchSpaceError.invalid("Graph edge crosses blocked or unknown space.") }
        }
    }
    func room(at point: MapPoint) -> MapRoom? {
        if let room = package.geometry.rooms.first(where:{ polygonContains(point,$0.polygon) }) { return room }
        if let passage = passages.first(where:{ polygonContains(point,$0.1) }) {
            return package.geometry.rooms.first { $0.id == passage.0.roomIds[0] }
        }
        return nil
    }
    func covered(_ p: MapPoint) -> Bool { room(at:p) != nil }
    func walkable(_ p: MapPoint) -> Bool {
        let clearance = package.navigation.clearance
        guard covered(p) else { return false }
        for i in 0..<16 {
            let a = Double(i)*Double.pi/8
            if !covered(.init(x:p.x+clearance*cos(a),z:p.z+clearance*sin(a))) { return false }
        }
        if wallSegments.contains(where: { segmentDistance(p,$0.0,$0.1) < clearance+$0.2/2-1e-7 }) { return false }
        for obstacle in package.geometry.obstacles {
            let polygon = obstacle.polygon
            if polygonContains(p,polygon) { return false }
            for i in polygon.indices where segmentDistance(p,polygon[i],polygon[(i+1)%polygon.count]) < clearance-1e-7 { return false }
        }
        return true
    }
    func clearSegment(_ a: MapPoint, _ b: MapPoint) -> Bool {
        let count = max(1,Int(ceil(a.distance(to:b)/0.05)))
        var previousRoom: MapRoom?
        for i in 0...count {
            let p = a+(b-a)*(Double(i)/Double(count))
            guard walkable(p), let room = room(at:p) else { return false }
            if let previousRoom, previousRoom.id != room.id {
                guard package.navigation.doors.contains(where:{ door in door.traversability == "confirmed" && door.roomIds.contains(room.id) && door.roomIds.contains(previousRoom.id) && segmentDistance(p,door.start,door.end) <= (package.geometry.walls.first { $0.id == door.wallId }?.thickness ?? 0)/2+0.25 }) else { return false }
            }
            previousRoom = room
        }
        return true
    }
    private func point(_ cell: GridCell) -> MapPoint { .init(x: Double(cell.x)*0.1,z: Double(cell.z)*0.1) }
    private func cellOK(_ cell: GridCell) -> Bool {
        if let result = cache[cell] { return result }
        let result = cell.x >= minX && cell.x <= maxX && cell.z >= minZ && cell.z <= maxZ && walkable(point(cell))
        cache[cell] = result
        return result
    }
    private func nearestCell(_ p: MapPoint) -> GridCell? {
        let x = Int((p.x/0.1).rounded()), z = Int((p.z/0.1).rounded())
        let cells = (-2...2).flatMap { dx in (-2...2).map { GridCell(x:x+dx,z:z+$0) } }.sorted {
            let a = p.distance(to:point($0)), b = p.distance(to:point($1))
            return a == b ? $0 < $1 : a < b
        }
        return cells.first { cellOK($0) && clearSegment(p,point($0)) }
    }
    func route(from start: MapPoint, to destinationId: String) throws -> PlannedRoute {
        guard let target = package.landmarks.landmarks.first(where: { $0.id == destinationId }) else { throw TouchSpaceError.invalid("Unknown destination.") }
        guard let source = nearestCell(start), let goal = nearestCell(target.position) else { throw TouchSpaceError.invalid("Start or destination lacks scanned clearance.") }
        var queue = MinHeap(), scores = [source:0.0], parents: [GridCell:GridCell] = [:], closed: Set<GridCell> = []
        queue.push(.init(score:point(source).distance(to:point(goal)),cell:source))
        while let item = queue.pop() {
            var cell = item.cell
            if closed.contains(cell) { continue }
            if cell == goal {
                var cells = [cell]
                while let parent = parents[cell] { cell = parent; cells.append(cell) }
                let points = [start]+cells.reversed().map(point)+[target.position]
                var simplified = [points[0]]
                for i in 1..<(points.count-1) {
                    let a = simplified.last!, b = points[i], c = points[i+1]
                    let cross = abs((b.x-a.x)*(c.z-b.z)-(b.z-a.z)*(c.x-b.x))
                    let door = package.navigation.doors.contains { segmentDistance(b,$0.start,$0.end) < 0.2 }
                    if door || cross > 1e-7 || !clearSegment(a,c), simplified.last!.distance(to:b) > 1e-7 { simplified.append(b) }
                }
                if simplified.last!.distance(to:points.last!) > 1e-7 { simplified.append(points.last!) }
                return .init(destinationId:destinationId,waypoints:simplified)
            }
            closed.insert(cell)
            if closed.count > 150_000 { break }
            for dx in -1...1 {
                for dz in -1...1 where dx != 0 || dz != 0 {
                    let next = GridCell(x:cell.x+dx,z:cell.z+dz)
                    let cost = scores[cell]!+hypot(Double(dx),Double(dz))*0.1
                    if cost+1e-8 >= scores[next,default:.infinity] { continue }
                    if !cellOK(next) { continue }
                    if dx != 0 && dz != 0 && (!cellOK(.init(x:cell.x+dx,z:cell.z)) || !cellOK(.init(x:cell.x,z:cell.z+dz))) { continue }
                    if !clearSegment(point(cell),point(next)) { continue }
                    if cost+1e-8 < scores[next,default:.infinity] {
                        scores[next] = cost; parents[next] = cell
                        queue.push(.init(score:cost+point(next).distance(to:point(goal)),cell:next))
                    }
                }
            }
        }
        throw TouchSpaceError.invalid("No validated route through this scanned zone.")
    }
    func relativeBearing(from origin: MapPoint, heading: Double, to p: MapPoint) -> Double {
        normalizedAngle(atan2(p.x-origin.x,-(p.z-origin.z))-heading)
    }
}
