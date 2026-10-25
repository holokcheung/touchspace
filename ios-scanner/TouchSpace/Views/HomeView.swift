import SwiftUI
import UniformTypeIdentifiers

extension UTType { static let touchSpaceMap = UTType(exportedAs:"ai.touchspace.map",conformingTo:.zip) }

struct HomeView: View {
    @EnvironmentObject private var library: MapLibrary
    @AppStorage("backendURL") private var backendURL = "http://localhost:8000"
    @State private var query = ""
    @State private var results: [MapSummary] = []
    @State private var importing = false
    @State private var scanning = false
    @State private var settings = false
    @State private var busy = false
    @State private var error: String?
    @State private var searchGeneration = 0
    @State private var demoMaps: [MapPackage] = []
    @State private var showingDemos = false
    private var api: APIClient? { APIClient.configured }
    var body: some View {
        NavigationStack {
            List {
                Section {
                    Button("Scan space",systemImage:"camera.viewfinder") { scanning = true }
                    Button("Import from community",systemImage:"square.and.arrow.down") { importing = true }
                    Button("Try demo spaces",systemImage:"cube.transparent") { loadDemos() }.accessibilityIdentifier("load-demo-maps")
                }.controlSize(.large)
                Section("Downloaded maps · available offline") {
                    if library.maps.isEmpty { Text("Import a .touchspacemap file, scan a space, or download a community map.") }
                    ForEach(library.maps) { package in
                        NavigationLink { MapDetailView(package:package,api:api) } label: {
                            VStack(alignment:.leading) { Text(package.manifest.venue).font(.headline); if package.manifest.isSynthetic { Text("Synthetic fixture · Interactive demo").font(.caption) }; Text("\(package.manifest.floor) · \(package.manifest.coverage)").font(.subheadline) }
                        }
                    }
                }
                Section("Community maps") {
                    Button("Search community",systemImage:"magnifyingglass") { Task { await search() } }.disabled(busy || api == nil)
                    if busy { ProgressView("Working") }
                    ForEach(results) { summary in
                        VStack(alignment:.leading,spacing:6) {
                            Text(summary.manifest.venue).font(.headline)
                            if summary.manifest.isSynthetic { Text("Synthetic fixture · Interactive demo").font(.caption) }
                            Text("\(summary.manifest.floor) · \(summary.manifest.coverage) · \(summary.manifest.contributor)").font(.subheadline)
                            Button("Download complete map",systemImage:"arrow.down.circle") { Task { await download(summary.id) } }.disabled(busy)
                        }
                    }
                    Text("Community scans may be partial or outdated. Check contributor, review status and capture date before visiting.").font(.footnote)
                }
            }
            .navigationTitle("TouchSpace")
            .navigationDestination(isPresented:$showingDemos) { DemoSpacesView(maps:demoMaps,api:api) }
            .searchable(text:$query,prompt:"Search venues")
            .onSubmit(of:.search) { Task { await search() } }
            .toolbar { ToolbarItem(placement:.primaryAction) { Button("Settings",systemImage:"gear") { settings = true } } }
            .sheet(isPresented:$scanning) { ScannerView() }
            .sheet(isPresented:$settings) { SettingsView() }
            .fileImporter(isPresented:$importing,allowedContentTypes:[.touchSpaceMap,.zip]) { result in
                do { _ = try library.importMap(result.get()) } catch { self.error = error.localizedDescription }
            }
            .alert("Map status",isPresented:Binding(get:{ error != nil },set:{ if !$0 { error = nil } })) { Button("OK") { error = nil } } message: { Text(error ?? "") }
        }
    }
    private func loadDemos() {
        do {
            var loaded: [MapPackage] = []
            for name in ["harbour-clinic","neighbourhood-library"] {
                guard let url = Bundle.main.url(forResource:name,withExtension:"touchspacemap") else { throw TouchSpaceError.invalid("Demo bundle is missing from this app build.") }
                let map = try PackageCodec.load(url)
                if !library.maps.contains(where:{ $0.id == map.id }) { _ = try library.importMap(url) }
                loaded.append(map)
            }
            demoMaps = loaded
            showingDemos = true
        } catch { self.error = error.localizedDescription }
    }
    private func search() async {
        guard let api else { return }
        searchGeneration += 1; let generation = searchGeneration
        busy = true
        defer { if generation == searchGeneration { busy = false } }
        do { let response = try await api.search(query); if generation == searchGeneration { results = response } }
        catch { if generation == searchGeneration { self.error = error.localizedDescription } }
    }
    private func download(_ id:UUID) async {
        guard let api else { return }; busy = true; defer { busy = false }
        do {
            let url = try await api.download(id)
            defer { try? FileManager.default.removeItem(at:url) }
            _ = try library.importMap(url)
        } catch { self.error = error.localizedDescription }
    }
}

