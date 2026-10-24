import XCTest

final class FlowTests:XCTestCase {
    func testMapOnlyCriticalFlowAndTypedQuestion() {
        let app=XCUIApplication(); app.launch()
        app.buttons["addDemo"].tap()
        app.buttons.matching(NSPredicate(format:"label CONTAINS %@","Small venue demo")).firstMatch.tap()
        XCTAssertTrue(app.staticTexts["Synthetic demonstration, not a scan of a real venue. It cannot be used for live positioning."].exists)
        for _ in 0..<6 { if app.buttons["exploreMap"].exists { break }; app.swipeUp() }
        app.buttons["exploreMap"].tap()
        XCTAssertTrue(app.buttons["askMicrophone"].exists)
        let input=app.textFields["questionInput"]
        // Multiline SwiftUI text inputs can be exposed as text views on newer iOS versions.
        let field=input.exists ? input:app.textViews["questionInput"]
        field.tap(); field.typeText("how are the rooms connected?")
        app.buttons["sendQuestion"].tap()
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format:"label CONTAINS %@","Gallery doorway links Lobby and Gallery")).firstMatch.waitForExistence(timeout:5))
        XCTAssertTrue(app.buttons["Repeat"].exists)
        XCTAssertFalse(app.keyboards.firstMatch.exists)
        let shot=XCTAttachment(screenshot:app.screenshot());shot.name="Explore map with grounded answer";shot.lifetime = .keepAlways;add(shot)
    }
    func testUnsupportedScannerExplainsHardwareRequirement() {
        let app=XCUIApplication(); app.launch(); app.buttons["scanSpace"].tap()
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format:"label CONTAINS %@","LiDAR-equipped")).firstMatch.waitForExistence(timeout:5))
    }
}

final class AccessibilityTests:XCTestCase {
    func testHomeControlsAndLargeTextRemainAccessible() throws {
        let app=XCUIApplication()
        app.launchArguments += ["-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityXXXL"]
        app.launch()
        if #available(iOS 17.0,*) {
            try app.performAccessibilityAudit(for:[.sufficientElementDescription,.trait])
        }
        for _ in 0..<5 { if app.buttons["addDemo"].isHittable {break}; app.swipeUp() }
        XCTAssertTrue(app.buttons["addDemo"].isHittable)
    }
}
