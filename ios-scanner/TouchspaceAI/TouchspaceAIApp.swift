import SwiftUI
import TouchspaceCore

extension Color {
    static let touchspaceButton=Color(red:15/255,green:92/255,blue:85/255)
    static let touchspaceAccent=Color(UIColor { traits in
        traits.userInterfaceStyle == .dark ? UIColor(red:0.40,green:0.85,blue:0.78,alpha:1) : UIColor(red:15/255,green:92/255,blue:85/255,alpha:1)
    })
}

@main struct TouchspaceAIApp: App {
    @StateObject private var library=MapLibrary()
    var body: some Scene {
        WindowGroup {
            HomeView().environmentObject(library).tint(.touchspaceAccent)
                .onOpenURL { library.importMap($0) }
        }
    }
}
struct Notice: View {
    var text:String
    var body:some View { Label(text,systemImage:"info.circle").font(.body).foregroundStyle(.secondary).fixedSize(horizontal:false,vertical:true).padding(.vertical,4) }
}
struct HomeView: View {
    @EnvironmentObject var library:MapLibrary
    @State private var importing=false
    @State private var catalog=false
    @State private var settings=false
    @State private var scanning=false
    var body:some View {
        NavigationStack {
            List {
                Section {
                    VStack(alignment:.leading,spacing:10) {
                        Image(systemName:"viewfinder.circle.fill").font(.largeTitle).foregroundStyle(.teal).accessibilityHidden(true)
                        Text("Explore a space,\none question at a time.").font(.title2.bold()).accessibilityAddTraits(.isHeader)
                        Text("Download an indoor map, discover its layout, and explore with spoken directions.").foregroundStyle(.secondary)
                    }.padding(.vertical,10)
                }
                Section("Downloaded maps") {
                    if library.maps.isEmpty { Text("No downloaded maps yet. Import a package or try the map-only demo.").foregroundStyle(.secondary) }
                    ForEach(library.maps) { map in
                        NavigationLink { MapDetails(map:map) } label: {
                            VStack(alignment:.leading,spacing:6) {
                                Text(map.package.manifest.title).font(.headline)
                                Text(map.package.manifest.floor+" · "+(map.package.manifest.worldMapIncluded ? "Positioning data included":"Map-only draft")).font(.subheadline).foregroundStyle(.secondary)
                            }.padding(.vertical,5)
                        }.accessibilityLabel("\(map.package.manifest.title), \(map.package.manifest.worldMapIncluded ? "positioning data included":"map-only draft"). Map details")
                    }
                }
                Section("Add a map") {
                    Button { importing=true } label:{ Label("Import from Files",systemImage:"square.and.arrow.down").frame(minHeight:44) }.accessibilityIdentifier("importMap")
                    Button { catalog=true } label:{ Label("Search community maps",systemImage:"magnifyingglass").frame(minHeight:44) }
                    Button { scanning=true } label:{ Label("Scan a space",systemImage:"viewfinder").frame(minHeight:44) }.accessibilityIdentifier("scanSpace")
                    Button { library.addDemo() } label:{ Label("Try the map-only demo",systemImage:"square.stack.3d.up").frame(minHeight:44) }.accessibilityIdentifier("addDemo")
                }
                Section { Notice(text:"Maps describe a structural approximation. They do not detect live obstacles and do not replace a cane or guide dog.") }
            }
            .navigationTitle("Touchspace AI")
            .toolbar { ToolbarItem(placement:.topBarTrailing) { Button { settings=true } label:{ Image(systemName:"gearshape").frame(minWidth:44,minHeight:44) }.accessibilityLabel("Settings") } }
            .fileImporter(isPresented:$importing,allowedContentTypes:[.touchspaceMap,.zip],allowsMultipleSelection:false) { result in
                switch result { case .success(let urls): if let url=urls.first { library.importMap(url) }; case .failure(let error): library.error=error.localizedDescription }
            }
            .sheet(isPresented:$settings) { SettingsView() }
            .sheet(isPresented:$catalog) { CatalogView() }
            .sheet(isPresented:$scanning) { ScanFlow() }
            .alert("Map could not be opened",isPresented:Binding(get:{library.error != nil},set:{if !$0 { library.error=nil }})) { Button("OK",role:.cancel) { library.error=nil } } message:{ Text(library.error ?? "") }
        }
    }
}
struct SettingsView: View {
    @Environment(\.dismiss) var dismiss
    @AppStorage("serverAddress") var address="http://localhost:8000"
    @State private var token=TokenStore.read()
    @State private var error:String?
    var body:some View {
        NavigationStack {
            Form {
                Section("Community server") {
                    TextField("Server URL",text:$address).textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
                    SecureField("Upload authorization token",text:$token).textInputAutocapitalization(.never).autocorrectionDisabled()
                    Text("Browsing public maps needs no token. Ask the server operator for an upload credential. Provider API keys belong on the server.").font(.footnote).foregroundStyle(.secondary)
                }
                Section("Privacy") { Text("Maps stay on this device until you share or upload them. Camera frames and continuous phone positions are never uploaded. Server chat is optional; enabling it sends each question and that turn's current pose to your configured server.") }
                if let error { Section { Text(error).foregroundStyle(.red) } }
            }.navigationTitle("Settings").toolbar {
                ToolbarItem(placement:.confirmationAction) { Button("Done") { do { _=try APIClient(address:address); try TokenStore.write(token); dismiss() } catch { self.error=error.localizedDescription } } }
            }
        }
    }
}
struct CatalogView: View {
    @Environment(\.dismiss) var dismiss
    @EnvironmentObject var library:MapLibrary
    @AppStorage("serverAddress") var address="http://localhost:8000"
    @State private var query=""
    @State private var maps=[CatalogMap]()
    @State private var busy=false
    @State private var message="Search maps shared by volunteers."
    var body:some View {
        NavigationStack {
            List {
                Section { TextField("Search by title or coverage",text:$query).onSubmit { Task { await search() } }; Button("Search") { Task { await search() } }.disabled(busy) }
                Section {
                    if busy { ProgressView("Working…") }
                    Text(message).accessibilityIdentifier("catalogStatus")
                    ForEach(maps) { map in
                        VStack(alignment:.leading,spacing:10) {
                            Text(map.manifest.title).font(.headline)
                            Text(map.manifest.coverage)
                            Text("By \(map.manifest.contributor) · \(map.manifest.verification)").font(.subheadline).foregroundStyle(.secondary)
                            Text("World data included; successful positioning depends on your surroundings.").font(.footnote)
                            Button("Download \(map.manifest.title)") { Task { await download(map) } }.frame(minHeight:44).disabled(busy)
                        }.padding(.vertical,5)
                    }
                }
            }.navigationTitle("Community maps").toolbar { ToolbarItem(placement:.cancellationAction) { Button("Close") { dismiss() } } }
        }
    }
    func search() async {
        busy=true; defer{busy=false}
        do { maps=try await APIClient(address:address,token:TokenStore.read()).search(query); message=maps.isEmpty ? "No shared maps match your search.":"\(maps.count) shared maps found." }
        catch { message=error.localizedDescription }
    }
    func download(_ map:CatalogMap) async {
        busy=true; defer{busy=false}
        do { let p=try await APIClient(address:address,token:TokenStore.read()).download(map); try library.save(p); message="Downloaded \(map.manifest.title). It is now available offline." }
        catch { message=error.localizedDescription }
    }
}
struct MapDetails: View {
    @EnvironmentObject var library:MapLibrary
    var map:LocalMap
    @State private var sharing=false
    @State private var publishing=false
    var body:some View {
        let p=map.package,m=p.manifest
        List {
            Section("About this map") {
                LabeledContent("Coverage",value:m.coverage)
                LabeledContent("Floor",value:m.floor)
                LabeledContent("Contributor",value:m.contributor)
                LabeledContent("Scan date",value:m.createdAt)
                LabeledContent("Updated",value:m.updatedAt)
                LabeledContent("Verification",value:m.verification)
                if m.synthetic { Notice(text:"Synthetic demonstration, not a scan of a real venue. It cannot be used for live positioning.") }
                ForEach(p.warnings,id:\.self) { Notice(text:$0) }
                Notice(text:"Volunteer labels and traversability reflect the scan review, not current conditions. Door accessibility and live obstacles may be unknown.")
            }
            Section("Explore") {
                NavigationLink("Explore map") { ExploreView(map:map,startLive:false) }.frame(minHeight:44).accessibilityIdentifier("exploreMap")
                NavigationLink("Start live exploration") { ExploreView(map:map,startLive:true) }.frame(minHeight:44).disabled(!m.worldMapIncluded)
                if !m.worldMapIncluded { Text("Live exploration requires saved positioning data from a real scan.").font(.footnote) }
            }
            Section("Rooms") { ForEach(p.geometry.rooms) { room in Text(room.name) } }
            Section("Landmarks") {
                ForEach(p.landmarks.landmarks) { lm in
                    VStack(alignment:.leading,spacing:4) {
                        Text(lm.name).font(.headline)
                        Text("\(lm.type) · \(p.geometry.rooms.first{$0.id==lm.roomId}?.name ?? lm.roomId) · \(lm.provenance == "scan" ? "Scan-derived fact":"Volunteer-provided label")").font(.subheadline).foregroundStyle(.secondary)
                    }
                }
            }
            Section("Supplemental floor plan") { PlanView(package:p,pose:nil,route:nil).frame(height:240).accessibilityHidden(true); Text("Room and landmark names are listed above. The visual plan is optional.").font(.footnote) }
            Section("Share") {
                Button("Share complete map package") { sharing=true }.frame(minHeight:44)
                Button("Upload / publish to community") { publishing=true }.frame(minHeight:44)
            }
        }.navigationTitle(m.title)
            .sheet(isPresented:$sharing) { ShareSheet(items:[map.url]) }
            .sheet(isPresented:$publishing) { PublishView(package:p) }
    }
}
struct ShareSheet: UIViewControllerRepresentable {
    var items:[Any]
    func makeUIViewController(context:Context)->UIActivityViewController { UIActivityViewController(activityItems:items,applicationActivities:nil) }
    func updateUIViewController(_ controller:UIActivityViewController,context:Context) {}
}
struct PublishView: View {
    @Environment(\.dismiss) var dismiss
    @AppStorage("serverAddress") var address="http://localhost:8000"
    var package:MapPackage
    @State private var publicly=false
    @State private var consent=false
    @State private var busy=false
    @State private var message=""
    var body:some View {
        NavigationStack {
            Form {
                Section { Text(package.manifest.title).font(.headline); Toggle("Make publicly discoverable",isOn:$publicly).disabled(!package.manifest.worldMapIncluded) }
                Section("Publication consent") {
                    Text("The package includes indoor geometry, volunteer labels, and saved AR world data that may reveal private spaces. Public packages can be downloaded by anyone.")
                    if publicly { Toggle("I have permission to share this space and consent to publish the complete package",isOn:$consent) }
                    else { Text("This upload will be private and accessible only with your server authorization.") }
                }
                Section {
                    Button(publicly ? "Publish map":"Upload privately") { Task { await upload() } }.disabled(busy || (publicly && !consent)).frame(minHeight:44)
                    if busy { ProgressView() }; if !message.isEmpty { Text(message) }
                }
            }.navigationTitle("Share with community").toolbar { ToolbarItem(placement:.cancellationAction) { Button("Close") { dismiss() } } }
        }
    }
    func upload() async {
        busy=true; defer { busy=false }
        do { let m=try await APIClient(address:address,token:TokenStore.read()).upload(package,publicly:publicly,consent:consent); message=m.visibility=="public" ? "Published to the community catalog.":"Uploaded privately." }
        catch { message=error.localizedDescription }
    }
}
