import Foundation
import RoomPlan

/// A finished scan saved on the device: Apple's own CapturedRoom JSON plus an optional USDZ model.
struct SavedScan: Identifiable, Codable, Hashable {
    let id: UUID
    var name: String
    let createdAt: Date
    let folderName: String
    let walls: Int
    let doors: Int
    let windows: Int
    let openings: Int
    let objects: Int
    let hasModel: Bool

    var summary: String {
        "\(walls) walls, \(doors) doors, \(openings) openings, \(windows) windows, \(objects) objects"
    }
}

@MainActor
final class ScanStore: ObservableObject {
    @Published private(set) var scans: [SavedScan] = []

    private let root: URL
    private let fm = FileManager.default

    init() {
        root = fm.urls(for: .documentDirectory, in: .userDomainMask)[0].appendingPathComponent("Scans", isDirectory: true)
        try? fm.createDirectory(at: root, withIntermediateDirectories: true)
        reload()
    }

    func folder(for scan: SavedScan) -> URL { root.appendingPathComponent(scan.folderName, isDirectory: true) }
    func jsonURL(for scan: SavedScan) -> URL { folder(for: scan).appendingPathComponent("\(fileStem(scan)).json") }
    func usdzURL(for scan: SavedScan) -> URL? {
        scan.hasModel ? folder(for: scan).appendingPathComponent("\(fileStem(scan)).usdz") : nil
    }

    /// Saves the CapturedRoom exactly as RoomPlan encodes it (no custom schema), plus a USDZ model.
    func save(_ room: CapturedRoom, name: String) throws -> SavedScan {
        let id = UUID()
        let folderName = "\(Int(Date().timeIntervalSince1970))-\(id.uuidString.prefix(8))"
        let folder = root.appendingPathComponent(folderName, isDirectory: true)
        try fm.createDirectory(at: folder, withIntermediateDirectories: true)

        var scan = SavedScan(
            id: id, name: name, createdAt: Date(), folderName: folderName,
            walls: room.walls.count, doors: room.doors.count, windows: room.windows.count,
            openings: room.openings.count, objects: room.objects.count, hasModel: false
        )

        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted]
        try encoder.encode(room).write(to: jsonURL(for: scan), options: .atomic)

        // The USDZ model is a nice-to-have for previewing; a failure here should not lose the scan.
        let usdz = folder.appendingPathComponent("\(fileStem(scan)).usdz")
        if (try? room.export(to: usdz, exportOptions: .parametric)) != nil {
            scan = SavedScan(
                id: scan.id, name: scan.name, createdAt: scan.createdAt, folderName: scan.folderName,
                walls: scan.walls, doors: scan.doors, windows: scan.windows, openings: scan.openings,
                objects: scan.objects, hasModel: true
            )
        }
        try writeMeta(scan)
        reload()
        return scan
    }

    func rename(_ scan: SavedScan, to name: String) {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        let oldJSON = jsonURL(for: scan)
        let oldUSDZ = usdzURL(for: scan)
        var renamed = scan
        renamed.name = trimmed
        try? fm.moveItem(at: oldJSON, to: jsonURL(for: renamed))
        if let oldUSDZ, let newUSDZ = usdzURL(for: renamed) { try? fm.moveItem(at: oldUSDZ, to: newUSDZ) }
        try? writeMeta(renamed)
        reload()
    }

    func delete(_ scan: SavedScan) {
        try? fm.removeItem(at: folder(for: scan))
        reload()
    }

    func reload() {
        let folders = (try? fm.contentsOfDirectory(at: root, includingPropertiesForKeys: nil)) ?? []
        let decoder = JSONDecoder()
        scans = folders
            .compactMap { try? decoder.decode(SavedScan.self, from: Data(contentsOf: $0.appendingPathComponent("meta.json"))) }
            .sorted { $0.createdAt > $1.createdAt }
    }

    private func writeMeta(_ scan: SavedScan) throws {
        try JSONEncoder().encode(scan).write(to: folder(for: scan).appendingPathComponent("meta.json"), options: .atomic)
    }

    /// File names people will see in the share sheet, e.g. "touchspace-kitchen".
    private func fileStem(_ scan: SavedScan) -> String {
        let slug = scan.name.lowercased()
            .components(separatedBy: CharacterSet.alphanumerics.inverted)
            .filter { !$0.isEmpty }
            .joined(separator: "-")
        return "touchspace-\(slug.isEmpty ? "room" : slug)"
    }
}
