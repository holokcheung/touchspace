import Foundation

/// Conservative occupancy grid over one coherent surveyed room; unknown space is never filled in.
public enum GraphBuilder {
    public static func build(manifest: Manifest, geometry: Geometry, doors: [Door], spacing: Double = 0.5) throws -> Navigation {
        guard geometry.rooms.count==1, (0.3...1).contains(spacing) else { throw MapError("v1 scanner supports one coherent room per session.") }
        let room=geometry.rooms[0], xs=room.polygon.map(\.x), zs=room.polygon.map(\.z)
        guard let minX=xs.min(), let maxX=xs.max(), let minZ=zs.min(), let maxZ=zs.max(), (maxX-minX)/spacing<200, (maxZ-minZ)/spacing<200 else { throw MapError("Scanned room is too large for the v1 grid.") }
        var nav=Navigation(coordinateFrameId:manifest.coordinateFrameId,nodes:[],edges:[],doors:doors)
        let shell=MapPackage(manifest:manifest,geometry:geometry,landmarks:Landmarks(coordinateFrameId:manifest.coordinateFrameId,landmarks:[]),navigation:nav,worldData:nil)
        let engine=SpatialEngine(package:shell)
        var grid=[String:Node]()
        let width=Int(ceil((maxX-minX)/spacing)), height=Int(ceil((maxZ-minZ)/spacing))
        for i in 0..<width {
            for j in 0..<height {
                let p=Point(x:minX+(Double(i)+0.5)*spacing,z:minZ+(Double(j)+0.5)*spacing)
                guard engine.segmentValid(p,p) else { continue }
                let n=Node(id:"grid-\(i)-\(j)",position:p,roomId:room.id)
                grid["\(i),\(j)"]=n; nav.nodes.append(n)
            }
        }
        for i in 0..<width {
            for j in 0..<height {
                guard let a=grid["\(i),\(j)"] else { continue }
                // Four-neighbor connectivity avoids cutting diagonal obstacle corners.
                for (dx,dz) in [(1,0),(0,1)] {
                    if let b=grid["\(i+dx),\(j+dz)"],engine.segmentValid(a.position,b.position) { nav.edges.append(Edge(a:a.id,b:b.id)) }
                }
            }
        }
        guard !nav.nodes.isEmpty else { throw MapError("No traversable area remains after applying obstacle clearance. Rescan a larger clear area.") }
        return nav
    }
}
