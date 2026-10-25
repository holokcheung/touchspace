import AVFoundation
import Speech
import OSLog
import SwiftUI

@MainActor final class AudioGuidance: ObservableObject {
    enum Mode: String, CaseIterable, Identifiable { case speech = "Speech only", beacon = "Speech and beacon", mute = "Mute"; var id: String { rawValue } }
    @Published var mode = Mode.speech { didSet { if mode == .mute { stop() } } }
    private let speech = AVSpeechSynthesizer()
    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private var lastBeacon = -Double.infinity
    private(set) var lastInstruction = "Guidance is ready."
    private var lastSpoken = ""
    private var spokenAt = -Double.infinity
    init() {
        engine.attach(player)
        engine.connect(player,to:engine.mainMixerNode,format:AVAudioFormat(standardFormatWithSampleRate:44100,channels:1))
    }
    func say(_ text: String, urgent: Bool = false) {
        lastInstruction = text
        guard mode != .mute else { return }
        let now = ProcessInfo.processInfo.systemUptime
        guard urgent || text != lastSpoken || now-spokenAt > 12 else { return }
        lastSpoken = text; spokenAt = now
        player.stop()
        if urgent { speech.stopSpeaking(at:.immediate) }
        else if speech.isSpeaking { speech.stopSpeaking(at:.word) }
        try? AVAudioSession.sharedInstance().setCategory(.playback,mode:.spokenAudio,options:[.mixWithOthers])
        try? AVAudioSession.sharedInstance().setActive(true)
        let utterance = AVSpeechUtterance(string:text); utterance.rate = AVSpeechUtteranceDefaultSpeechRate
        speech.speak(utterance)
    }
    func repeatLast() { say(lastInstruction,urgent:true) }
    func stop() { speech.stopSpeaking(at:.immediate); player.stop(); engine.pause() }
    func beacon(relativeBearing: Double) {
        let now = ProcessInfo.processInfo.systemUptime
        guard mode == .beacon, !speech.isSpeaking, now-lastBeacon >= 2 else { return }
        lastBeacon = now
        let format = AVAudioFormat(standardFormatWithSampleRate:44100,channels:1)!
        let frames = AVAudioFrameCount(44100*0.07)
        guard let buffer = AVAudioPCMBuffer(pcmFormat:format,frameCapacity:frames), let samples = buffer.floatChannelData?[0] else { return }
        buffer.frameLength = frames
        for i in 0..<Int(frames) {
            let phase = Double(i)/Double(frames)
            samples[i] = Float(sin(2*Double.pi*880*Double(i)/44100)*sin(Double.pi*phase)*0.12)
        }
        player.pan = Float(sin(relativeBearing))
        if !engine.isRunning { try? engine.start() }
        player.scheduleBuffer(buffer); player.play()
    }
}

/// Releasing a hold ends audio, then waits briefly for the recognizer's final words.
@MainActor protocol VoiceCapture: AnyObject {
    func begin() async throws
    func finish() async throws -> String
    func cancel()
}

/// Capture and recognition have separate lifetimes. Releasing the button stops
/// input, while the audio session stays active until Apple's final result arrives.
@MainActor protocol SpeechAudioSource: AnyObject {
    func start(append:@escaping (AVAudioPCMBuffer) -> Void) throws
    func stop()
    func deactivate()
}

@MainActor final class MicrophoneAudioSource: SpeechAudioSource {
    private let engine = AVAudioEngine()
    private var tapInstalled = false
    private var active = false
    func start(append:@escaping (AVAudioPCMBuffer) -> Void) throws {
        try AVAudioSession.sharedInstance().setCategory(.playAndRecord,mode:.measurement,options:[.defaultToSpeaker])
        try AVAudioSession.sharedInstance().setActive(true); active = true
        let input = engine.inputNode, format = input.outputFormat(forBus:0)
        guard format.sampleRate > 0, format.channelCount > 0 else {
            throw TouchSpaceError.invalid("No microphone input is available on this device.")
        }
        input.installTap(onBus:0,bufferSize:1024,format:format) { buffer,_ in append(buffer) }
        tapInstalled = true
        engine.prepare(); try engine.start()
    }
    func stop() {
        engine.stop()
        if tapInstalled { engine.inputNode.removeTap(onBus:0); tapInstalled = false }
    }
    func deactivate() {
        guard active else { return }
        try? AVAudioSession.sharedInstance().setActive(false,options:.notifyOthersOnDeactivation)
        active = false
    }
}

enum SpeechFailure {
    static func message(_ error:Error?) -> String {
        let failure = error as NSError?
        switch (failure?.domain,failure?.code) {
        case ("kLSRErrorDomain",102), ("kLSRErrorDomain",300):
            #if targetEnvironment(simulator)
            return "The simulator's speech model could not load. Use the walkthrough’s local-server voice input instead; this runtime’s model targets iPhone hardware."
            #else
            return "The on-device speech model could not load. Enable Dictation and download a speech language in Settings, then try again."
            #endif
        case ("kLSRErrorDomain",201):
            return "Dictation is disabled. Enable Dictation in Settings to use voice questions."
        case ("kAFAssistantErrorDomain",1700):
            return "Allow Speech Recognition for TouchSpace in Settings to ask by voice."
        case ("kAFAssistantErrorDomain",1101), ("kAFAssistantErrorDomain",1107):
            return "The on-device speech service disconnected. Reopen TouchSpace and try again."
        case ("kAFAssistantErrorDomain",1110), (nil,_):
            return "I didn't hear any speech. Check the microphone input, then hold while speaking and release to send."
        default:
            return "Speech recognition could not finish. Check the microphone input and speech language, then try again."
        }
    }
}

