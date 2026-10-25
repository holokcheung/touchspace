import XCTest
import Network

/// Exercise the app's real HTTP chat path without spending a provider budget.
private final class ChatServer {
    let listener: NWListener
    let queue = DispatchQueue(label:"touchspace.ui-test-chat")
    var port: UInt16 { listener.port!.rawValue }
    var onRequest: (([String:Any]) -> Void)?
    init() throws { listener = try NWListener(using:.tcp,on:.any) }
    func start(ready:@escaping () -> Void) {
        listener.stateUpdateHandler = { state in if case .ready = state { ready() } }
        listener.newConnectionHandler = { [weak self] connection in
            guard let self else { return }
            connection.start(queue:self.queue)
            self.receive(connection,buffer:Data())
        }
        listener.start(queue:queue)
    }
    func receive(_ connection:NWConnection,buffer:Data) {
        connection.receive(minimumIncompleteLength:1,maximumLength:65536) { [weak self] data,_,complete,error in
            guard let self, error == nil else { connection.cancel(); return }
            var buffer = buffer; buffer.append(data ?? Data())
            if let separator = buffer.range(of:Data("\r\n\r\n".utf8)),
               let headers = String(data:buffer[..<separator.lowerBound],encoding:.utf8) {
                let length = headers.components(separatedBy:"\r\n").first { $0.lowercased().hasPrefix("content-length:") }
                    .flatMap { Int($0.dropFirst("content-length:".count).trimmingCharacters(in:.whitespaces)) } ?? 0
                if buffer.count-separator.upperBound >= length {
                    let body = buffer[separator.upperBound..<separator.upperBound+length]
                    if headers.hasPrefix("POST /api/touchspace/chat "),
                       let request = try? JSONSerialization.jsonObject(with:body) as? [String:Any] {
                        self.onRequest?(request)
                        let json = #"{"answer":"Simulation route to Treatment bed.","actions":[{"type":"simulateNavigation","destinationId":"clinic-treatment"}],"providerUsed":true,"requiresLocalization":false}"#
                        let response = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: \(json.utf8.count)\r\nConnection: close\r\n\r\n" + json
                        connection.send(content:Data(response.utf8),completion:.contentProcessed { _ in connection.cancel() })
                    } else { connection.cancel() }
                    return
                }
            }
            if complete { connection.cancel() }
            else { self.receive(connection,buffer:buffer) }
        }
    }
    func stop() { listener.cancel() }
}

