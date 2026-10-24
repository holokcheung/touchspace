import Foundation
import CZip

/// Flat bounded ZIP reader/writer (stored and raw DEFLATE); never extracts to a file path.
/// ZIP64, encryption, symlinks, duplicate names, trailing bytes, and unexpected entries are rejected.
public enum MapArchive {
    public static let maxBytes = 64 * 1024 * 1024
    static let jsonNames: Set<String> = ["manifest.json", "geometry.json", "landmarks.json", "navigation.json"]
    static let allowedNames = jsonNames.union(["worldmap.archive"])
    public static func read(_ data: Data) throws -> [String: Data] {
        guard data.count >= 22, data.count <= maxBytes else { throw MapError("Package must be nonempty and at most 64 MiB.") }
        let bytes=[UInt8](data)
        func u16(_ i: Int) throws -> Int {
            guard i>=0, i+2<=bytes.count else { throw MapError("Truncated ZIP.") }
            return Int(bytes[i]) | Int(bytes[i+1])<<8
        }
        func u32(_ i: Int) throws -> Int { try u16(i) | (u16(i+2)<<16) }
        var eocd: Int?
        for i in stride(from: bytes.count-22, through: max(0, bytes.count-65557), by: -1) {
            if try u32(i)==0x06054b50, i+22+(try u16(i+20))==bytes.count { eocd=i; break }
        }
        guard let end=eocd else { throw MapError("Missing ZIP directory.") }
        let count=try u16(end+10), directorySize=try u32(end+12), directoryStart=try u32(end+16)
        guard try u16(end+4)==0, try u16(end+6)==0, try u16(end+8)==count, (4...5).contains(count), directoryStart+directorySize==end else { throw MapError("Unsupported ZIP layout.") }
        var cursor=directoryStart, total=0, result: [String:Data]=[:], ranges: [Range<Int>]=[]
        for _ in 0..<count {
            guard try u32(cursor)==0x02014b50 else { throw MapError("Invalid ZIP directory entry.") }
            let flags=try u16(cursor+8), method=try u16(cursor+10), crc=try u32(cursor+16)
            let compressed=try u32(cursor+20), expanded=try u32(cursor+24)
            let nameLen=try u16(cursor+28), extraLen=try u16(cursor+30), commentLen=try u16(cursor+32)
            let attrs=try u32(cursor+38), offset=try u32(cursor+42)
            guard cursor+46+nameLen+extraLen+commentLen<=end else { throw MapError("Truncated ZIP entry.") }
            let name=String(bytes: bytes[(cursor+46)..<(cursor+46+nameLen)], encoding: .utf8) ?? ""
            total += expanded
            guard allowedNames.contains(name), result[name]==nil, flags & 1 == 0, [0,8].contains(method), (attrs>>16)&0xf000 != 0xa000, try u16(cursor+34)==0, total<=maxBytes, expanded>0 else { throw MapError("Unsafe, duplicate, oversized, or unsupported archive entry.") }
            guard !jsonNames.contains(name) || expanded<=8*1024*1024 else { throw MapError("JSON document exceeds 8 MiB.") }
            guard offset>=0, offset+30<=directoryStart, try u32(offset)==0x04034b50, try u16(offset+6)==flags, try u16(offset+8)==method else { throw MapError("Invalid ZIP local entry.") }
            let localNameLen=try u16(offset+26), localExtraLen=try u16(offset+28)
            let start=offset+30+localNameLen+localExtraLen, stop=start+compressed
            guard start<=directoryStart, stop<=directoryStart, localNameLen==nameLen,
                  String(bytes: bytes[(offset+30)..<(offset+30+localNameLen)], encoding:.utf8)==name,
                  !ranges.contains(where: { $0.overlaps(offset..<stop) }) else { throw MapError("Overlapping or mismatched ZIP entries.") }
            ranges.append(offset..<stop)
            let source=Data(bytes[start..<stop])
            var decoded: Data
            if method==0 {
                guard compressed==expanded else { throw MapError("Invalid stored entry size.") }
                decoded=source
            } else {
                decoded=Data(count: expanded)
                let valid=decoded.withUnsafeMutableBytes { dst in source.withUnsafeBytes { src in
                    ts_inflate(src.bindMemory(to:UInt8.self).baseAddress, source.count, dst.bindMemory(to:UInt8.self).baseAddress, expanded)
                }}
                guard valid==1 else { throw MapError("Invalid compressed ZIP data.") }
            }
            guard checksum(decoded)==UInt32(crc) else { throw MapError("Package checksum failed.") }
            result[name]=decoded
            cursor += 46+nameLen+extraLen+commentLen
        }
        guard cursor==end, jsonNames.isSubset(of:Set(result.keys)) else { throw MapError("Missing canonical package files.") }
        return result
    }
    public static func write(_ files: [String:Data]) throws -> Data {
        guard jsonNames.isSubset(of:Set(files.keys)), Set(files.keys).isSubset(of:allowedNames), files.values.reduce(0,{$0+$1.count})<=maxBytes-2048, files.allSatisfy({!$0.value.isEmpty && (!jsonNames.contains($0.key) || $0.value.count<=8*1024*1024)}) else { throw MapError("Invalid package files or size.") }
        var body=Data(), directory=Data()
        for name in files.keys.sorted() {
            let value=files[name]!, filename=Data(name.utf8), crc=checksum(value), offset=body.count
            body.le32(0x04034b50); body.le16(20); body.le16(0); body.le16(0); body.le16(0); body.le16(0)
            body.le32(crc); body.le32(UInt32(value.count)); body.le32(UInt32(value.count)); body.le16(filename.count); body.le16(0); body.append(filename); body.append(value)
            directory.le32(0x02014b50); directory.le16(20); directory.le16(20); directory.le16(0); directory.le16(0); directory.le16(0); directory.le16(0)
            directory.le32(crc); directory.le32(UInt32(value.count)); directory.le32(UInt32(value.count)); directory.le16(filename.count); directory.le16(0); directory.le16(0); directory.le16(0); directory.le16(0); directory.le32(0); directory.le32(UInt32(offset)); directory.append(filename)
        }
        let offset=body.count; body.append(directory)
        body.le32(0x06054b50); body.le16(0); body.le16(0); body.le16(files.count); body.le16(files.count); body.le32(UInt32(directory.count)); body.le32(UInt32(offset)); body.le16(0)
        return body
    }
    static func checksum(_ data: Data) -> UInt32 { data.withUnsafeBytes { ts_crc($0.bindMemory(to:UInt8.self).baseAddress, data.count) } }
}
private extension Data {
    mutating func le16(_ n: Int) { append(UInt8(n&255)); append(UInt8((n>>8)&255)) }
    mutating func le32(_ n: UInt32) { for i in 0..<4 { append(UInt8((n>>UInt32(i*8))&255)) } }
}

