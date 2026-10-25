import Foundation

/// Ear clipping preserves concave scanned floor outlines rather than filling a bounding box.
enum PolygonMesh {
    static func triangles(_ polygon: [MapPoint]) throws -> [UInt32] {
        guard polygon.count >= 3 else { throw TouchSpaceError.invalid("A floor needs a polygon.") }
        func cross(_ a:MapPoint,_ b:MapPoint,_ c:MapPoint) -> Double { (b.x-a.x)*(c.z-a.z)-(b.z-a.z)*(c.x-a.x) }
        let signed = polygon.indices.reduce(0.0) { $0+polygon[$1].x*polygon[($1+1)%polygon.count].z-polygon[($1+1)%polygon.count].x*polygon[$1].z }
        var remaining = signed >= 0 ? Array(polygon.indices) : Array(polygon.indices.reversed())
        var result: [UInt32] = []
        while remaining.count > 3 {
            var clipped = false
            for index in remaining.indices {
                let a=remaining[(index+remaining.count-1)%remaining.count], b=remaining[index], c=remaining[(index+1)%remaining.count]
                guard cross(polygon[a],polygon[b],polygon[c]) > 1e-10 else { continue }
                let contains = remaining.contains { p in
                    p != a && p != b && p != c && cross(polygon[a],polygon[b],polygon[p]) >= -1e-10 && cross(polygon[b],polygon[c],polygon[p]) >= -1e-10 && cross(polygon[c],polygon[a],polygon[p]) >= -1e-10
                }
                if !contains {
                    result += [UInt32(a),UInt32(b),UInt32(c)]; remaining.remove(at:index); clipped = true; break
                }
            }
            guard clipped else { throw TouchSpaceError.invalid("The floor polygon cannot be triangulated.") }
        }
        result += remaining.map(UInt32.init)
        return result
    }
}
