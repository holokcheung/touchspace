import ARKit
import CryptoKit
import Foundation
import ZIPFoundation

/// The only import/export path: geometry and secure AR archive travel together.
enum PackageCodec {
    static let maximum = 64*1024*1024
    static let payloads: Set<String> = ["geometry.json","landmarks.json","navigation.json","worldmap.archive"]
    static let files = payloads.union(["manifest.json"])
    static func digest(_ data: Data) -> String { SHA256.hash(data:data).map { String(format:"%02x",$0) }.joined() }
    static func load(_ url: URL) throws -> MapPackage {
        let entries = try readEntries(url)
        let decoder = JSONDecoder()
        let manifest = try decoder.decode(MapManifest.self,from:entries["manifest.json"]!)
        guard Set(manifest.checksums.keys) == payloads, manifest.schemaVersion == "1.0" else { throw TouchSpaceError.invalid("Unsupported map manifest.") }
        for name in payloads where digest(entries[name]!) != manifest.checksums[name] { throw TouchSpaceError.invalid("Package checksum mismatch: \(name).") }
        let package = MapPackage(manifest:manifest,
                                 geometry:try decoder.decode(MapGeometry.self,from:entries["geometry.json"]!),
                                 landmarks:try decoder.decode(MapLandmarks.self,from:entries["landmarks.json"]!),
                                 navigation:try decoder.decode(MapNavigation.self,from:entries["navigation.json"]!))
        try validate(package)
        if manifest.isSynthetic { try validateSyntheticWorldMap(entries["worldmap.archive"]!,manifest:manifest) }
        else { _ = try decodeWorldMap(entries["worldmap.archive"]!,manifest:manifest) }
        return package
    }
    static func readEntries(_ url: URL) throws -> [String:Data] {
        let size = try url.resourceValues(forKeys:[.fileSizeKey]).fileSize ?? maximum+1
        guard size <= maximum else { throw TouchSpaceError.invalid("Map package exceeds 64 MB.") }
        let archive = try Archive(url:url,accessMode:.read)
        var results: [String:Data] = [:], total = 0
        for entry in archive {
            guard files.contains(entry.path), results[entry.path] == nil, entry.type == .file,
                  entry.uncompressedSize <= maximum else { throw TouchSpaceError.invalid("Invalid ZIP entries or paths.") }
            if entry.path.hasSuffix(".json") && entry.uncompressedSize > 4*1024*1024 { throw TouchSpaceError.invalid("Map JSON exceeds 4 MB.") }
            var data = Data()
            let checksum = try archive.extract(entry) { chunk in
                total += chunk.count
                guard total <= maximum else { throw TouchSpaceError.invalid("Expanded package exceeds 64 MB.") }
                data.append(chunk)
            }
            guard checksum == entry.checksum else { throw TouchSpaceError.invalid("Corrupt ZIP entry.") }
            if entry.path.hasSuffix(".json") { try JSONGuard.validate(data) }
            results[entry.path] = data
        }
        guard Set(results.keys) == files else { throw TouchSpaceError.invalid("A map requires geometry, labels, navigation and AR world data together.") }
        return results
    }
    static func worldMap(_ url: URL, manifest: MapManifest) throws -> ARWorldMap {
        guard !manifest.isSynthetic else { throw TouchSpaceError.invalid("Synthetic fixtures support map-only testing and contain no physical AR world data.") }
        return try decodeWorldMap(readEntries(url)["worldmap.archive"]!,manifest:manifest)
    }
    static func validateSyntheticWorldMap(_ data:Data, manifest:MapManifest) throws {
        let expected: [String:Any] = ["format":"touchspace.synthetic-worldmap", "version":1,
            "coordinateFrameId":manifest.coordinateFrameId.uuidString.lowercased(),
            "frameAnchorId":manifest.frameAnchorId.uuidString.lowercased(), "relocalizable":false]
        guard let value = try PropertyListSerialization.propertyList(from:data,format:nil) as? NSDictionary,
              value.isEqual(to:expected) else { throw TouchSpaceError.invalid("Invalid synthetic world-map placeholder.") }
    }
    static func decodeWorldMap(_ data: Data, manifest: MapManifest) throws -> ARWorldMap {
        guard !manifest.isSynthetic else { throw TouchSpaceError.invalid("Synthetic fixtures cannot restore a physical AR session.") }
        guard let archive = try PropertyListSerialization.propertyList(from:data,format:nil) as? [String:Any],
              archive["$archiver"] as? String == "NSKeyedArchiver" else { throw TouchSpaceError.invalid("Expected a secure AR world-map archive.") }
        guard let map = try NSKeyedUnarchiver.unarchivedObject(ofClass:ARWorldMap.self,from:data),
              map.anchors.contains(where: { $0.identifier == manifest.frameAnchorId && $0.name?.lowercased() == "touchspace-frame:\(manifest.coordinateFrameId.uuidString.lowercased())" }) else {
            throw TouchSpaceError.invalid("Secure AR world map lacks the expected coordinate-frame anchor.")
        }
        return map
    }
    static func write(_ package: MapPackage, worldMap: ARWorldMap, to url: URL) throws -> MapPackage {
        try validate(package)
        guard !package.manifest.isSynthetic else { throw TouchSpaceError.invalid("A RoomPlan capture cannot be saved as a synthetic fixture.") }
        let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]
        var data = ["geometry.json":try encoder.encode(package.geometry),
                    "landmarks.json":try encoder.encode(package.landmarks),
                    "navigation.json":try encoder.encode(package.navigation),
                    "worldmap.archive":try NSKeyedArchiver.archivedData(withRootObject:worldMap,requiringSecureCoding:true)]
        _ = try decodeWorldMap(data["worldmap.archive"]!,manifest:package.manifest)
        var saved = package
        saved.manifest.checksums = data.mapValues(digest)
        data["manifest.json"] = try encoder.encode(saved.manifest)
        guard data.values.reduce(0, { $0+$1.count }) <= maximum else { throw TouchSpaceError.invalid("Package exceeds 64 MB.") }
        let staging = url.deletingLastPathComponent().appendingPathComponent(UUID().uuidString+".zip")
        defer { try? FileManager.default.removeItem(at:staging) }
        do {
            let archive = try Archive(url:staging,accessMode:.create)
            for name in data.keys.sorted() {
                let bytes = data[name]!
                try archive.addEntry(with:name,type:.file,uncompressedSize:Int64(bytes.count),compressionMethod:.deflate) { offset,count in
                    bytes.subdata(in:Int(offset)..<(Int(offset)+count))
                }
            }
        }
        if FileManager.default.fileExists(atPath:url.path) { _ = try FileManager.default.replaceItemAt(url,withItemAt:staging) }
        else { try FileManager.default.moveItem(at:staging,to:url) }
        return saved
    }
    static func validate(_ package: MapPackage) throws {
        let g = package.geometry, n = package.navigation, m = package.manifest
        func require(_ condition: Bool, _ message: String) throws { if !condition { throw TouchSpaceError.invalid(message) } }
        func point(_ p: MapPoint) -> Bool { p.x.isFinite && p.z.isFinite && abs(p.x) <= 1000 && abs(p.z) <= 1000 }
        func polygon(_ p: [MapPoint]) -> Bool {
            guard p.count >= 3, p.count <= 2000, p.allSatisfy(point) else { return false }
            let area = abs(p.indices.reduce(0.0) { $0+p[$1].x*p[($1+1)%p.count].z-p[($1+1)%p.count].x*p[$1].z })/2
            guard area > 1e-6 && area <= 10000 else { return false }
            // Reject self-intersections, including collinear overlaps.
            func cross(_ a: MapPoint,_ b: MapPoint,_ c: MapPoint) -> Double { (b.x-a.x)*(c.z-a.z)-(b.z-a.z)*(c.x-a.x) }
            for i in p.indices {
                let a=p[i], b=p[(i+1)%p.count]
                if a.distance(to:b) < 1e-6 { return false }
                for j in p.indices where j > i+1 && !(i == 0 && j == p.count-1) {
                    let c=p[j], d=p[(j+1)%p.count]
                    let c1=cross(a,b,c),c2=cross(a,b,d),c3=cross(c,d,a),c4=cross(c,d,b)
                    if c1*c2 < 0 && c3*c4 < 0 { return false }
                    if segmentDistance(c,a,b) < 1e-7 || segmentDistance(d,a,b) < 1e-7 || segmentDistance(a,c,d) < 1e-7 || segmentDistance(b,c,d) < 1e-7 { return false }
                }
            }
            return true
        }
        try require(m.schemaVersion == "1.0" && ["roomplan-same-session","synthetic-fixture"].contains(m.provenance) && !m.venue.isEmpty && !m.floor.isEmpty && !m.contributor.isEmpty,"Invalid manifest.")
        try require(!m.isSynthetic || m.verification == "unverified","Synthetic fixtures must remain unverified.")
        try require(["partial","contiguous-zone"].contains(m.coverage) && ["unverified","volunteer-reviewed"].contains(m.verification),"Unknown coverage or verification.")
        try require(ISO8601DateFormatter().date(from:m.createdAt) != nil,"Invalid capture date.")
        try require(!g.rooms.isEmpty && g.rooms.count <= 100 && g.walls.count <= 4000 && g.obstacles.count <= 2000 && package.landmarks.landmarks.count <= 1000 && n.doors.count <= 1000 && n.nodes.count <= 5000 && n.edges.count <= 10000,"Map exceeds supported limits.")
        let groups = [g.rooms.map(\.id),g.walls.map(\.id),g.obstacles.map(\.id),package.landmarks.landmarks.map(\.id),n.doors.map(\.id),n.nodes.map(\.id)]
        try require(groups.allSatisfy { Set($0).count == $0.count && $0.allSatisfy { !$0.isEmpty && $0.count <= 100 } },"Invalid or duplicate stable IDs.")
        try require(g.floorY.isFinite && abs(g.floorY) <= 100 && [g.mapToWorld.x,g.mapToWorld.z,g.mapToWorld.y,g.mapToWorld.yaw].allSatisfy(\.isFinite),"Invalid coordinate transform.")
        try require(g.rooms.allSatisfy { polygon($0.polygon) && !$0.name.isEmpty && $0.name.count <= 120 } && g.obstacles.allSatisfy { polygon($0.polygon) },"Invalid scanned polygons.")
        try require(g.walls.allSatisfy { point($0.start) && point($0.end) && $0.start.distance(to:$0.end) > 1e-6 && (0.02...2).contains($0.thickness) },"Invalid walls.")
        for l in package.landmarks.landmarks {
            try require(!l.name.isEmpty && l.name.count <= 120 && point(l.position) && g.rooms.contains { $0.id == l.roomId && polygonContains(l.position,$0.polygon) },"Destination lies outside its scanned room.")
        }
        for node in n.nodes { try require(point(node.position) && g.rooms.contains { $0.id == node.roomId && polygonContains(node.position,$0.polygon) },"Invalid graph node.") }
        for d in n.doors {
            try require(["unknown","confirmed","blocked"].contains(d.traversability) && (1...2).contains(d.roomIds.count) && d.roomIds.allSatisfy { id in g.rooms.contains { $0.id == id } },"Invalid door links.")
            try require(point(d.start) && point(d.end) && d.start.distance(to:d.end) > 0.1 && g.walls.contains { $0.id == d.wallId && segmentDistance(d.start,$0.start,$0.end) <= 0.15 && segmentDistance(d.end,$0.start,$0.end) <= 0.15 },"Door must lie on its wall.")
        }
        for e in n.edges { try require(n.nodes.contains { $0.id == e.source } && n.nodes.contains { $0.id == e.target } && e.clearance.isFinite,"Invalid graph edge.") }
        _ = try SpatialEngine(package)
    }
}