final class WalkthroughUITests: XCTestCase {
    var app: XCUIApplication!
    private var server: ChatServer!
    override func setUpWithError() throws {
        continueAfterFailure = false
        server = try ChatServer()
        let ready = expectation(description:"Chat test server listening")
        server.start { ready.fulfill() }
        wait(for:[ready],timeout:5)
        app = XCUIApplication()
        app.launchArguments = ["--ui-test-mute","--ui-test-voice","Could you escort me to the treatment area?","-backendURL","http://127.0.0.1:\(server.port)","-AppleLanguages","(en)","-AppleLocale","en_US"]
        app.launch()
        app.buttons["load-demo-maps"].tap()
        XCTAssertTrue(app.navigationBars["Demo spaces"].waitForExistence(timeout:5))
    }
    override func tearDownWithError() throws { app.terminate(); app = nil; server.stop(); server = nil }
    func saveScreenshot(_ name:String) throws {
        let screenshot = app.screenshot()
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(name+".png")
        try screenshot.pngRepresentation.write(to:url)
        print("SCREENSHOT_FILE: "+url.path)
        let attachment = XCTAttachment(screenshot:screenshot); attachment.name = name; attachment.lifetime = .keepAlways; add(attachment)
    }
    func reveal(_ element:XCUIElement) {
        for _ in 0..<8 {
            if element.exists {
                let frame = element.frame, height = app.frame.height
                if element.isHittable && frame.midY > 150 && frame.midY < height-130 { return }
                let travel = min(0.4,max(-0.4,(frame.midY-height*0.5)/height))
                let start = app.coordinate(withNormalizedOffset:CGVector(dx:0.5,dy:0.65))
                let end = app.coordinate(withNormalizedOffset:CGVector(dx:0.5,dy:0.65-travel))
                start.press(forDuration:0.1,thenDragTo:end)
            } else { app.swipeUp() }
        }
        XCTAssertTrue(element.isHittable)
    }
    func openWalkthrough(_ venue:String = "Harbour Community Clinic") {
        let open = app.buttons["Start 3D walkthrough of "+venue]; reveal(open); open.tap()
        XCTAssertTrue(app.buttons["simulation-forward"].waitForExistence(timeout:10))
        XCTAssertFalse(app.segmentedControls["Viewpoint"].exists)
        XCTAssertFalse(app.buttons["simulation-play"].exists)
        XCTAssertFalse(app.buttons["simulation-destinations"].exists)
        XCTAssertFalse(app.buttons["Ask"].exists)
        XCTAssertFalse(app.textFields.firstMatch.exists)
        XCTAssertFalse(app.navigationBars["3D walkthrough"].exists)
    }
    func testWalkthroughOpensInFirstPersonAndRespondsToMovementAndSwipe() throws {
        openWalkthrough()
        let look = app.otherElements["simulation-look-surface"]
        XCTAssertTrue(look.waitForExistence(timeout:5))
        let original = look.value as? String
        app.buttons["simulation-forward"].tap()
        let forward = look.value as? String; XCTAssertNotEqual(original,forward)
        app.buttons["simulation-backward"].tap()
        XCTAssertEqual(original,look.value as? String)
        let start = app.coordinate(withNormalizedOffset:CGVector(dx:0.3,dy:0.4))
        let end = app.coordinate(withNormalizedOffset:CGVector(dx:0.7,dy:0.4))
        start.press(forDuration:0.1,thenDragTo:end)
        XCTAssertNotEqual(original,look.value as? String)
        try saveScreenshot("touchspace-immersive-first-person")
        app.buttons["simulation-close"].tap()
        XCTAssertTrue(app.navigationBars["Demo spaces"].waitForExistence(timeout:5))
    }
    func testHoldToTalkSendsOnReleaseAndDrawsRequestedRouteWithoutChat() throws {
        let sent = expectation(description:"Question sent through online chat")
        server.onRequest = { request in
            XCTAssertEqual(request["message"] as? String,"Could you escort me to the treatment area?")
            XCTAssertNotNil(request["mapPackage"]); XCTAssertNotNil(request["simulatedPose"])
            XCTAssertNil(request["pose"])
            sent.fulfill()
        }
        openWalkthrough()
        app.buttons["simulation-microphone"].press(forDuration:1)
        let destination = app.staticTexts["simulation-destination"]
        XCTAssertTrue(destination.waitForExistence(timeout:10))
        wait(for:[sent],timeout:5)
        XCTAssertTrue(destination.label.contains("Treatment bed"))
        XCTAssertEqual(app.staticTexts["simulation-voice-status"].label,"Hold to ask · swipe to look")
        XCTAssertFalse(app.textFields.firstMatch.exists); XCTAssertFalse(app.textViews.firstMatch.exists)
        XCTAssertFalse(app.buttons["Play route"].exists)
        try saveScreenshot("touchspace-voice-route")
    }
    func testDemoButtonOpensChooserAgainForAlreadyLoadedMaps() throws {
        app.navigationBars["Demo spaces"].buttons.element(boundBy:0).tap()
        XCTAssertTrue(app.buttons["load-demo-maps"].waitForExistence(timeout:5))
        app.buttons["load-demo-maps"].tap()
        XCTAssertTrue(app.navigationBars["Demo spaces"].waitForExistence(timeout:5))
        openWalkthrough("Neighbourhood Library")
        try saveScreenshot("touchspace-library-first-person")
        app.buttons["simulation-close"].tap()
        XCTAssertTrue(app.navigationBars["Demo spaces"].waitForExistence(timeout:5))
    }
}
