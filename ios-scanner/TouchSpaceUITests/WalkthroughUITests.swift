import XCTest

final class WalkthroughUITests: XCTestCase {
    var app: XCUIApplication!
    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments = ["--ui-test-mute","-AppleLanguages","(en)","-AppleLocale","en_US"]
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
    func testExploreAndPlayThreeDimensionalRoute() throws {
        let explore = app.buttons["Explore map of Harbour Community Clinic"]; reveal(explore); explore.tap()
        let preview = app.staticTexts["route-preview-status"]
        XCTAssertTrue(preview.waitForExistence(timeout:5))
        let planned = XCTNSPredicateExpectation(predicate:NSPredicate(format:"label CONTAINS %@","Route preview:"),object:preview)
        XCTAssertEqual(XCTWaiter.wait(for:[planned],timeout:10),.completed)
        let open = app.buttons["open-walkthrough"]; reveal(open); open.tap()
        let play = app.buttons["simulation-play"]
        XCTAssertTrue(play.waitForExistence(timeout:10))
        let ready = XCTNSPredicateExpectation(predicate:NSPredicate(format:"enabled == true"),object:play)
        XCTAssertEqual(XCTWaiter.wait(for:[ready],timeout:10),.completed)
        try saveScreenshot("touchspace-overview")
        let initial = app.staticTexts["simulation-destination"].label
        play.tap()
        let moved = XCTNSPredicateExpectation(predicate:NSPredicate(format:"label != %@",initial),object:app.staticTexts["simulation-destination"])
        XCTAssertEqual(XCTWaiter.wait(for:[moved],timeout:10),.completed)
        XCTAssertEqual(play.label,"Pause")
        try saveScreenshot("touchspace-first-person")
        play.tap(); XCTAssertEqual(play.label,"Play route")
        app.buttons["simulation-destinations"].tap()
        app.buttons["Staff supplies"].tap()
        XCTAssertTrue(app.alerts["Simulation route"].waitForExistence(timeout:10))
        XCTAssertTrue(app.alerts.staticTexts.matching(NSPredicate(format:"label CONTAINS %@","No validated route")).firstMatch.exists)
        app.alerts.buttons["OK"].tap()
        XCTAssertTrue(app.staticTexts["simulation-destination"].label.contains("No destination"))
    }
    func testDemoButtonOpensChooserAgainForAlreadyLoadedMaps() throws {
        app.navigationBars["Demo spaces"].buttons.element(boundBy:0).tap()
        XCTAssertTrue(app.buttons["load-demo-maps"].waitForExistence(timeout:5))
        app.buttons["load-demo-maps"].tap()
        XCTAssertTrue(app.navigationBars["Demo spaces"].waitForExistence(timeout:5))
        try saveScreenshot("touchspace-demo-chooser")
        let library = app.buttons["Start 3D walkthrough of Neighbourhood Library"]
        reveal(library); library.tap()
        let play = app.buttons["simulation-play"]
        XCTAssertTrue(play.waitForExistence(timeout:10))
        let ready = XCTNSPredicateExpectation(predicate:NSPredicate(format:"enabled == true"),object:play)
        XCTAssertEqual(XCTWaiter.wait(for:[ready],timeout:10),.completed)
        try saveScreenshot("touchspace-library-walkthrough")
        let initial = app.staticTexts["simulation-destination"].label
        play.tap()
        let moved = XCTNSPredicateExpectation(predicate:NSPredicate(format:"label != %@",initial),object:app.staticTexts["simulation-destination"])
        XCTAssertEqual(XCTWaiter.wait(for:[moved],timeout:10),.completed)
    }
    func testMockQuestionsWorkLocallyWithoutCatalogUpload() throws {
        let explore = app.buttons["Explore map of Harbour Community Clinic"]; reveal(explore); explore.tap()
        let ask = app.buttons["Ask about this map"]; reveal(ask); ask.tap()
        let field = app.textFields["Type a map question"].exists ? app.textFields["Type a map question"] : app.textViews["Type a map question"]
        XCTAssertTrue(field.waitForExistence(timeout:5)); field.tap(); field.typeText("Where is Reception desk?")
        app.buttons["Ask"].tap()
        let answer = app.staticTexts.matching(NSPredicate(format:"label CONTAINS %@","Reception desk is in Reception and waiting")).firstMatch
        XCTAssertTrue(answer.waitForExistence(timeout:10))
    }
}
