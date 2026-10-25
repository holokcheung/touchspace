import SwiftUI

struct SimulationEntry: View {
    let package: MapPackage
    var api: APIClient? = APIClient.configured
    var initialDestination: String? = nil
    @State private var session: SimulationSession?
    @State private var error: String?
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        Group {
            if let session { SimulationView(session:session,initialDestination:initialDestination) }
            else if let error { ContentUnavailableView("Walkthrough unavailable",systemImage:"cube",description:Text(error)) }
            else { ProgressView("Building the virtual space") }
        }
        .toolbar(.hidden,for:.navigationBar)
        .overlay(alignment:.topLeading) {
            if error != nil { Button("Back",systemImage:"chevron.left") { dismiss() }.padding() }
        }
        .task {
            guard session == nil else { return }
            do { session = try SimulationSession(package:package,api:api) } catch { self.error = error.localizedDescription }
        }
    }
}

struct SimulationView: View {
    @ObservedObject var session: SimulationSession
    @ObservedObject private var voice: WalkthroughVoice
    let initialDestination: String?
    @State private var previousDrag = 0.0
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.dismiss) private var dismiss

    init(session:SimulationSession,initialDestination:String?) {
        self.session = session; self.initialDestination = initialDestination
        self.voice = session.voice
    }

    var body: some View {
        GeometryReader { geometry in
            ZStack {
                VirtualMapView(scene:session.scene,pose:session.engine.pose,route:session.engine.route,viewpoint:.walk)
                    .ignoresSafeArea().accessibilityHidden(true)
                Color.clear.contentShape(Rectangle())
                    .gesture(DragGesture(minimumDistance:5)
                        .onChanged { value in
                            // A full-width swipe turns about half a circle. Use deltas to avoid jumps.
                            let angle = Double(value.translation.width / max(geometry.size.width,1)) * .pi
                            if !voice.isBusy { session.turn(angle-previousDrag) }
                            previousDrag = angle
                        }
                        .onEnded { _ in previousDrag = 0 })
                    .accessibilityElement().accessibilityLabel("First-person view")
                    .accessibilityValue("Virtual position \(String(format:"%.1f",session.engine.pose.position.x)), \(String(format:"%.1f",session.engine.pose.position.z)); heading \(Int(session.engine.pose.heading * 180 / .pi)) degrees")
                    .accessibilityHint("Swipe left or right to look around. Adjust up or down with VoiceOver to turn.")
                    .accessibilityAdjustableAction { direction in
                        guard !voice.isBusy else { return }
                        session.turn(direction == .increment ? .pi/6 : -.pi/6)
                    }
                    .accessibilityIdentifier("simulation-look-surface")

                VStack(spacing:0) {
                    HStack(alignment:.top,spacing:12) {
                        Button { session.stop(); dismiss() } label: {
                            Image(systemName:"xmark").font(.headline).frame(width:48,height:48)
                                .background(.black.opacity(0.58),in:Circle())
                        }.accessibilityLabel("Leave walkthrough").accessibilityIdentifier("simulation-close")
                        VStack(alignment:.leading,spacing:4) {
                            Text("DEMO SPACE").font(.caption2.bold()).tracking(1.8).foregroundStyle(.white.opacity(0.75))
                            Text(session.package.manifest.venue.replacingOccurrences(of:" (Synthetic)",with:""))
                                .font(.subheadline.weight(.semibold)).lineLimit(2)
                            if let destination = session.destination {
                                Text("\(destination.name) · \(String(format:"%.1f",session.remaining)) m")
                                    .font(.caption).accessibilityIdentifier("simulation-destination")
                            }
                        }.padding(12).frame(maxWidth:.infinity,alignment:.leading)
                            .background(.black.opacity(0.58),in:RoundedRectangle(cornerRadius:18))
                    }
                    Spacer()
                    HStack {
                        Spacer()
                        VStack(spacing:12) {
                            stepButton(forward:true)
                            stepButton(forward:false)
                        }
                    }.padding(.bottom,24)
                    VoicePromptControl(voice:session.voice)
                }.padding(.horizontal,20).padding(.top,12).padding(.bottom,20)
            }.foregroundStyle(.white)
        }
        .background(.black)
        .toolbar(.hidden,for:.navigationBar)
        .statusBarHidden(true)
        .persistentSystemOverlays(.hidden)
        .onAppear { session.start(initialDestination:initialDestination) }
        .onDisappear { session.stop() }
        .onChange(of:scenePhase) { _,phase in if phase != .active { session.suspend() } }
    }

    private func stepButton(forward:Bool) -> some View {
        Button { session.move(forward ? 0.5 : -0.5) } label: {
            Image(systemName:forward ? "chevron.up" : "chevron.down")
                .resizable().frame(width:54,height:18)
                .fontWeight(.bold).frame(width:126,height:60)
                .background(.black.opacity(0.58),in:RoundedRectangle(cornerRadius:22))
                .overlay { RoundedRectangle(cornerRadius:22).strokeBorder(.white.opacity(0.24)) }
        }
        .disabled(session.planning || voice.isBusy)
        .opacity(session.planning || voice.isBusy ? 0.4 : 1)
        .accessibilityLabel(forward ? "Move forward" : "Move backward")
        .accessibilityHint("Move half a metre if the floor is clear")
        .accessibilityIdentifier(forward ? "simulation-forward" : "simulation-backward")
    }
}

private struct VoicePromptControl: View {
    @ObservedObject var voice: WalkthroughVoice
    @GestureState private var touching = false
    @State private var pressing = false
    var body: some View {
        VStack(spacing:10) {
            Text(voice.status).font(.subheadline.weight(.medium)).multilineTextAlignment(.center)
                .padding(.horizontal,14).padding(.vertical,8)
                .background(.black.opacity(0.58),in:Capsule())
                .accessibilityIdentifier("simulation-voice-status")
            ZStack {
                Circle().fill(voice.phase == .listening ? Color.red : Color.touchSpaceMintFill)
                Circle().strokeBorder(.white.opacity(0.8),lineWidth:2)
                Image(systemName:voice.phase == .listening ? "waveform" : voice.phase == .thinking ? "ellipsis" : "mic.fill")
                    .resizable().scaledToFit().frame(width:28,height:32).foregroundStyle(.white)
            }.frame(width:82,height:82)
                .scaleEffect(touching ? 1.08 : 1)
                .contentShape(Circle())
                .gesture(DragGesture(minimumDistance:0)
                    .updating($touching) { _,state,_ in state = true }
                    .onChanged { _ in if !pressing { pressing = true; voice.press() } }
                    .onEnded { _ in pressing = false; voice.release() })
                .onChange(of:touching) { _,down in if !down { pressing = false; voice.release() } }
                .accessibilityElement().accessibilityAddTraits(.isButton)
                .accessibilityLabel("Hold to ask TouchSpace")
                .accessibilityValue(voice.status)
                .accessibilityHint("Hold while speaking, then release to send. With VoiceOver, double tap to start and double tap again to send.")
                .accessibilityAction { voice.toggleAccessibleRecording() }
                .accessibilityIdentifier("simulation-microphone")
        }
        .alert("Voice unavailable",isPresented:Binding(get:{ voice.error != nil },set:{ if !$0 { voice.error = nil } })) {
            Button("OK") { voice.error = nil }
        } message: { Text(voice.error ?? "") }
    }
}
