import AVFoundation
import Speech
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

@MainActor final class SpeechInput: ObservableObject {
    @Published var recording = false
    @Published var transcript = ""
    @Published var error: String?
    private let engine = AVAudioEngine()
    private var task: SFSpeechRecognitionTask?
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var tapInstalled = false
    func start() async {
        error = nil
        let speechPermission = await withCheckedContinuation { continuation in SFSpeechRecognizer.requestAuthorization { continuation.resume(returning:$0) } }
        let micPermission = await AVAudioApplication.requestRecordPermission()
        guard speechPermission == .authorized, micPermission else { error = "Microphone or speech permission was declined. Type your question instead."; return }
        guard let recognizer = SFSpeechRecognizer(), recognizer.isAvailable, recognizer.supportsOnDeviceRecognition else { error = "On-device recognition is unavailable. Type your question instead."; return }
        do {
            stop(); transcript = ""
            try AVAudioSession.sharedInstance().setCategory(.playAndRecord,mode:.measurement,options:[.defaultToSpeaker,.mixWithOthers])
            try AVAudioSession.sharedInstance().setActive(true)
            let request = SFSpeechAudioBufferRecognitionRequest(); request.requiresOnDeviceRecognition = true
            self.request = request
            let input = engine.inputNode
            let format = input.outputFormat(forBus:0)
            input.installTap(onBus:0,bufferSize:1024,format:format) { buffer,_ in request.append(buffer) }
            tapInstalled = true
            task = recognizer.recognitionTask(with:request) { [weak self] result,error in
                Task { @MainActor in
                    if let result { self?.transcript = result.bestTranscription.formattedString }
                    if result?.isFinal == true || error != nil { self?.stop() }
                }
            }
            engine.prepare(); try engine.start(); recording = true
        } catch { stop(); self.error = "Voice input could not start. Type your question instead." }
    }
    func stop() {
        engine.stop()
        if tapInstalled { engine.inputNode.removeTap(onBus:0); tapInstalled = false }
        request?.endAudio(); task?.cancel(); task = nil; request = nil; recording = false
    }
}