@MainActor final class SpeechInput: ObservableObject, VoiceCapture {
    @Published private(set) var recording = false
    @Published private(set) var transcript = ""
    @Published var error: String?
    private let source: SpeechAudioSource
    private let authorize: () async throws -> Void
    private let finalizationTimeout: UInt64
    private let log = Logger(subsystem:"ai.touchspace.TouchSpace",category:"SpeechInput")
    private var recognizer: SFSpeechRecognizer?
    private var task: SFSpeechRecognitionTask?
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var generation = 0
    private var finalized = false
    private var recognitionError: Error?
    private var completion: CheckedContinuation<String,Error>?
    private var finalTimeout: Task<Void,Never>?

    init(source:SpeechAudioSource? = nil,
         finalizationTimeout:UInt64 = 8_000_000_000,
         authorize:(() async throws -> Void)? = nil) {
        self.source = source ?? MicrophoneAudioSource(); self.finalizationTimeout = finalizationTimeout
        self.authorize = authorize ?? Self.requestPermissions
    }
    private static func requestPermissions() async throws {
        let permission = await withCheckedContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { continuation.resume(returning:$0) }
        }
        try Task.checkCancellation()
        guard permission == .authorized else {
            throw TouchSpaceError.invalid("Allow Speech Recognition for TouchSpace in Settings to ask by voice.")
        }
        let microphone = await AVAudioApplication.requestRecordPermission()
        try Task.checkCancellation()
        guard microphone else {
            throw TouchSpaceError.invalid("Allow Microphone access for TouchSpace in Settings to ask by voice.")
        }
    }

    // Retained for the saved-floor-plan question sheet.
    func start() async {
        do { try await begin() }
        catch is CancellationError { }
        catch { self.error = error.localizedDescription }
    }
    func stop() { cancel() }

    func begin() async throws {
        cancel(); error = nil; transcript = ""; finalized = false; recognitionError = nil
        let expected = generation
        try await authorize()
        try Task.checkCancellation()
        guard expected == generation else { throw CancellationError() }
        guard let recognizer = SFSpeechRecognizer(), recognizer.isAvailable, recognizer.supportsOnDeviceRecognition else {
            throw TouchSpaceError.invalid("On-device speech recognition is unavailable. Check that a speech language is downloaded on this device, then try again.")
        }
        self.recognizer = recognizer
        let request = SFSpeechAudioBufferRecognitionRequest()
        request.requiresOnDeviceRecognition = true; request.shouldReportPartialResults = true
        request.taskHint = .search
        self.request = request
        task = recognizer.recognitionTask(with:request) { [weak self] result,error in
            Task { @MainActor in
                guard let self, expected == self.generation else { return }
                if let result { self.transcript = result.bestTranscription.formattedString }
                if let error {
                    let failure = error as NSError
                    // Only diagnostic metadata; never log audio, questions or transcripts.
                    self.log.error("Recognition failed: domain=\(failure.domain,privacy:.public) code=\(failure.code)")
                }
                if result?.isFinal == true || error != nil {
                    self.finalized = true; self.recognitionError = error
                    self.stopCapture(); self.complete()
                }
            }
        }
        do {
            try source.start { buffer in request.append(buffer) }
            recording = true
        } catch {
            cancel(); throw error
        }
    }

    func finish() async throws -> String {
        stopCapture()
        if finalized { let result = Result { try recognizedText() }; cancel(); return try result.get() }
        guard task != nil else { throw CancellationError() }
        return try await withCheckedThrowingContinuation { continuation in
            completion = continuation
            // Register completion before signalling end-of-input. Do not deactivate
            // the session or cancel the task until its final words have been delivered.
            request?.endAudio(); task?.finish()
            let timeout = finalizationTimeout
            finalTimeout = Task { [weak self] in
                do { try await Task.sleep(nanoseconds:timeout) } catch { return }
                self?.complete()
            }
        }
    }
    func cancel() {
        generation += 1
        finalTimeout?.cancel(); finalTimeout = nil
        let pending = completion; completion = nil
        stopCapture(); request?.endAudio(); task?.cancel(); task = nil; request = nil; recognizer = nil
        source.deactivate()
        pending?.resume(throwing:CancellationError())
    }
    private func stopCapture() { source.stop(); recording = false }
    private func recognizedText() throws -> String {
        let text = transcript.trimmingCharacters(in:.whitespacesAndNewlines)
        guard !text.isEmpty else { throw TouchSpaceError.invalid(SpeechFailure.message(recognitionError)) }
        return text
    }
    private func complete() {
        guard let completion else { return }
        self.completion = nil; finalTimeout?.cancel(); finalTimeout = nil
        let result = Result { try recognizedText() }
        // Ignore any callback queued by cancellation before starting spoken playback.
        generation += 1; stopCapture(); task?.cancel(); task = nil; request = nil; recognizer = nil
        source.deactivate()
        completion.resume(with:result)
    }
}
