#if !SWIFT_PACKAGE
import XCTest
@testable import TouchSpace

final class ChatURLProtocol: URLProtocol {
    static var handler: ((URLRequest) throws -> (Int,[String:Any]))?
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        do {
            let (status,body) = try Self.handler!(request)
            let response = HTTPURLResponse(url:request.url!,statusCode:status,httpVersion:nil,headerFields:["Content-Type":"application/json"])!
            client?.urlProtocol(self,didReceive:response,cacheStoragePolicy:.notAllowed)
            client?.urlProtocol(self,didLoad:try JSONSerialization.data(withJSONObject:body))
            client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self,didFailWithError:error) }
    }
    override func stopLoading() { }
    static func api(_ handler:@escaping (URLRequest) throws -> (Int,[String:Any])) -> APIClient {
        self.handler = handler
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [ChatURLProtocol.self]
        return APIClient(baseURL:URL(string:"https://chat.test")!,session:URLSession(configuration:configuration))
    }
    static func body(_ request:URLRequest) throws -> [String:Any] {
        var data = request.httpBody ?? Data()
        if let stream = request.httpBodyStream {
            stream.open(); defer { stream.close() }
            var buffer = [UInt8](repeating:0,count:4096)
            while stream.hasBytesAvailable {
                let count = stream.read(&buffer,maxLength:buffer.count)
                if count <= 0 { break }
                data.append(contentsOf:buffer.prefix(count))
            }
        }
        return try XCTUnwrap(JSONSerialization.jsonObject(with:data) as? [String:Any])
    }
}

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
        var requests: [[String:Any]] = []
        let api = ChatURLProtocol.api { request in
            XCTAssertEqual(request.url?.path,"/api/touchspace/chat")
            XCTAssertEqual(request.httpMethod,"POST")
            let body = try ChatURLProtocol.body(request); requests.append(body)
            XCTAssertNotNil(body["mapPackage"]); XCTAssertNil(body["pose"])
            XCTAssertNotNil(body["simulatedPose"])
            let destination = requests.count == 1 ? "clinic-treatment" : "clinic-supplies"
            return (200,["answer":"Simulation route to Treatment bed.","actions":[["type":"simulateNavigation","destinationId":destination]],"providerUsed":true,"requiresLocalization":false])
        }
        let session = try SimulationSession(package:package,api:api); session.audio.mode = .mute
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
        XCTAssertEqual(requests.count,2)
        XCTAssertEqual(requests[0]["sessionId"] as? String,requests[1]["sessionId"] as? String)
        let virtual = try XCTUnwrap(requests[0]["simulatedPose"] as? [String:Any])
        let point = try XCTUnwrap(virtual["position"] as? [String:Double])
        XCTAssertEqual(point["x"],start.position.x); XCTAssertEqual(point["z"],start.position.z)
        session.stop()
    }
    func testOnlineFailureDoesNotFallBackToKeywordAnswers() async throws {
        let package = try SimulationTests().package("harbour-clinic")
        for status in [503, 401] {
            let api = ChatURLProtocol.api { _ in (status,["detail":"Map chat unavailable."]) }
            let session = try SimulationSession(package:package,api:api)
            do { _ = try await session.answer("Where is Reception desk?"); XCTFail("Must report the online error") }
            catch { XCTAssertTrue(error.localizedDescription.contains("Map chat unavailable")) }
            XCTAssertNil(session.engine.route)
            session.stop()
        }
        let api = ChatURLProtocol.api { _ in throw URLError(.notConnectedToInternet) }
        let session = try SimulationSession(package:package,api:api)
        do { _ = try await session.answer("Where is Reception desk?"); XCTFail("Must report network failure") }
        catch { XCTAssertTrue(error.localizedDescription.contains("Cannot reach map chat")) }
        session.stop()
    }
    func testWalkthroughIgnoresPhysicalNavigationActions() async throws {
        let package = try SimulationTests().package("harbour-clinic")
        let api = ChatURLProtocol.api { _ in
            (200,["answer":"A reply.","actions":[["type":"navigate","destinationId":"clinic-treatment"]],"providerUsed":true,"requiresLocalization":false])
        }
        let session = try SimulationSession(package:package,api:api)
        _ = try await session.answer("Show me the treatment area")
        XCTAssertNil(session.engine.route)
        session.stop()
    }

}
#endif