@MainActor final class MapLibrary: ObservableObject {
    @Published var maps: [MapPackage] = []
    let directory: URL
    init() {
        directory = FileManager.default.urls(for:.documentDirectory,in:.userDomainMask)[0].appendingPathComponent("Maps",isDirectory:true)
        try? FileManager.default.createDirectory(at:directory,withIntermediateDirectories:true)
        refresh()
    }
    func url(for id: UUID) -> URL { directory.appendingPathComponent(id.uuidString.lowercased()+".touchspacemap") }
    func refresh() {
        maps = ((try? FileManager.default.contentsOfDirectory(at:directory,includingPropertiesForKeys:nil)) ?? [])
            .filter { $0.pathExtension == "touchspacemap" }.compactMap { try? PackageCodec.load($0) }.sorted { $0.manifest.createdAt > $1.manifest.createdAt }
    }
    @discardableResult func importMap(_ source: URL) throws -> MapPackage {
        let access = source.startAccessingSecurityScopedResource()
        defer { if access { source.stopAccessingSecurityScopedResource() } }
        let package = try PackageCodec.load(source)
        let destination = url(for:package.id)
        if source.standardizedFileURL != destination.standardizedFileURL {
            let staging = directory.appendingPathComponent(UUID().uuidString+".tmp")
            defer { try? FileManager.default.removeItem(at:staging) }
            try FileManager.default.copyItem(at:source,to:staging)
            if FileManager.default.fileExists(atPath:destination.path) { _ = try FileManager.default.replaceItemAt(destination,withItemAt:staging) }
            else { try FileManager.default.moveItem(at:staging,to:destination) }
        }
        refresh(); return package
    }
}
