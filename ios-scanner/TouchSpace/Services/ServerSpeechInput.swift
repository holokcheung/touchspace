import AVFoundation
import Foundation

@MainActor protocol VoiceFileRecording: AnyObject {
    func start() throws
    func finish() throws -> Data
    func cancel()
}

/// PCM WAV is accepted directly by the existing /api/stt local-only path.
@MainActor final class MicrophoneFileRecording: VoiceFileRecording {
    private var recorder: AVAudioRecorder?
    private var file: URL?
    private var active = false
    func start() throws {
        cancel()
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playAndRecord,mode:.measurement,options:[.defaultToSpeaker])
        try session.setActive(true); active = true
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString+".wav")
        file = url
        let recorder = try AVAudioRecorder(url:url,settings:[
            AVFormatIDKey:kAudioFormatLinearPCM, AVSampleRateKey:16000,
            AVNumberOfChannelsKey:1, AVLinearPCMBitDepthKey:16,
            AVLinearPCMIsFloatKey:false, AVLinearPCMIsBigEndianKey:false])
        self.recorder = recorder
        guard recorder.prepareToRecord(), recorder.record(forDuration:60) else {
            cancel(); throw TouchSpaceError.invalid("The microphone could not start. Check Simulator audio input and Mac microphone access.")
        }
    }
    func finish() throws -> Data {
        recorder?.stop()
        defer { cancel() }
        guard let file else { throw CancellationError() }
        let audio = try Data(contentsOf:file)
        guard audio.count > 44 else { throw TouchSpaceError.invalid("No microphone audio was recorded. Check Simulator audio input and try again.") }
        return audio
    }
    func cancel() {
        recorder?.stop(); recorder = nil
        if let file { try? FileManager.default.removeItem(at:file); self.file = nil }
        if active { try? AVAudioSession.sharedInstance().setActive(false,options:.notifyOthersOnDeactivation); active = false }
    }
}

/// Simulator speech assets may target iPhone neural hardware. Record locally and
/// use the configured Mac server instead; local_only forbids cloud-provider STT.
@MainActor final class ServerSpeechInput: VoiceCapture {
    private let api: APIClient
    private let recording: VoiceFileRecording
    private let authorize: () async -> Bool
    private var generation = 0
    init(api:APIClient,recording:VoiceFileRecording? = nil,authorize:(() async -> Bool)? = nil) {
        self.api = api; self.recording = recording ?? MicrophoneFileRecording()
        self.authorize = authorize ?? { await AVAudioApplication.requestRecordPermission() }
    }
    func begin() async throws {
        cancel(); let expected = generation
        let allowed = await authorize()
        try Task.checkCancellation()
        guard expected == generation else { throw CancellationError() }
        guard allowed else { throw TouchSpaceError.invalid("Allow Microphone access for TouchSpace in Settings and on your Mac to ask by voice.") }
        do { try recording.start() } catch { recording.cancel(); throw error }
    }
    func finish() async throws -> String {
        let expected = generation, audio = try recording.finish()
        let text = try await api.transcribeLocally(audio)
        try Task.checkCancellation()
        guard expected == generation else { throw CancellationError() }
        return text
    }
    func cancel() { generation += 1; recording.cancel() }
}
