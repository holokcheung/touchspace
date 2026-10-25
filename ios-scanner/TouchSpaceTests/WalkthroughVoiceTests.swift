#if !SWIFT_PACKAGE
import XCTest
@testable import TouchSpace

@MainActor final class WalkthroughVoiceTests: XCTestCase {
    final class Capture: VoiceCapture {
        var beginCount = 0, cancelCount = 0
        var delayBegin = false, delayFinish = false
        var text = "Where is Reception desk?"
        var failure: Error?
        var beginCompletion: CheckedContinuation<Void,Error>?
        var finishCompletion: CheckedContinuation<String,Error>?
        func begin() async throws {
            beginCount += 1
            if let failure { throw failure }
            if delayBegin { try await withCheckedThrowingContinuation { beginCompletion = $0 } }
        }
        func finish() async throws -> String {
            if delayFinish { return try await withCheckedThrowingContinuation { finishCompletion = $0 } }
            return text
        }
        // Authorization dialogs cannot be dismissed by cancel; deliberately complete them later.
        func cancel() { cancelCount += 1 }
    }
    func settle(_ predicate:() -> Bool,file:StaticString = #filePath,line:UInt = #line) async throws {
        for _ in 0..<2000 {
            if predicate() { return }
            try await Task.sleep(nanoseconds:5_000_000)
        }
        XCTFail("Voice operation did not reach expected state",file:file,line:line)
    }
    func testReleaseWaitsForFinalTranscriptionThenSpeaksReplyExactlyOnce() async throws {
        let capture = Capture(); capture.delayFinish = true
        var messages: [String] = [], spoken: [String] = [], interruptions = 0
        let voice = WalkthroughVoice(capture:capture,interrupt:{ interruptions += 1 },answer:{ messages.append($0); return "Reception is ahead." },speak:{ spoken.append($0) })
        voice.press(); voice.press()
        try await settle { voice.phase == .listening }
        XCTAssertEqual(capture.beginCount,1); XCTAssertEqual(interruptions,1)
        XCTAssertTrue(messages.isEmpty)
        voice.release(); voice.release()
        try await settle { capture.finishCompletion != nil }
        XCTAssertEqual(voice.phase,.thinking); XCTAssertTrue(messages.isEmpty)
        capture.finishCompletion?.resume(returning:"Where is Reception desk?"); capture.finishCompletion = nil
        try await settle { voice.phase == .idle }
        XCTAssertEqual(messages,["Where is Reception desk?"]); XCTAssertEqual(spoken,["Reception is ahead."])
        XCTAssertGreaterThanOrEqual(capture.cancelCount,2)
    }
    func testReleaseDuringPermissionPromptDoesNotRecordOrSendLater() async throws {
        let capture = Capture(); capture.delayBegin = true
        var sent = false, spoke = false
        let voice = WalkthroughVoice(capture:capture,interrupt:{},answer:{ _ in sent = true; return "reply" },speak:{ _ in spoke = true })
        voice.press()
        try await settle { capture.beginCompletion != nil }
        voice.release(); XCTAssertEqual(voice.phase,.idle)
        capture.beginCompletion?.resume(); capture.beginCompletion = nil
        await Task.yield(); await Task.yield()
        XCTAssertEqual(voice.phase,.idle); XCTAssertFalse(sent); XCTAssertFalse(spoke)
    }
    func testLeavingOrStartingAnotherHoldDiscardsAnOldReply() async throws {
        let capture = Capture()
        var pending: CheckedContinuation<String,Never>?
        var spoken: [String] = []
        let voice = WalkthroughVoice(capture:capture,interrupt:{},answer:{ _ in await withCheckedContinuation { pending = $0 } },speak:{ spoken.append($0) })
        voice.press(); try await settle { voice.phase == .listening }; voice.release()
        try await settle { pending != nil }
        voice.cancel()
        voice.press(); try await settle { voice.phase == .listening }
        pending?.resume(returning:"Outdated answer"); pending = nil
        await Task.yield(); await Task.yield()
        XCTAssertTrue(spoken.isEmpty); XCTAssertEqual(voice.phase,.listening)
        voice.cancel()
    }
    func testEmptySpeechAndDeniedPermissionHaveSpokenErrorsAndCanRetry() async throws {
        let capture = Capture(); capture.text = "  "
        var spoken: [String] = []
        let voice = WalkthroughVoice(capture:capture,interrupt:{},answer:{ _ in XCTFail("Empty speech must not be sent"); return "" },speak:{ spoken.append($0) })
        voice.press(); try await settle { voice.phase == .listening }; voice.release()
        try await settle { voice.error != nil }
        XCTAssertEqual(voice.phase,.idle); XCTAssertTrue(spoken.last?.contains("didn't catch") == true)
        capture.failure = TouchSpaceError.invalid("Microphone access is declined.")
        voice.press(); try await settle { voice.error?.contains("declined") == true }
        XCTAssertEqual(spoken.last,"Microphone access is declined.")
        capture.failure = nil
        voice.toggleAccessibleRecording(); try await settle { voice.phase == .listening }
        voice.cancel(); XCTAssertEqual(voice.phase,.idle)
    }
    func testSpokenNavigationUsesCurrentVirtualPoseAndNeverStartsAutoplay() async throws {
        let package = try SimulationTests().package("harbour-clinic")
        let session = try SimulationSession(package:package); session.audio.mode = .mute
        session.start(initialDestination:nil)
        XCTAssertNil(session.engine.route)
        session.move(0.5)
        let start = session.engine.pose
        let capture = Capture(); capture.text = "Take me to Treatment bed"
        let voice = WalkthroughVoice(capture:capture,interrupt:{ session.audio.stop() },answer:{ try await session.answer($0) },speak:{ session.audio.say($0,urgent:true) })
        voice.toggleAccessibleRecording(); try await settle { voice.phase == .listening }
        voice.toggleAccessibleRecording(); try await settle { voice.phase == .idle }
        XCTAssertEqual(session.destination?.id,"clinic-treatment")
        XCTAssertEqual(session.engine.route?.waypoints.first,start.position)
        XCTAssertEqual(session.engine.pose,start); XCTAssertFalse(session.engine.following)
        XCTAssertTrue(session.audio.lastInstruction.contains("Simulation route to Treatment bed"))
        do { _ = try await session.answer("Take me to Staff supplies"); XCTFail("Unknown door must refuse navigation") }
        catch { XCTAssertTrue(error.localizedDescription.contains("No validated route")) }
        XCTAssertNil(session.engine.route); XCTAssertNil(session.destination)
        session.stop()
    }
}
#endif
