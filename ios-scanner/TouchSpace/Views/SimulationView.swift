import ARKit
import AVFoundation
import SwiftUI

struct SimulationEntry: View {
    let package: MapPackage
    var initialDestination: String? = nil
    @State private var session: SimulationSession?
    @State private var error: String?
    var body: some View {
        Group {
            if let session { SimulationView(session:session,initialDestination:initialDestination) }
            else if let error { ContentUnavailableView("Walkthrough unavailable",systemImage:"cube",description:Text(error)) }
            else { ProgressView("Building the virtual space") }
        }.task {
            guard session == nil else { return }
            do { session = try SimulationSession(package:package) } catch { self.error = error.localizedDescription }
        }
    }
}

struct SimulationView: View {
    @ObservedObject var session: SimulationSession
    let initialDestination: String?
    @State private var destinations = false
    @State private var asking = false
    @State private var minimap = false
    @State private var arModel = false
    @State private var conversation = UUID()
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        VStack(spacing:0) {
            VStack(alignment:.leading,spacing:5) {
                Label("SIMULATION · Virtual position",systemImage:"cube.transparent").font(.headline).foregroundStyle(.blue)
                Text(session.destination.map { "\($0.name) · \(String(format:"%.1f",session.remaining)) m remaining" } ?? "No destination selected")
                    .accessibilityIdentifier("simulation-destination")
                Text(session.instruction).font(.subheadline).accessibilityIdentifier("simulation-status")
                if session.planning { ProgressView("Planning route") }
                Picker("Viewpoint",selection:$session.viewpoint) { ForEach(VirtualMapScene.Viewpoint.allCases) { Text($0.rawValue).tag($0) } }.pickerStyle(.segmented)
            }.padding().background(.regularMaterial)
            ZStack(alignment:.bottomTrailing) {
                VirtualMapView(scene:session.scene,pose:session.engine.pose,route:session.engine.route,viewpoint:session.viewpoint)
                    .accessibilityHidden(true)
                if minimap {
                    FloorPlanView(package:session.package,route:session.engine.route,pose:session.engine.pose.position,heading:session.engine.pose.heading)
                        .frame(width:200,height:180).background(.regularMaterial,in:RoundedRectangle(cornerRadius:12)).padding(8)
                }
            }.frame(maxWidth:.infinity,maxHeight:.infinity).frame(minHeight:200)
            ScrollView {
                VStack(spacing:8) {
                    LazyVGrid(columns:[GridItem(.adaptive(minimum:105))],spacing:8) {
                        DemoControl("Left 30°",icon:"arrow.turn.up.left") { session.turn(-.pi/6) }.accessibilityIdentifier("simulation-left")
                        DemoControl("Forward",icon:"arrow.up") { session.move(0.5) }.accessibilityHint("Move the virtual camera half a metre, if clear").accessibilityIdentifier("simulation-forward")
                        DemoControl("Right 30°",icon:"arrow.turn.up.right") { session.turn(.pi/6) }
                        DemoControl("Back",icon:"arrow.down") { session.move(-0.5) }
                        DemoControl(session.engine.following ? "Pause" : "Play route",icon:session.engine.following ? "pause.fill" : "play.fill") { session.togglePlayback() }
                            .disabled(session.engine.route == nil).accessibilityIdentifier("simulation-play")
                        DemoControl("Places",icon:"mappin.and.ellipse") { destinations = true }.accessibilityLabel("Destinations").accessibilityIdentifier("simulation-destinations")
                        DemoControl("Ask",icon:"text.bubble") { session.pause(); asking = true }
                        DemoControl("Repeat",icon:"speaker.wave.2") { session.audio.repeatLast() }
                        DemoControl(minimap ? "Hide plan" : "Plan",icon:"map") { minimap.toggle() }
                    }.buttonStyle(.borderedProminent).controlSize(.regular).disabled(session.planning)
                    HStack {
                        Button("Reset",systemImage:"arrow.counterclockwise") { session.reset() }
                        Button("End",systemImage:"xmark.circle") { session.stop(); dismiss() }
                        Menu("Audio",systemImage:"speaker") { AudioModePicker(audio:session.audio) }
                    }.buttonStyle(.bordered)
                    Text("No physical location or camera tracking. Movement and speech are simulated. 3D heights are illustrative.").font(.caption).foregroundStyle(.secondary)
                }.padding()
            }.frame(maxHeight:300).background(.regularMaterial)
        }
        .navigationTitle("3D walkthrough").navigationBarTitleDisplayMode(.inline)
        .toolbar { ToolbarItem(placement:.primaryAction) { Button("AR model",systemImage:"arkit") { session.pause(); arModel = true } } }
        .sheet(isPresented:$destinations) { DestinationPicker(package:session.package,canNavigate:true) { session.plan(to:$0.id) } }
        .sheet(isPresented:$asking) {
            AskSheet(package:session.package,api:nil,simulatedPose:{ session.engine.pose },audio:session.audio,onNavigate:{ session.plan(to:$0) },sessionId:conversation)
        }
        .sheet(isPresented:$arModel) { ARModelPreview(package:session.package,pose:session.engine.pose,route:session.engine.route) }
        .alert("Simulation route",isPresented:Binding(get:{ session.error != nil },set:{ if !$0 && session.error != nil { session.error = nil } })) { Button("OK") { session.error = nil } } message:{ Text(session.error ?? "") }
        .onAppear { session.start(initialDestination:initialDestination) }
        .onDisappear { session.stop() }
        .onChange(of:scenePhase) { _,phase in if phase != .active { session.pause() } }
    }
}

