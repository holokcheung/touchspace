import AVFoundation
import Speech
import SwiftUI

/// Serial audio-session configuration runs off the UI actor.
actor AudioSessionController {
    static let shared=AudioSessionController()
    func playback() throws {
        try Task.checkCancellation()
        try AVAudioSession.sharedInstance().setCategory(.playback,mode:.default,options:[.mixWithOthers])
        try AVAudioSession.sharedInstance().setActive(true)
    }
    func configureRecording() throws {
        try AVAudioSession.sharedInstance().setCategory(.playAndRecord,mode:.default,options:[.mixWithOthers,.defaultToSpeaker])
    }
    func recording() throws {
        try Task.checkCancellation()
        try configureRecording()
        try AVAudioSession.sharedInstance().setActive(true)
    }
    func deactivate() { try? AVAudioSession.sharedInstance().setActive(false,options:.notifyOthersOnDeactivation) }
}

@MainActor final class AudioGuide: ObservableObject {
    @Published var muted=false { didSet { if muted { silence() } } }
    @Published var speechOnly=true
    @Published var cueInterval=5.0
    private let speech=AVSpeechSynthesizer()
    private let engine=AVAudioEngine()
    private let player=AVAudioPlayerNode()
    private var lastCue=Date.distantPast
    private var lastSpoken=""
    private var speechTask:Task<Void,Never>?
    private var cueTask:Task<Void,Never>?
    init() {
        engine.attach(player); engine.connect(player,to:engine.mainMixerNode,format:AVAudioFormat(standardFormatWithSampleRate:44100,channels:1))
    }
    func say(_ text:String, repeatAllowed:Bool=false) {
        guard !muted, !text.isEmpty, repeatAllowed || text != lastSpoken else { return }
        lastSpoken=text
        speechTask?.cancel()
        speechTask=Task {
          do {
            try await AudioSessionController.shared.playback()
            guard !Task.isCancelled,!muted else{return}
            speech.stopSpeaking(at:.immediate)
            // VoiceOver announces state changes through its own speech queue.
            if UIAccessibility.isVoiceOverRunning { UIAccessibility.post(notification:.announcement,argument:text) }
            else { let u=AVSpeechUtterance(string:text); u.rate=AVSpeechUtteranceDefaultSpeechRate; speech.speak(u) }
          } catch { /* Visible text remains available when audio output is unavailable. */ }
        }
    }
    func beep(pan:Float) {
        guard !muted,!speechOnly,!speech.isSpeaking,Date().timeIntervalSince(lastCue)>=cueInterval else { return }
        lastCue=Date(); cueTask?.cancel()
        cueTask=Task {
          do {
            try await AudioSessionController.shared.playback()
            guard !Task.isCancelled,!muted,!speech.isSpeaking else{return}
            if !engine.isRunning { try engine.start() }
            let format=AVAudioFormat(standardFormatWithSampleRate:44100,channels:1)!
            let count:AVAudioFrameCount=5292, buffer=AVAudioPCMBuffer(pcmFormat:format,frameCapacity:count)!
            buffer.frameLength=count
            for i in 0..<Int(count) {
                let envelope=sin(.pi*Double(i)/Double(count))
                buffer.floatChannelData![0][i]=Float(sin(2 * .pi*660*Double(i)/44100)*envelope*0.12)
            }
            player.pan=min(1,max(-1,pan)); enqueue(buffer); player.play(); lastCue=Date()
          } catch { speechOnly=true }
        }
    }
    private func enqueue(_ buffer:AVAudioPCMBuffer) { player.scheduleBuffer(buffer,completionHandler:nil) }
    func silence() { speechTask?.cancel(); cueTask?.cancel(); speech.stopSpeaking(at:.immediate); player.stop(); lastSpoken="" }
}

@MainActor final class SpeechInput: ObservableObject {
    @Published var recording=false
    @Published var transcript=""
    @Published var error:String?
    private let engine=AVAudioEngine()
    private var task:SFSpeechRecognitionTask?
    private var request:SFSpeechAudioBufferRecognitionRequest?
    private var tapInstalled=false
    private var generation=0
    func start() async {
        stop(); let ticket=generation; error=nil; transcript=""
        let status=await withCheckedContinuation { continuation in SFSpeechRecognizer.requestAuthorization { continuation.resume(returning:$0) } }
        let mic=await AVCaptureDevice.requestAccess(for:.audio)
        guard ticket==generation else{return}
        guard status == .authorized,mic else { error="Speech and microphone permission are required for dictation. You can type your question."; return }
        guard let recognizer=SFSpeechRecognizer(locale:.current),recognizer.isAvailable,recognizer.supportsOnDeviceRecognition else { error="On-device dictation is unavailable for this language or device. Type your question instead."; return }
        do {
            try await AudioSessionController.shared.recording()
            guard ticket==generation else { await AudioSessionController.shared.deactivate();return }
            let request=SFSpeechAudioBufferRecognitionRequest(); request.requiresOnDeviceRecognition=true; request.shouldReportPartialResults=true; self.request=request
            let input=engine.inputNode,format=input.outputFormat(forBus:0)
            guard format.sampleRate>0 else { throw NSError(domain:"Microphone unavailable",code:1) }
            input.installTap(onBus:0,bufferSize:1024,format:format) { buffer,_ in request.append(buffer) }; tapInstalled=true
            task=recognizer.recognitionTask(with:request) { [weak self] result,error in
                Task { @MainActor in
                    guard self?.generation==ticket else{return}
                    if let result { self?.transcript=result.bestTranscription.formattedString }
                    if error != nil || result?.isFinal==true { self?.stop() }
                }
            }
            engine.prepare(); try engine.start(); recording=true
        } catch { stop(); self.error="Dictation could not start. You can type your question." }
    }
    func stop() {
        let wasActive=recording || request != nil; generation += 1
        engine.stop(); if tapInstalled { engine.inputNode.removeTap(onBus:0); tapInstalled=false }
        request?.endAudio(); task?.cancel(); task=nil; request=nil; recording=false
        if wasActive { Task { await AudioSessionController.shared.deactivate() } }
    }
}
