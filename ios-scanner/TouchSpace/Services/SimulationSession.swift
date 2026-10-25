import SwiftUI

@MainActor final class SimulationSession: ObservableObject {
    let package: MapPackage
    let scene: VirtualMapScene
    let audio = AudioGuidance()
    @Published private(set) var engine: SimulationEngine
    @Published var viewpoint = VirtualMapScene.Viewpoint.overview
    @Published var planning = false
    @Published var remaining = 0.0
    @Published var instruction = "Choose a destination, then play the route or use the movement controls."
    @Published var error: String?
    private var timer: Timer?
    private var generation = 0
    private var lastTick = 0.0
    private var stopped = false
    var destination: Landmark? { package.landmarks.landmarks.first { $0.id == engine.destinationId } }
    init(package:MapPackage) throws {
        self.package = package; engine = try SimulationEngine(package:package); scene = try VirtualMapScene(package:package)
        if ProcessInfo.processInfo.arguments.contains("--ui-test-mute") { audio.mode = .mute }
    }
    func start(initialDestination:String?) {
        stopped = false; lastTick = ProcessInfo.processInfo.systemUptime
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval:0.1,repeats:true) { [weak self] _ in Task { @MainActor in self?.tick() } }
        if engine.route == nil {
            let target = initialDestination ?? package.landmarks.landmarks.first { $0.position.distance(to:engine.pose.position) > 0.5 }?.id
            if let target { plan(to:target) }
        }
    }
    func plan(to id:String) {
        generation += 1; let expected = generation
        engine.clearRoute(); audio.stop(); planning = true; remaining = 0
        var candidate = engine
        Task {
            do {
                candidate = try await Task.detached(priority:.userInitiated) { var copy = try SimulationEngine(package:candidate.package,currentPose:candidate.pose); try copy.plan(to:id); return copy }.value
                guard expected == generation && !stopped else { return }
                engine = candidate; planning = false; remaining = candidate.route?.distance ?? 0
                instruction = "Simulation route to \(destination?.name ?? "destination"), \(String(format:"%.1f",remaining)) metres. Press Play route to walk it."
                audio.say(instruction,urgent:true)
            } catch {
                guard expected == generation && !stopped else { return }
                planning = false; engine.pause(); self.error = error.localizedDescription
                instruction = "No simulation route: \(error.localizedDescription)"; audio.say(instruction,urgent:true)
            }
        }
    }
    func togglePlayback() {
        if engine.following { pause() }
        else {
            guard engine.destinationId != nil else { error = "Choose a destination first."; return }
            do { try engine.follow(); viewpoint = .walk; instruction = "Playing simulated route."; audio.say(instruction,urgent:true) }
            catch { self.error = error.localizedDescription }
        }
    }
    func pause() { engine.pause(); audio.stop(); instruction = "Simulation paused. Look around, ask a question, or resume with Play route." }
    func move(_ metres:Double) {
        guard !planning else { return }
        audio.stop()
        if engine.move(metres) { instruction = "Virtual position updated."; cue(engine.tick(seconds:0.1)) }
        else { instruction = "Step blocked by furniture, a wall, an unconfirmed doorway or unknown floor."; audio.say(instruction,urgent:true) }
    }
    func turn(_ radians:Double) { guard !planning else { return }; engine.turn(radians); cue(engine.tick(seconds:0.1)) }
    func reset() {
        generation += 1; planning = false; engine.reset(); audio.stop(); remaining = 0; viewpoint = .overview
        instruction = "Simulation reset to the saved entrance. Choose a destination."
    }
    func stop() { stopped = true; generation += 1; timer?.invalidate(); timer = nil; engine.pause(); audio.stop(); scene.stop() }
    private func tick() {
        let now = ProcessInfo.processInfo.systemUptime, delta = now-lastTick; lastTick = now
        guard !planning, !stopped, engine.following else { return }
        cue(engine.tick(seconds:delta))
    }
    private func cue(_ update:GuidanceUpdate?) {
        guard let update else { return }
        remaining = update.remaining
        if let text = update.instruction { instruction = "Simulation: "+text; audio.say(instruction,urgent:update.urgent) }
        if engine.following { audio.beacon(relativeBearing:engine.spatial.relativeBearing(from:engine.pose.position,heading:engine.pose.heading,to:update.waypoint)) }
    }
}
