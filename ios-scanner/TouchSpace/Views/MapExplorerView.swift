import SwiftUI

struct MapExplorerView: View {
    let package: MapPackage
    let api: APIClient?
    @State private var originId: String
    @State private var destinationId: String
    @State private var route: PlannedRoute?
    @State private var planning = false
    @State private var status = "Choose saved places to preview a route."
    @State private var asking = false
    @State private var conversation = UUID()
    init(package:MapPackage,api:APIClient?) {
        self.package = package; self.api = api
        let origin = package.landmarks.landmarks.first { $0.kind == "entrance" } ?? package.landmarks.landmarks.first
        _originId = State(initialValue:origin?.id ?? "")
        _destinationId = State(initialValue:package.landmarks.landmarks.first { $0.id != origin?.id }?.id ?? origin?.id ?? "")
    }
    var body: some View {
        ScrollView {
            VStack(alignment:.leading,spacing:18) {
                if package.manifest.isSynthetic {
                    Label("Interactive demo · No live position",systemImage:"cube.transparent").font(.headline).foregroundStyle(.blue)
                }
                FloorPlanView(package:package,route:route,selected:package.landmarks.landmarks.first { $0.id == destinationId }?.position,onSelect:{ p in
                    if let place = package.landmarks.landmarks.min(by:{ $0.position.distance(to:p) < $1.position.distance(to:p) }), place.position.distance(to:p) < 1.3 { destinationId = place.id }
                }).frame(height:330).background(.quaternary.opacity(0.4),in:RoundedRectangle(cornerRadius:18))
                Text("Select a destination below or tap its floor-plan marker.").font(.footnote).foregroundStyle(.secondary)
                if !package.landmarks.landmarks.isEmpty {
                    Picker("Preview start",selection:$originId) { ForEach(package.landmarks.landmarks) { Text($0.name+" · "+roomName($0.roomId)).tag($0.id) } }
                    Picker("Destination",selection:$destinationId) { ForEach(package.landmarks.landmarks) { Text($0.name+" · "+roomName($0.roomId)).tag($0.id) } }.accessibilityIdentifier("preview-destination")
                    Text("Preview start is a saved map point, not your physical location.").font(.caption).foregroundStyle(.secondary)
                }
                if planning { ProgressView("Planning a validated route") }
                Text(status).accessibilityIdentifier("route-preview-status")
                if package.manifest.isSynthetic {
                    NavigationLink { SimulationEntry(package:package,initialDestination:destinationId.isEmpty ? nil : destinationId) } label: { Label("Open 3D walkthrough",systemImage:"figure.walk") }
                        .buttonStyle(.borderedProminent).controlSize(.large).accessibilityIdentifier("open-walkthrough")
                }
                Button("Ask about this map",systemImage:"text.bubble") { asking = true }.buttonStyle(.bordered).controlSize(.large)
                ForEach(package.geometry.rooms) { room in
                    VStack(alignment:.leading,spacing:10) {
                        Text(room.name).font(.headline)
                        ForEach(package.landmarks.landmarks.filter { $0.roomId == room.id }) { place in
                            Button { destinationId = place.id } label: {
                                Label(place.name,systemImage:place.id == destinationId ? "mappin.circle.fill" : "mappin.circle")
                            }.frame(minHeight:44).accessibilityHint("Preview a route from the selected saved starting point")
                        }
                    }.frame(maxWidth:.infinity,alignment:.leading).padding().background(.quaternary.opacity(0.4),in:RoundedRectangle(cornerRadius:14))
                }
                Text("Unknown areas and unconfirmed doors stay blocked. Geometry and route previews work offline.").font(.footnote).foregroundStyle(.secondary)
            }.padding()
        }
        .navigationTitle("Explore map").navigationBarTitleDisplayMode(.inline)
        .sheet(isPresented:$asking) { AskSheet(package:package,api:api,sessionId:conversation) }
        .task(id:originId+"|"+destinationId) { await preview() }
    }
    private func roomName(_ id:String) -> String { package.geometry.rooms.first { $0.id == id }?.name ?? id }
    private func preview() async {
        route = nil
        guard let origin = package.landmarks.landmarks.first(where:{ $0.id == originId }), !destinationId.isEmpty else { status = "No labelled places are saved yet."; return }
        planning = true
        let package = package, target = destinationId
        do {
            let result = try await Task.detached(priority:.userInitiated) { try SpatialEngine(package).route(from:origin.position,to:target) }.value
            guard !Task.isCancelled else { return }
            route = result; status = "Route preview: \(String(format:"%.1f",result.distance)) metres from \(origin.name). No live localization is used."
        } catch {
            guard !Task.isCancelled else { return }
            status = error.localizedDescription
        }
        planning = false
    }
}
