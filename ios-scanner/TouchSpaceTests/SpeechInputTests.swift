#if !SWIFT_PACKAGE
import AVFoundation
import Speech
import XCTest
@testable import TouchSpace

@MainActor final class SpeechInputTests: XCTestCase {
    func testSpeechErrorsDescribeTheActualCause() {
        let assets = NSError(domain:"kLSRErrorDomain",code:102)
        let initialization = NSError(domain:"kLSRErrorDomain",code:300)
        XCTAssertTrue(SpeechFailure.message(assets).contains("speech model"))
        XCTAssertTrue(SpeechFailure.message(initialization).contains("speech model"))
        let silence = NSError(domain:"kAFAssistantErrorDomain",code:1110)
        XCTAssertTrue(SpeechFailure.message(silence).contains("didn't hear any speech"))
        let disconnected = NSError(domain:"kAFAssistantErrorDomain",code:1107)
        XCTAssertTrue(SpeechFailure.message(disconnected).contains("disconnected"))
        XCTAssertFalse(SpeechFailure.message(assets).contains("hold the microphone and try again"))
    }
}

@MainActor final class ServerSpeechInputTests: XCTestCase {
    final class Recording: VoiceFileRecording {
        var starts = 0
        func start() throws { starts += 1 }
        func finish() throws -> Data { Data() }
        func cancel() { }
    }
    func testCancelledPermissionRequestNeverStartsRecording() async throws {
        let recording = Recording()
        var permission: CheckedContinuation<Bool,Never>?
        let capture = ServerSpeechInput(api:APIClient(baseURL:URL(string:"http://localhost:8000")!),recording:recording,authorize:{ await withCheckedContinuation { permission = $0 } })
        let operation = Task { try await capture.begin() }
        while permission == nil { await Task.yield() }
        capture.cancel(); permission?.resume(returning:true)
        do { try await operation.value; XCTFail("Cancelled hold must not start recording") }
        catch is CancellationError { }
        XCTAssertEqual(recording.starts,0)
    }
    func testDeniedMicrophonePermissionExplainsHowToRecover() async throws {
        let recording = Recording()
        let capture = ServerSpeechInput(api:APIClient(baseURL:URL(string:"http://localhost:8000")!),recording:recording,authorize:{false})
        do { try await capture.begin(); XCTFail("Permission should be required") }
        catch { XCTAssertTrue(error.localizedDescription.contains("Allow Microphone access")) }
        XCTAssertEqual(recording.starts,0)
    }
}

/// Opt in with TOUCHSPACE_SPEECH_INTEGRATION=1 in the test process. Unlike the
/// walkthrough UI tests, this runs Apple's actual on-device recognition model.
@MainActor final class SpeechRecognitionIntegrationTests: XCTestCase {
    final class RecordedAudio: SpeechAudioSource {
        let url: URL
        var stopped = false
        var released = false
        var verifyRelease: (() -> Void)?
        init(url:URL) { self.url = url }
        func start(append:@escaping (AVAudioPCMBuffer) -> Void) throws {
            stopped = false; released = false
            let file = try AVAudioFile(forReading:url)
            guard let buffer = AVAudioPCMBuffer(pcmFormat:file.processingFormat,frameCapacity:AVAudioFrameCount(file.length)) else {
                throw TouchSpaceError.invalid("Could not allocate fixture audio")
            }
            try file.read(into:buffer)
            append(buffer)
        }
        func stop() { stopped = true }
        func deactivate() { if !released { verifyRelease?() }; released = true }
    }
    func testRealSpokenQuestionFinalizesOnReleaseAndCanBeAskedTwice() async throws {
        try XCTSkipUnless(ProcessInfo.processInfo.environment["TOUCHSPACE_SPEECH_INTEGRATION"] == "1","Requires installed Apple speech assets; enable the real-speech integration run")
        XCTAssertEqual(SFSpeechRecognizer.authorizationStatus(),.authorized,"Grant Speech Recognition to TouchSpace before the integration run")
        let url = try XCTUnwrap(Bundle(for:Self.self).url(forResource:"reception-question",withExtension:"wav"))
        let source = RecordedAudio(url:url)
        let input = SpeechInput(source:source,finalizationTimeout:20_000_000_000,authorize:{})
        for _ in 0..<2 {
            source.verifyRelease = nil
            try await input.begin()
            XCTAssertTrue(input.recording)
            source.verifyRelease = {
                XCTAssertFalse(input.recording)
                XCTAssertTrue(input.transcript.lowercased().contains("reception"),"The audio session must survive until the recognizer returns the question")
            }
            let text = try await input.finish()
            XCTAssertTrue(text.lowercased().contains("reception"))
            XCTAssertTrue(text.lowercased().contains("desk"))
            XCTAssertFalse(input.recording); XCTAssertTrue(source.stopped); XCTAssertTrue(source.released)
        }
        source.verifyRelease = nil; input.cancel()
    }
}
@MainActor final class ServerSpeechRecognitionIntegrationTests: XCTestCase {
    final class RecordedQuestion: VoiceFileRecording {
        let audio: Data
        init(audio:Data) { self.audio = audio }
        func start() throws { }
        func finish() throws -> Data { audio }
        func cancel() { }
    }
    func testRealAudioReachesLocalWhisperAndProducesSpokenMapAnswersTwice() async throws {
        try XCTSkipUnless(ProcessInfo.processInfo.environment["TOUCHSPACE_SPEECH_INTEGRATION"] == "1","Requires local backend and Whisper model")
        let url = try XCTUnwrap(Bundle(for:Self.self).url(forResource:"reception-question",withExtension:"wav"))
        let recording = RecordedQuestion(audio:try Data(contentsOf:url))
        let capture = ServerSpeechInput(api:APIClient(baseURL:URL(string:"http://localhost:8000")!),recording:recording,authorize:{true})
        let package = try SimulationTests().package("harbour-clinic")
        let audio = AudioGuidance(); audio.mode = .mute
        let conversation = UUID()
        let voice = WalkthroughVoice(capture:capture,interrupt:{audio.stop()},answer:{ message in
            XCTAssertTrue(message.lowercased().contains("reception desk"))
            return try await APIClient(baseURL:URL(string:"http://localhost:8000")!).ask(package:package,session:conversation,message:message).answer
        },speak:{audio.say($0,urgent:true)})
        for _ in 0..<2 {
            voice.press()
            try await settle { voice.phase == .listening || voice.error != nil }
            XCTAssertNil(voice.error)
            voice.release()
            try await settle { voice.phase == .idle }
            XCTAssertNil(voice.error)
            XCTAssertTrue(audio.lastInstruction.contains("Reception desk is in Reception and waiting"))
        }
        voice.cancel()
    }
    private func settle(_ condition:() -> Bool) async throws {
        for _ in 0..<1000 {
            if condition() { return }
            try await Task.sleep(nanoseconds:20_000_000)
        }
        XCTFail("Timed out waiting for real local transcription")
    }
}
#endif
