import SwiftUI

/// Owns the entire press/release lifecycle so permission prompts, interruptions and
/// stale async replies cannot accidentally start recording or speak after leaving.
@MainActor final class WalkthroughVoice: ObservableObject {
    enum Phase { case idle, preparing, listening, thinking }
    @Published private(set) var phase = Phase.idle
    @Published var error: String?
    var isBusy: Bool { phase != .idle }
    var status: String {
        switch phase {
        case .idle: return inputHint
        case .preparing: return "Preparing microphone…"
        case .listening: return "Listening · release to send"
        case .thinking: return "Thinking…"
        }
    }
    private let inputHint: String
    private let capture: VoiceCapture
    private let interrupt: () -> Void
    private let answer: (String) async throws -> String
    private let speak: (String) -> Void
    private var operation: Task<Void,Never>?
    private var maximumHold: Task<Void,Never>?
    private var held = false
    private var generation = 0

    init(capture:VoiceCapture,inputHint:String = "Hold to ask · swipe to look",interrupt:@escaping () -> Void,
         answer:@escaping (String) async throws -> String,speak:@escaping (String) -> Void) {
        self.inputHint = inputHint; self.capture = capture; self.interrupt = interrupt; self.answer = answer; self.speak = speak
    }
    func press() {
        guard !held else { return }
        cancel(); held = true; error = nil; phase = .preparing
        let expected = generation
        operation = Task {
            do {
                try await capture.begin()
                guard expected == generation, held, !Task.isCancelled else { return }
                phase = .listening
                scheduleMaximumHold()
            } catch is CancellationError { }
            catch { fail(error,expected:expected) }
        }
    }
    func release() {
        guard held else { return }
        held = false; maximumHold?.cancel(); maximumHold = nil
        // Releasing during a permission prompt must not begin recording later.
        guard phase == .listening else { cancel(); return }
        phase = .thinking
        let expected = generation
        operation = Task {
            do {
                let message = try await capture.finish().trimmingCharacters(in:.whitespacesAndNewlines)
                capture.cancel()
                try Task.checkCancellation()
                guard expected == generation else { return }
                guard !message.isEmpty else { throw TouchSpaceError.invalid("I didn't catch that. Hold the microphone and try again.") }
                let reply = try await answer(message)
                try Task.checkCancellation()
                guard expected == generation else { return }
                phase = .idle; speak(reply)
            } catch is CancellationError { }
            catch { fail(error,expected:expected) }
        }
    }
    func toggleAccessibleRecording() { if held { release() } else { press() } }
    func cancel() {
        generation += 1; held = false
        operation?.cancel(); operation = nil; maximumHold?.cancel(); maximumHold = nil
        capture.cancel(); interrupt(); phase = .idle
    }
    private func scheduleMaximumHold() {
        maximumHold = Task { [weak self] in
            do { try await Task.sleep(nanoseconds:60_000_000_000) } catch { return }
            self?.release()
        }
    }
    private func fail(_ failure:Error,expected:Int) {
        guard expected == generation else { return }
        capture.cancel(); held = false; maximumHold?.cancel(); maximumHold = nil
        error = failure.localizedDescription; phase = .idle; speak(failure.localizedDescription)
    }
}

#if DEBUG
@MainActor final class FixtureVoiceCapture: VoiceCapture {
    let text: String
    init(text:String) { self.text = text }
    func begin() async throws { }
    func finish() async throws -> String { text }
    func cancel() { }
}
#endif