public struct MapPackage: Sendable {
    public var manifest: Manifest
    public var geometry: Geometry
    public var landmarks: Landmarks
    public var navigation: Navigation
    public var worldData: Data?
    public init(manifest: Manifest, geometry: Geometry, landmarks: Landmarks, navigation: Navigation, worldData: Data?) {
        self.manifest=manifest; self.geometry=geometry; self.landmarks=landmarks; self.navigation=navigation; self.worldData=worldData
    }
    public init(data: Data) throws {
        let files=try MapArchive.read(data), decoder=JSONDecoder()
        manifest=try decoder.decode(Manifest.self, from:files["manifest.json"]!)
        geometry=try decoder.decode(Geometry.self, from:files["geometry.json"]!)
        landmarks=try decoder.decode(Landmarks.self, from:files["landmarks.json"]!)
        navigation=try decoder.decode(Navigation.self, from:files["navigation.json"]!)
        worldData=files["worldmap.archive"]
        try validate()
    }
    public func encoded() throws -> Data {
        try validate()
        let encoder=JSONEncoder(); encoder.outputFormatting=[.sortedKeys]
        var files=["manifest.json":try encoder.encode(manifest), "geometry.json":try encoder.encode(geometry), "landmarks.json":try encoder.encode(landmarks), "navigation.json":try encoder.encode(navigation)]
        if let worldData { files["worldmap.archive"]=worldData }
        return try MapArchive.write(files)
    }
    public func validate() throws {
        guard manifest.schemaVersion==1, manifest.units=="meters", geometry.transform==Geometry.identity,
              geometry.coordinateFrameId==manifest.coordinateFrameId, landmarks.coordinateFrameId==manifest.coordinateFrameId, navigation.coordinateFrameId==manifest.coordinateFrameId,
              manifest.worldMapIncluded == (worldData?.isEmpty == false), !(manifest.synthetic && manifest.worldMapIncluded),
              validID(manifest.mapId), [manifest.title,manifest.floor,manifest.coverage,manifest.contributor].allSatisfy(validLabel),
              ["unverified","volunteer-reviewed"].contains(manifest.verification) else { throw MapError("Unsupported schema, coordinate frame, metadata, or world map declaration.") }
        func date(_ s:String)->Date? { let f=ISO8601DateFormatter(); f.formatOptions=[.withInternetDateTime,.withFractionalSeconds]; return f.date(from:s) ?? ISO8601DateFormatter().date(from:s) }
        guard let created=date(manifest.createdAt), let updated=date(manifest.updatedAt), updated>=created else { throw MapError("Invalid map timestamps.") }
        try SpatialEngine(package:self).validate()
    }
    public var warnings: [String] {
        var result=[String]()
        if !manifest.worldMapIncluded { result.append("Map-only draft. No saved AR world data; live positioning is unavailable.") }
        if SpatialEngine(package:self).componentCount > 1 { result.append("Disconnected areas: some destinations cannot be reached.") }
        return result
    }
}
func validID(_ s: String) -> Bool { s.range(of: "^[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}$", options:.regularExpression) == s.startIndex..<s.endIndex }
func validLabel(_ s:String)->Bool { !s.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty && s.unicodeScalars.count<=200 }
