import AVFoundation
import SwiftUI

struct ScannerView: View {
    @EnvironmentObject private var library: MapLibrary
    @Environment(\.dismiss) private var dismiss
    @StateObject private var scanner = RoomScanner()
    @State private var reviewing = false
    @State private var permitted = false
    var body: some View {
        NavigationStack {
            Group {
                if reviewing, let package = scanner.package {
                    ScanReviewView(scanner:scanner,initial:package,onBack:{ reviewing = false })
                } else {
                    VStack(spacing:16) {
                        if permitted { RoomCaptureCamera(scanner:scanner).accessibilityHidden(true) }
                        Text(scanner.instruction).padding(.horizontal).accessibilityAddTraits(.updatesFrequently)
                        if scanner.processing { ProgressView("Processing scanned geometry") }
                        HStack {
                            Button(scanner.scanning ? "Finish room" : (scanner.roomCount == 0 ? "Start scan" : "Add room"),systemImage:scanner.scanning ? "stop.circle" : "camera") {
                                if scanner.scanning { scanner.finishRoom() } else { scanner.startRoom() }
                            }.disabled(!permitted || scanner.processing)
                            if scanner.package != nil { Button("Review",systemImage:"checklist") { reviewing = true }.disabled(scanner.scanning || scanner.processing) }
                        }.buttonStyle(.borderedProminent).controlSize(.large).padding()
                    }
                }
            }
            .navigationTitle(reviewing ? "Review scan" : "Scan space")
            .toolbar { ToolbarItem(placement:.cancellationAction) { Button("Close") { scanner.stop(); dismiss() } } }
            .alert("Scan status",isPresented:Binding(get:{ scanner.error != nil },set:{ if !$0 { scanner.error = nil } })) { Button("OK") { scanner.error = nil } } message: { Text(scanner.error ?? "") }
        }
        .task { permitted = await AVCaptureDevice.requestAccess(for:.video); if !permitted { scanner.error = "Camera permission is required for RoomPlan capture." } }
        .onDisappear { scanner.stop() }
    }
}

