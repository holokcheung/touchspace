import AVFoundation
import SwiftUI

struct LiveEntry: View {
    let package: MapPackage
    let url: URL
    let api: APIClient?
    @State private var session: NavigationSession?
    @State private var error: String?
    var body: some View {
        Group {
            if let session { LiveNavigationView(session:session,api:api) }
            else if let error { ContentUnavailableView("AR navigation unavailable",systemImage:"camera",description:Text(error+" Return to the map for offline exploration.")) }
            else { ProgressView("Loading saved AR world map") }
        }.task {
            guard session == nil else { return }
            guard await AVCaptureDevice.requestAccess(for:.video) else { error = "Camera access is required for automatic localization."; return }
            do { session = try NavigationSession(package:package,url:url) }
            catch { self.error = error.localizedDescription }
        }
    }
}

struct LiveNavigationView: View {
    @ObservedObject var session: NavigationSession
    let api: APIClient?
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase
    var body: some View { LiveCameraContent(session:session,localization:session.localization,audio:session.audio,api:api) }
}

private struct LiveCameraContent: View {
    @ObservedObject var session: NavigationSession
    @ObservedObject var localization: ARLocalization
    @ObservedObject var audio: AudioGuidance
    let api: APIClient?
    @State private var ask = false
    @State private var destinations = false
    @State private var minimap = false
    @State private var conversation = UUID()
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase
    var body: some View {
        ZStack {
            CameraView(localization:localization).ignoresSafeArea().accessibilityHidden(true)
            VStack {
                VStack(alignment:.leading,spacing:6) {
                    Text(session.package.manifest.venue).font(.headline)
                    Label(localization.status.rawValue,systemImage:localization.status == .localized ? "location.fill" : "location.slash")
                    if let destination = session.destination { Text("\(destination.name) · \(Int(session.remaining.rounded())) metres remaining") }
                    Text(localization.status == .localized ? session.nextAction : localization.instruction).font(.subheadline)
                    if localization.status != .localized {
                        HStack {
                            Button("Retry",systemImage:"arrow.clockwise") { session.end(); localization.retry() }
                            Button("Map only",systemImage:"map") { dismiss() }
                        }.buttonStyle(.bordered)
                    }
                    if session.planning { ProgressView("Planning a validated route. Stay still.") }
                }
                .padding().frame(maxWidth:.infinity,alignment:.leading).background(.regularMaterial,in:RoundedRectangle(cornerRadius:18))
                .accessibilityElement(children:.contain).accessibilitySortPriority(2)
                Spacer()
                if minimap {
                    FloorPlanView(package:session.package,route:session.route,pose:localization.pose?.position)
                        .frame(height:190).background(.regularMaterial,in:RoundedRectangle(cornerRadius:12))
                }
            }.padding()
        }
        .safeAreaInset(edge:.bottom) {
            VStack(spacing:8) {
                LazyVGrid(columns:[GridItem(.adaptive(minimum:120))],spacing:8) {
                    Button("Ask",systemImage:"mic") { session.interruptForQuestion(); ask = true }
                    Button("Repeat",systemImage:"speaker.wave.2") { audio.repeatLast() }
                    Button(session.paused ? "Resume" : "Pause",systemImage:session.paused ? "play" : "pause") { session.togglePause() }
                    Button("End",systemImage:"xmark.circle") { session.stop(); dismiss() }
                    Button("Destinations",systemImage:"mappin.and.ellipse") { destinations = true }
                    Button(minimap ? "Hide plan" : "Plan",systemImage:"map") { minimap.toggle() }
                }
                Picker("Guidance audio",selection:$audio.mode) { ForEach(AudioGuidance.Mode.allCases) { Text($0.rawValue).tag($0) } }.pickerStyle(.menu)
            }
            .buttonStyle(.borderedProminent).controlSize(.large).padding().frame(maxWidth:.infinity).background(.regularMaterial)
            .accessibilitySortPriority(1)
        }
        .toolbar(.hidden,for:.navigationBar)
        .sheet(isPresented:$destinations) {
            DestinationPicker(package:session.package,canNavigate:localization.pose != nil) { session.navigate(to:$0) }
        }
        .sheet(isPresented:$ask) {
            AskSheet(package:session.package,api:api,pose:{ localization.pose },audio:audio,onNavigate:{ id in
                if let place = session.package.landmarks.landmarks.first(where: { $0.id == id }) { session.navigate(to:place) }
            },sessionId:conversation)
        }
        .alert("Navigation status",isPresented:Binding(get:{ session.error != nil },set:{ if !$0 { session.error = nil } })) { Button("OK") { session.error = nil } } message: { Text(session.error ?? "") }
        .onAppear { localization.start() }
        .onDisappear { session.stop() }
        .onChange(of:scenePhase) { _,phase in
            if phase != .active { session.end(); localization.stop() }
            else { localization.start() }
        }
    }
}

struct DestinationPicker: View {
    let package: MapPackage
    var canNavigate: Bool
    var onSelect: (Landmark) -> Void
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            List {
                if !canNavigate { Text("Automatic localization is required to start live guidance.") }
                ForEach(package.geometry.rooms) { room in
                    Section(room.name) {
                        ForEach(package.landmarks.landmarks.filter { $0.roomId == room.id }) { landmark in
                            Button(landmark.name) { onSelect(landmark); dismiss() }.disabled(!canNavigate)
                                .accessibilityHint("Start a validated route to \(landmark.name)")
                        }
                    }
                }
            }.touchSpaceBackground().navigationTitle("Destinations")
                .toolbar { ToolbarItem(placement:.confirmationAction) { Button("Done") { dismiss() } } }
        }
    }
}