private struct DemoControl: View {
    let title:String
    let icon:String
    let action:() -> Void
    init(_ title:String,icon:String,action:@escaping () -> Void) { self.title=title; self.icon=icon; self.action=action }
    var body: some View {
        Button(action:action) {
            VStack(spacing:4) { Image(systemName:icon).font(.body); Text(title).font(.subheadline).lineLimit(2).multilineTextAlignment(.center) }
                .frame(maxWidth:.infinity,minHeight:46)
        }.accessibilityLabel(title)
    }
}

private struct AudioModePicker: View {
    @ObservedObject var audio: AudioGuidance
    var body: some View { Picker("Guidance audio",selection:$audio.mode) { ForEach(AudioGuidance.Mode.allCases) { Text($0.rawValue).tag($0) } } }
}

struct ARModelPreview: View {
    let package: MapPackage
    let pose: SimulatedPose
    let route: PlannedRoute?
    @State private var scene: VirtualMapScene?
    @State private var status = "Preparing AR model preview"
    @State private var unavailable = false
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase
    var body: some View {
        NavigationStack {
            VStack(spacing:12) {
                Label("AR MODEL · No venue alignment",systemImage:"arkit").font(.headline)
                Text("A miniature virtual map placed in front of this device. This does not restore the mock venue or guide real walking.").font(.subheadline).padding(.horizontal)
                if let scene {
                    VirtualMapView(scene:scene,pose:pose,route:route,viewpoint:.overview).accessibilityHidden(true)
                    Button("Place model in front of me",systemImage:"cube") { status = scene.placeAR() ? "Virtual model placed. Move the device to inspect it." : "Waiting for normal camera tracking. Look around and try again." }.buttonStyle(.borderedProminent)
                } else if unavailable {
                    ContentUnavailableView("Use the 3D walkthrough here",systemImage:"cube",description:Text("The simulator has no live AR camera. On a camera-capable iPhone, AR model preview uses ordinary ARKit and does not require LiDAR."))
                } else { ProgressView() }
                Text(status).font(.footnote).padding()
            }.navigationTitle("AR model preview").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement:.confirmationAction) { Button("Done") { scene?.stop(); dismiss() } } }
        }
        .task {
            #if targetEnvironment(simulator)
            unavailable = true; status = "Virtual 3D exploration is fully available in the walkthrough."
            #else
            guard ARWorldTrackingConfiguration.isSupported else { unavailable = true; status = "AR tracking is not supported on this device."; return }
            guard await AVCaptureDevice.requestAccess(for:.video) else { unavailable = true; status = "Camera access was declined. Use the 3D walkthrough."; return }
            do { let scene = try VirtualMapScene(package:package,arPreview:true); self.scene = scene; scene.startAR(); status = "Look around until camera tracking is ready, then place the model." }
            catch { unavailable = true; status = error.localizedDescription }
            #endif
        }
        .onDisappear { scene?.stop() }
        .onChange(of:scenePhase) { _,phase in if phase != .active { scene?.stop() } else { scene?.startAR(); status = "Camera resumed. Place the model again." } }
    }
}
