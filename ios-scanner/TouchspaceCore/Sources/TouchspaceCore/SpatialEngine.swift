import Foundation

public struct RelativeDirection: Equatable, Sendable {
    public var distanceMeters: Double; public var angleRadians: Double; public var direction: String
    public var stereoPan: Float { Float(sin(angleRadians)) }
}
public struct SpatialEngine: Sendable {
    public let package: MapPackage
    public init(package: MapPackage) { self.package=package }
    public func room(at p: Point) -> Room? { package.geometry.rooms.first { Self.contains(p,in:$0.polygon) } }
    public func relative(from pose: Pose, to target: Point) -> RelativeDirection {
        let bearing=atan2(target.x-pose.position.x, -(target.z-pose.position.z))
        let angle=atan2(sin(bearing-pose.heading),cos(bearing-pose.heading))
        let direction=abs(angle)<=Double.pi/4 ? "ahead" : abs(angle)>=3*Double.pi/4 ? "behind" : angle>0 ? "right" : "left"
        return RelativeDirection(distanceMeters:pose.position.distance(to:target), angleRadians:angle, direction:direction)
    }
    public func segmentValid(_ a: Point, _ b: Point) -> Bool {
        let g=package.geometry, clearance=package.navigation.clearance
        guard room(at:a) != nil, room(at:b) != nil else { return false }
        // Partition at every surveyed polygon boundary; test all intervals, including narrow gaps.
        var cuts=[0.0,1.0]
        for r in g.rooms {
            for (c,d) in Self.sides(r.polygon) { if let t=Self.intersectionParameter(a,b,c,d) { cuts.append(t) } }
        }
        cuts.sort()
        for (lo,hi) in zip(cuts,cuts.dropFirst()) {
            let t=(lo+hi)/2, p=Point(x:a.x+(b.x-a.x)*t,z:a.z+(b.z-a.z)*t)
            if room(at:p)==nil { return false }
        }
        for w in g.walls { if Self.segmentDistance(a,b,w.a,w.b)<=clearance { return false } }
        for o in g.obstacles {
            if Self.contains(a,in:o.polygon) || Self.contains(b,in:o.polygon) { return false }
            if Self.sides(o.polygon).contains(where:{Self.segmentDistance(a,b,$0.0,$0.1)<=clearance}) { return false }
        }
        return true
    }
    public func nearestNode(to p: Point) throws -> Node {
        guard let node=package.navigation.nodes.sorted(by: {
            let a=$0.position.distance(to:p), b=$1.position.distance(to:p)
            return a==b ? $0.id<$1.id : a<b
        }).first(where:{$0.roomId==room(at:p)?.id && $0.position.distance(to:p)<=1.5 && segmentValid(p,$0.position)}) else { throw MapError("No safe connection to the route graph at this position.") }
        return node
    }
    private var adjacency: [String:[(String,Double)]] {
        let nodes=Dictionary(package.navigation.nodes.map{($0.id,$0)}, uniquingKeysWith: {a,_ in a})
        let doors=Dictionary(package.navigation.doors.map{($0.id,$0)}, uniquingKeysWith: {a,_ in a})
        var result=[String:[(String,Double)]]()
        for e in package.navigation.edges {
            guard let a=nodes[e.a], let b=nodes[e.b], e.doorId==nil || doors[e.doorId!]?.traversable==true else { continue }
            let cost=a.position.distance(to:b.position)
            result[a.id,default:[]].append((b.id,cost)); result[b.id,default:[]].append((a.id,cost))
        }
        return result
    }
    public func route(from start: String, to end: String) throws -> Route {
        let nodes=Dictionary(package.navigation.nodes.map{($0.id,$0)},uniquingKeysWith:{a,_ in a}), graph=adjacency
        guard let source=nodes[start], let goal=nodes[end] else { throw MapError("Unknown route node.") }
        var costs=[start:0.0], previous=[String:String](), queue=MinHeap()
        queue.push(HeapItem(priority:source.position.distance(to:goal.position), cost:0, id:start))
        while let item=queue.pop() {
            if item.cost>(costs[item.id] ?? .infinity)+1e-9 { continue }
            if item.id==end {
                var ids=[end]
                while ids.last != start { guard let prev=previous[ids.last!] else { throw MapError("Invalid route.") }; ids.append(prev) }
                ids.reverse()
                let protected=Set(package.navigation.edges.filter{$0.doorId != nil}.flatMap{[$0.a,$0.b]})
                var waypoints=[Point]()
                for (i,id) in ids.enumerated() {
                    let p=nodes[id]!.position
                    var keep=i==0 || i==ids.count-1 || protected.contains(id)
                    if !keep {
                        let a=nodes[ids[i-1]]!.position,b=nodes[ids[i+1]]!.position
                        let dx=p.x-a.x,dz=p.z-a.z,ex=b.x-p.x,ez=b.z-p.z
                        keep=abs(dx*ez-dz*ex)>1e-8 || dx*ex+dz*ez<0
                    }
                    if keep {waypoints.append(p)}
                }
                return Route(nodeIds:ids, waypoints:waypoints, distanceMeters:item.cost)
            }
            for (id,weight) in (graph[item.id] ?? []).sorted(by:{$0.0<$1.0}) {
                let next=item.cost+weight
                if next<(costs[id] ?? .infinity) {
                    costs[id]=next; previous[id]=item.id
                    queue.push(HeapItem(priority:next+nodes[id]!.position.distance(to:goal.position),cost:next,id:id))
                }
            }
        }
        throw MapError("This destination is unreachable in the scanned navigation graph.")
    }
    public func route(from pose: Pose, to landmark: Landmark) throws -> Route {
        guard pose.isUsable(for:package.manifest), room(at:pose.position) != nil else { throw MapError("Position is uncertain. Live guidance is paused.") }
        guard let end=landmark.nodeId else { throw MapError("This landmark has no surveyed route connection.") }
        let node=try nearestNode(to:pose.position)
        var result=try route(from:node.id,to:end)
        result.waypoints.insert(pose.position,at:0)
        result.distanceMeters += pose.position.distance(to:node.position)
        return result
    }
    public var componentCount: Int {
        var unseen=Set(package.navigation.nodes.map(\.id)), count=0
        let graph=adjacency
        while let node=unseen.first {
            count += 1; unseen.remove(node); var stack=[node]
            while let next=stack.popLast() { for (n,_) in graph[next] ?? [] { if unseen.remove(n) != nil { stack.append(n) } } }
        }
        return count
    }
    public func validate() throws {
        let g=package.geometry, n=package.navigation, l=package.landmarks.landmarks
        guard (1...100).contains(g.rooms.count), g.walls.count<=2000, g.obstacles.count<=2000, (1...20000).contains(n.nodes.count), n.edges.count<=80000, n.doors.count<=1000, l.count<=2000, n.clearance.isFinite, (0.25...2).contains(n.clearance) else { throw MapError("Geometry or graph exceeds supported bounds.") }
        func unique(_ ids:[String]) -> Bool { Set(ids).count==ids.count && ids.allSatisfy(validID) }
        guard unique(g.rooms.map(\.id)), unique(g.walls.map(\.id)), unique(g.obstacles.map(\.id)), unique(n.nodes.map(\.id)), unique(n.doors.map(\.id)), unique(l.map(\.id)) else { throw MapError("Duplicate or invalid stable IDs.") }
        func valid(_ p:Point)->Bool { p.x.isFinite && p.z.isFinite && abs(p.x)<=10000 && abs(p.z)<=10000 }
        guard g.rooms.allSatisfy({validLabel($0.name)}), n.doors.allSatisfy({validLabel($0.name)}), g.obstacles.allSatisfy({$0.polygon.count<=128}) else { throw MapError("Invalid room/door labels or obstacle bounds.") }
        for polygon in g.rooms.map(\.polygon)+g.obstacles.map(\.polygon) {
            guard (3...512).contains(polygon.count), polygon.allSatisfy(valid), Self.simplePolygon(polygon) else { throw MapError("Invalid or degenerate polygon.") }
        }
        guard g.walls.allSatisfy({valid($0.a) && valid($0.b)}) else { throw MapError("Invalid wall coordinates.") }
        let rooms=Dictionary(uniqueKeysWithValues:g.rooms.map{($0.id,$0)}), nodes=Dictionary(uniqueKeysWithValues:n.nodes.map{($0.id,$0)}), doors=Dictionary(uniqueKeysWithValues:n.doors.map{($0.id,$0)})
        for node in n.nodes {
            guard valid(node.position), let room=rooms[node.roomId], Self.contains(node.position,in:room.polygon), segmentValid(node.position,node.position) else { throw MapError("Node violates scanned-room bounds or obstacle clearance.") }
        }
        for door in n.doors {
            guard (1...2).contains(door.rooms.count), Set(door.rooms).count==door.rooms.count, door.rooms.allSatisfy({rooms[$0] != nil}), valid(door.position), door.width.isFinite, door.width>0, door.width<=20 else { throw MapError("Invalid doorway.") }
        }
        for lm in l {
            guard valid(lm.position), let room=rooms[lm.roomId], Self.contains(lm.position,in:room.polygon), validLabel(lm.name),
                  ["entrance","exit","information","restroom","object","stairs","elevator","other"].contains(lm.type), ["volunteer","scan"].contains(lm.provenance) else { throw MapError("Invalid landmark or room membership.") }
            if let id=lm.nodeId {
                guard let node=nodes[id], node.roomId==lm.roomId, lm.position.distance(to:node.position)<=1.5 else { throw MapError("Landmark route connection is invalid.") }
            }
        }
        var seen=Set<String>()
        for e in n.edges {
            let key=[e.a,e.b].sorted().joined(separator:"|")
            guard let a=nodes[e.a], let b=nodes[e.b], e.a != e.b, seen.insert(key).inserted, segmentValid(a.position,b.position) else { throw MapError("Invalid edge: wall, obstacle, duplicate, or unscanned area.") }
            if let did=e.doorId {
                guard let d=doors[did], d.width>=2*n.clearance,
                      a.position.distance(to:d.position)+b.position.distance(to:d.position)<=a.position.distance(to:b.position)+0.2 else { throw MapError("Invalid doorway transition.") }
            }
            if a.roomId != b.roomId {
                guard let did=e.doorId, let d=doors[did], Set(d.rooms)==Set([a.roomId,b.roomId]) else { throw MapError("Room transitions require a recorded doorway.") }
            }
        }
    }
    public static func contains(_ p: Point, in polygon: [Point]) -> Bool {
        guard polygon.count>=3 else { return false }
        var inside=false
        for (a,b) in sides(polygon) {
            if pointSegmentDistance(p,a,b)<1e-8 { return true }
            if (a.z>p.z) != (b.z>p.z), p.x<(b.x-a.x)*(p.z-a.z)/(b.z-a.z)+a.x { inside.toggle() }
        }
        return inside
    }
    static func sides(_ polygon:[Point])->[(Point,Point)] { zip(polygon,polygon.dropFirst()+polygon.prefix(1)).map{($0,$1)} }
    static func cross(_ ax:Double,_ az:Double,_ bx:Double,_ bz:Double)->Double { ax*bz-az*bx }
    static func intersectionParameter(_ a:Point,_ b:Point,_ c:Point,_ d:Point)->Double? {
        let rx=b.x-a.x, rz=b.z-a.z, sx=d.x-c.x, sz=d.z-c.z, det=cross(rx,rz,sx,sz)
        guard abs(det)>1e-10 else { return nil }
        let t=cross(c.x-a.x,c.z-a.z,sx,sz)/det, u=cross(c.x-a.x,c.z-a.z,rx,rz)/det
        return t >= -1e-9 && t<=1+1e-9 && u >= -1e-9 && u<=1+1e-9 ? min(1,max(0,t)) : nil
    }
    public static func pointSegmentDistance(_ p:Point,_ a:Point,_ b:Point)->Double {
        let dx=b.x-a.x,dz=b.z-a.z, denom=dx*dx+dz*dz
        let t=denom<1e-16 ? 0 : min(1,max(0,((p.x-a.x)*dx+(p.z-a.z)*dz)/denom))
        return p.distance(to:Point(x:a.x+t*dx,z:a.z+t*dz))
    }
    static func segmentDistance(_ a:Point,_ b:Point,_ c:Point,_ d:Point)->Double {
        if intersectionParameter(a,b,c,d) != nil { return 0 }
        return min(pointSegmentDistance(a,c,d), pointSegmentDistance(b,c,d), pointSegmentDistance(c,a,b), pointSegmentDistance(d,a,b))
    }
    static func simplePolygon(_ polygon:[Point])->Bool {
        let edges=sides(polygon)
        let area=abs(edges.reduce(0){$0+$1.0.x*$1.1.z-$1.1.x*$1.0.z})/2
        guard area>=0.01 else { return false }
        for i in edges.indices {
            if edges[i].0.distance(to:edges[i].1)<1e-8 { return false }
            for j in edges.indices where j>i+1 && !(i==0 && j==edges.count-1) {
                if segmentDistance(edges[i].0,edges[i].1,edges[j].0,edges[j].1)<1e-8 { return false }
            }
        }
        return true
    }
}
private struct HeapItem: Comparable {
    var priority: Double; var cost: Double; var id: String
    static func < (a: Self,b: Self)->Bool { a.priority==b.priority ? (a.cost==b.cost ? a.id<b.id : a.cost<b.cost) : a.priority<b.priority }
}
private struct MinHeap {
    var items=[HeapItem]()
    mutating func push(_ v:HeapItem) {
        items.append(v); var i=items.count-1
        while i>0 { let p=(i-1)/2; if !(items[i]<items[p]) { break }; items.swapAt(i,p); i=p }
    }
    mutating func pop()->HeapItem? {
        guard !items.isEmpty else { return nil }
        if items.count==1 { return items.removeLast() }
        let v=items[0]; items[0]=items.removeLast(); var i=0
        while 2*i+1<items.count { let a=2*i+1,b=a+1; let c=b<items.count && items[b]<items[a] ? b:a; if !(items[c]<items[i]) { break }; items.swapAt(c,i); i=c }
        return v
    }
}
