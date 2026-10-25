import SwiftUI

@MainActor final class SimulationSession: ObservableObject {
    let package: MapPackage
    let scene: VirtualMapScene
    let audio = AudioGuidance()
    lazy var voice: WalkthroughVoice = {
        let (capture,hint) = makeVoiceCapture()
        return WalkthroughVoice(capture:capture,inputHint:hint,interrupt:{ [weak self] in self?.interruptGuidance() },
            answer:{ [weak self] message in
                guard let self else { throw CancellationError() }
                return try await self.answer(message)
            },speak:{ [weak self] in self?.audio.say($0,urgent:true) })
    }()
    private func makeVoiceCapture() -> (VoiceCapture,String) {
        #if DEBUG
        if let index = ProcessInfo.processInfo.arguments.firstIndex(of:"--ui-test-voice"),
           ProcessInfo.processInfo.arguments.indices.contains(index+1) {
            return (FixtureVoiceCapture(text:ProcessInfo.processInfo.arguments[index+1]),"Hold to ask · swipe to look")
        }
        #endif
        #if targetEnvironment(simulator)
        let configured = UserDefaults.standard.string(forKey:"backendURL") ?? "http://localhost:8000"
        let url = URL(string:configured) ?? URL(string:"http://localhost:8000")!
        return (ServerSpeechInput(api:APIClient(baseURL:url)),"Hold to ask · speech via your Mac")
        #else
        return (SpeechInput(),"Hold to ask · swipe to look")
        #endif
    }
    @Published private(set) var engine: SimulationEngine
    @Published private(set) var planning = false
    @Published private(set) var remaining = 0.0
    private var generation = 0
    private var stopped = false
    var destination: Landmark? { package.landmarks.landmarks.first { $0.id == engine.destinationId } }
    init(package:MapPackage) throws {
        self.package = package; engine = try SimulationEngine(package:package); scene = try VirtualMapScene(package:package)
        // Face into the space through a confirmed opening, rather than a fixed compass heading.
        let position = engine.pose.position, room = engine.spatial.room(at:engine.pose.position)?.id
        let openings = package.navigation.doors.filter { $0.traversability == "confirmed" && $0.roomIds.contains(room ?? "") }
            .map { ($0.start+$0.end)*0.5 }.sorted { position.distance(to:$0) < position.distance(to:$1) }
        if let opening = openings.first {
            engine.turn(atan2(opening.x-position.x,-(opening.z-position.z))-engine.pose.heading)
        }
        if ProcessInfo.processInfo.arguments.contains("--ui-test-mute") { audio.mode = .mute }
    }
    func start(initialDestination:String?) {
        stopped = false
        if engine.route == nil, let initialDestination { plan(to:initialDestination) }
    }
    func plan(to id:String) {
        generation += 1; let expected = generation
        engine.clearRoute(); audio.stop(); planning = true; remaining = 0
        let package = package, pose = engine.pose
        Task {
            do {
                let candidate = try await Task.detached(priority:.userInitiated) {
                    var copy = try SimulationEngine(package:package,currentPose:pose); try copy.plan(to:id); return copy
                }.value
                guard expected == generation && !stopped else { return }
                engine = candidate; planning = false; remaining = candidate.route?.distance ?? 0
                audio.say("Route to \(destination?.name ?? "destination"), \(String(format:"%.1f",remaining)) metres. Follow the yellow line using the forward controls.",urgent:true)
            } catch {
                guard expected == generation && !stopped else { return }
                planning = false; audio.say(error.localizedDescription,urgent:true)
            }
        }
    }
    func move(_ metres:Double) {
        guard !planning, !voice.isBusy else { return }
        audio.stop()
        if engine.move(metres) { cue() }
        else { audio.say("That step is blocked. Turn to find a clear path.",urgent:true) }
    }
    func turn(_ radians:Double) {
        guard !planning, !voice.isBusy else { return }
        engine.turn(radians)
    }
    /// The assistant uses only saved geometry and an explicitly virtual pose, never physical AR tracking.
    func answer(_ message:String) async throws -> String {
        generation += 1; let expected = generation
        let package = package, pose = engine.pose
        let result: (ExplorationReply,SimulationEngine?)
        do {
            result = try await Task.detached(priority:.userInitiated) { () -> (ExplorationReply,SimulationEngine?) in
                let reply = try OfflineMapAssistant.answer(message,package:package,simulatedPose:pose)
                var planned: SimulationEngine?
                if let id = reply.destinationId {
                    var copy = try SimulationEngine(package:package,currentPose:pose)
                    try copy.plan(to:id); planned = copy
                }
                return (reply,planned)
            }.value
        } catch {
            try Task.checkCancellation()
            guard !stopped, expected == generation else { throw CancellationError() }
            engine.clearRoute(); remaining = 0
            throw error
        }
        try Task.checkCancellation()
        guard !stopped, expected == generation else { throw CancellationError() }
        planning = false
        if let planned = result.1 { engine = planned; remaining = planned.route?.distance ?? 0 }
        return result.0.answer
    }
    private func interruptGuidance() {
        generation += 1; planning = false; engine.pause(); audio.stop()
    }
    func suspend() { generation += 1; planning = false; voice.cancel(); engine.pause(); audio.stop() }
    func stop() { stopped = true; suspend(); scene.stop() }
    private func cue() {
        guard let update = engine.tick(seconds:0.1) else { return }
        remaining = update.remaining
        if let text = update.instruction { audio.say(text,urgent:update.urgent) }
    }
}