struct MapDetailView: View {
    let package: MapPackage
    let api: APIClient?
    @EnvironmentObject private var library: MapLibrary
    @State private var publishing = false
    var body: some View {
        List {
            Section {
                Text(package.manifest.floor).font(.title2)
                Text("Coverage: \(package.manifest.coverage)")
                Text("Contributor: \(package.manifest.contributor)")
                Text("Review: \(package.manifest.verification)")
                Text("\(package.manifest.isSynthetic ? "Created" : "Captured"): \(package.manifest.createdAt)")
                FloorPlanView(package:package).frame(height:240)
            }
            Section {
                NavigationLink { MapExplorerView(package:package,api:api) } label: { Label("Explore map",systemImage:"map") }.accessibilityIdentifier("explore-map")
                if package.manifest.isSynthetic {
                    NavigationLink { SimulationEntry(package:package,api:api) } label: { Label("3D walkthrough",systemImage:"figure.walk") }.accessibilityIdentifier("demo-walkthrough")
                    Text("Explore in first person: swipe to turn, use the chevrons to move, and hold the microphone for spoken map questions. This is a virtual space.").font(.footnote)
                } else {
                    NavigationLink { LiveEntry(package:package,url:library.url(for:package.id),api:api) } label: { Label("Start AR navigation",systemImage:"viewfinder") }
                }
            }
            Section("Rooms and destinations") {
                ForEach(package.geometry.rooms) { room in
                    VStack(alignment:.leading) {
                        Text(room.name).font(.headline)
                        ForEach(package.landmarks.landmarks.filter { $0.roomId == room.id }) { Text($0.name) }
                    }
                }
            }
            Section("Sharing") {
                ShareLink(item:library.url(for:package.id),label:{ Label("Share complete map package",systemImage:"square.and.arrow.up") })
                Button("Upload or publish",systemImage:"icloud.and.arrow.up") { publishing = true }.disabled(api == nil)
                Text("Geometry remains browsable offline. Live guidance requires verified alignment with this saved AR world map. This prototype does not replace mobility aids or provide certified collision avoidance.").font(.footnote)
            }
        }
        .navigationTitle(package.manifest.venue)
        .sheet(isPresented:$publishing) { if let api { PublishView(api:api,url:library.url(for:package.id)) } }
    }
}

struct SettingsView: View {
    @AppStorage("backendURL") private var backendURL = "http://localhost:8000"
    @Environment(\.dismiss) private var dismiss
    @State private var draft = ""
    @State private var error: String?
    var body: some View {
        NavigationStack {
            Form {
                Section("Backend") {
                    TextField("Server URL",text:$draft).textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
                    Text("For an iPhone on the same Wi-Fi, use your Mac's LAN address on port 8000. Use HTTPS for a hosted backend. Server API keys stay on the backend.").font(.footnote)
                    if let error { Text(error).foregroundStyle(.red) }
                }
            }.navigationTitle("Settings")
                .toolbar { ToolbarItem(placement:.confirmationAction) { Button("Save") {
                    guard let url=URL(string:draft), ["http","https"].contains(url.scheme), url.host != nil, url.user == nil, url.password == nil, url.query == nil, url.fragment == nil else { error = "Enter a valid HTTP or HTTPS server URL."; return }
                    backendURL = draft.trimmingCharacters(in:CharacterSet(charactersIn:"/")); dismiss()
                } } }
                .onAppear { draft = backendURL }
        }
    }
}

struct PublishView: View {
    let api: APIClient
    let url: URL
    @Environment(\.dismiss) private var dismiss
    @State private var code = ""
    @State private var makePublic = false
    @State private var consent = false
    @State private var busy = false
    @State private var status = ""
    @State private var paired = false
    var body: some View {
        NavigationStack {
            Form {
                Section("Demo publishing credential") {
                    SecureField("Server pairing code",text:$code).textInputAutocapitalization(.never)
                    Button("Pair for one hour") { Task {
                        busy = true; defer { busy = false }
                        do { try await api.pair(code:code); code=""; paired=true; status="Paired. Publishing credential saved securely in Keychain." }
                        catch { status=error.localizedDescription }
                    } }.disabled(busy || code.isEmpty)
                    Text("Ask the server operator for the pairing code. No permanent upload token is embedded in this app.").font(.footnote)
                }
                Section("Visibility") {
                    Toggle("Make this map public",isOn:$makePublic).onChange(of:makePublic) { _,_ in consent=false }
                    if makePublic { Toggle("I have permission to share this venue's geometry and AR world data publicly",isOn:$consent) }
                    Text(makePublic ? "Public maps can be searched and downloaded by anyone, including the complete AR archive." : "Private upload. Excluded from community search and protected by your publishing credential.")
                }
                Button(makePublic ? "Publish complete map" : "Upload privately") { Task {
                    busy=true; defer { busy=false }
                    do { try await api.upload(url,makePublic:makePublic,consent:consent); status=makePublic ? "Map published to the community." : "Map uploaded privately." }
                    catch { status=error.localizedDescription }
                } }.disabled(busy || (!paired && api.token == nil) || (makePublic && !consent))
                if busy { ProgressView("Working") }
                if !status.isEmpty { Text(status).accessibilityAddTraits(.updatesFrequently) }
            }.navigationTitle("Share a map")
                .toolbar { ToolbarItem(placement:.confirmationAction) { Button("Done") { dismiss() } } }
        }
    }
}