struct ScanReviewView: View {
    @ObservedObject var scanner: RoomScanner
    let initial: MapPackage
    var onBack: () -> Void
    @EnvironmentObject private var library: MapLibrary
    @Environment(\.dismiss) private var dismiss
    @State private var package: MapPackage
    @State private var label = ""
    @State private var roomId = ""
    @State private var x = 0.0
    @State private var z = 0.0
    @State private var saving = false
    @State private var reviewed = false
    @State private var savedURL: URL?
    @State private var error: String?
    init(scanner:RoomScanner,initial:MapPackage,onBack:@escaping () -> Void) {
        self.scanner = scanner; self.initial = initial; self.onBack = onBack
        _package = State(initialValue:initial); _roomId = State(initialValue:initial.geometry.rooms.first?.id ?? "")
    }
    var body: some View {
        Form {
            Section("Map details") {
                TextField("Venue",text:$package.manifest.venue)
                TextField("Floor",text:$package.manifest.floor)
                TextField("Contributor",text:$package.manifest.contributor)
                Picker("Coverage",selection:$package.manifest.coverage) { Text("Partial scan").tag("partial"); Text("One contiguous zone").tag("contiguous-zone") }
                Text("Only scanned floor areas are included. Adding a room uses the same uninterrupted AR session.").font(.footnote)
            }.disabled(savedURL != nil)
            Section("Review geometry") {
                FloorPlanView(package:package,selected:.init(x:x,z:z),onSelect:{ p in x=p.x; z=p.z }).frame(height:260)
                ForEach($package.geometry.rooms) { $room in TextField("Room name",text:$room.name).accessibilityLabel("Name for scanned area \(room.id)") }
            }.disabled(savedURL != nil)
            Section("Doorway traversal") {
                Text("Confirm only passages you inspected. Unknown and blocked doors stay closed to routing.")
                if package.navigation.doors.isEmpty { Text("No doorway links were detected. Routing stays within scanned room geometry.") }
                ForEach(Array(package.navigation.doors.enumerated()),id:\.element.id) { index,door in
                    Picker("Door \(index+1), \(door.roomIds.compactMap { id in package.geometry.rooms.first { $0.id == id }?.name }.joined(separator:" to "))",selection:Binding(get:{ package.navigation.doors[index].traversability },set:{ state in
                        let center = (door.start+door.end)*0.5
                        for i in package.navigation.doors.indices where ((package.navigation.doors[i].start+package.navigation.doors[i].end)*0.5).distance(to:center) < 0.3 { package.navigation.doors[i].traversability = state }
                    })) { Text("Unknown").tag("unknown"); Text("Confirmed passable").tag("confirmed"); Text("Blocked").tag("blocked") }
                }
            }.disabled(savedURL != nil)
            Section("Label destinations") {
                ForEach(package.landmarks.landmarks) { landmark in
                    HStack { Text(landmark.name); Spacer(); Button("Remove",role:.destructive) { package.landmarks.landmarks.removeAll { $0.id == landmark.id } }.accessibilityLabel("Remove \(landmark.name)") }
                }
                TextField("Destination name",text:$label)
                Picker("Room",selection:$roomId) { ForEach(package.geometry.rooms) { Text($0.name).tag($0.id) } }
                HStack { Text("Map X, metres"); TextField("X",value:$x,format:.number).keyboardType(.numbersAndPunctuation).accessibilityLabel("Destination X coordinate in metres") }
                HStack { Text("Map Z, metres"); TextField("Z",value:$z,format:.number).keyboardType(.numbersAndPunctuation).accessibilityLabel("Destination Z coordinate in metres") }
                Button("Use current phone position",systemImage:"location") {
                    if let frame = scanner.arSession.currentFrame { x=Double(frame.camera.transform.columns.3.x); z=Double(frame.camera.transform.columns.3.z) }
                }
                Button("Add destination",systemImage:"mappin.badge.plus") { addDestination() }.disabled(label.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty)
                Text("Place destinations in clear scanned floor space. Sighted volunteers can also tap the floor plan.").font(.footnote)
            }.disabled(savedURL != nil)
            Section {
                Toggle("I reviewed geometry, labels and doorway traversal",isOn:$reviewed).disabled(savedURL != nil)
                if let savedURL {
                    Label("Complete map saved on this device",systemImage:"checkmark.circle")
                    ShareLink(item:savedURL,label:{ Label("Share map package",systemImage:"square.and.arrow.up") })
                    Button("Done") { dismiss() }
                } else {
                    Button("Save complete map package",systemImage:"square.and.arrow.down") { Task { await save() } }.disabled(saving || !reviewed)
                    if saving { ProgressView("Saving geometry and AR world data together") }
                    Button("Back to capture") { onBack() }
                }
                Text("Saved locally and private by default. Publishing to the community requires a separate explicit action.").font(.footnote)
            }
        }
        .alert("Review status",isPresented:Binding(get:{ error != nil },set:{ if !$0 { error = nil } })) { Button("OK") { error = nil } } message: { Text(error ?? "") }
    }
    private func addDestination() {
        do {
            let position = MapPoint(x:x,z:z)
            guard package.geometry.rooms.contains(where:{ $0.id == roomId && polygonContains(position,$0.polygon) }), try SpatialEngine(package).walkable(position) else { throw TouchSpaceError.invalid("Destination must lie in clear scanned floor space in the selected room.") }
            package.landmarks.landmarks.append(.init(id:UUID().uuidString.lowercased(),name:label.trimmingCharacters(in:.whitespacesAndNewlines),roomId:roomId,position:position))
            label = ""
        } catch { self.error = error.localizedDescription }
    }
    private func save() async {
        saving = true; defer { saving = false }
        do {
            package.manifest.verification = reviewed ? "volunteer-reviewed" : "unverified"
            let worldMap = try await scanner.snapshot()
            let url = library.url(for:package.id)
            package = try PackageCodec.write(package,worldMap:worldMap,to:url)
            library.refresh(); savedURL = url; scanner.stop()
        } catch { self.error = error.localizedDescription }
    }
}
