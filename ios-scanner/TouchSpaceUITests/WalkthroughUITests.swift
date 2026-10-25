import XCTest

final class WalkthroughUITests: XCTestCase {
    var app: XCUIApplication!
    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments = ["--ui-test-mute","--ui-test-voice","Take me to Treatment bed","-AppleLanguages","(en)","-AppleLocale","en_US"]
        app.launch()
        app.buttons["load-demo-maps"].tap()
        XCTAssertTrue(app.navigationBars["Demo spaces"].waitForExistence(timeout:5))
    }
    override func tearDownWithError() throws { app.terminate(); app = nil }
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
        openWalkthrough()
        app.buttons["simulation-microphone"].press(forDuration:1)
        let destination = app.staticTexts["simulation-destination"]
        XCTAssertTrue(destination.waitForExistence(timeout:10))
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
