import Foundation
import XCTest
#if SWIFT_PACKAGE
@testable import TouchSpaceCore
#else
@testable import TouchSpace
#endif

final class SpatialTests: XCTestCase {
    struct Fixture: Decodable {
        var package: MapPackage
        var start: MapPoint
        var destinationId: String
        var expectedDistance: Double
        var expectedWaypoints: [MapPoint]
    }
    func fixture() throws -> Fixture {
        #if SWIFT_PACKAGE
        let url = URL(fileURLWithPath:#filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("shared/fixtures/routes.json")
        #else
        let url = try XCTUnwrap(Bundle(for:Self.self).url(forResource:"routes",withExtension:"json"))
        #endif
        return try JSONDecoder().decode(Fixture.self,from:Data(contentsOf:url))
    }
    func testSharedAStarDistanceAndEverySegmentCollisionFree() throws {
        let fixture = try fixture(), engine = try SpatialEngine(fixture.package)
        let route = try engine.route(from:fixture.start,to:fixture.destinationId)
        XCTAssertEqual(route.distance,fixture.expectedDistance,accuracy:1e-7)
        XCTAssertEqual(route.waypoints.count,fixture.expectedWaypoints.count)
        for (actual,expected) in zip(route.waypoints,fixture.expectedWaypoints) {
            XCTAssertEqual(actual.x,expected.x,accuracy:1e-7); XCTAssertEqual(actual.z,expected.z,accuracy:1e-7)
        }
        for (a,b) in zip(route.waypoints,route.waypoints.dropFirst()) { XCTAssertTrue(engine.clearSegment(a,b)) }
        XCTAssertFalse(engine.clearSegment(.init(x:1,z:2.5),.init(x:7,z:2.5)))
        XCTAssertFalse(engine.walkable(.init(x:4,z:1)))
        XCTAssertFalse(engine.walkable(.init(x:-1,z:2)))
        XCTAssertFalse(engine.walkable(.init(x:2,z:1.1)))
    }
    func testUnknownAndBlockedDoorRefuseRoute() throws {
        for state in ["unknown","blocked"] {
            var package = try fixture().package
            package.navigation.doors[0].traversability = state
            XCTAssertThrowsError(try SpatialEngine(package).route(from:.init(x:3.3,z:2.5),to:"desk"))
        }
    }
    func testConfirmedDoorBridgesWallThicknessGapOnly() throws {
        var package = try fixture().package
        package.geometry.rooms[0].polygon[1].x=3.9
        package.geometry.rooms[0].polygon[2].x=3.9
        package.geometry.rooms[1].polygon[0].x=4.1
        package.geometry.rooms[1].polygon[3].x=4.1
        let engine = try SpatialEngine(package)
        XCTAssertTrue(engine.walkable(.init(x:4,z:2.7)))
        XCTAssertNotNil(engine.room(at:.init(x:4,z:2.7)))
        XCTAssertGreaterThan(try engine.route(from:.init(x:3.5,z:2.7),to:"desk").distance,0)
        package.navigation.doors[0].traversability="unknown"
        XCTAssertFalse(try SpatialEngine(package).walkable(.init(x:4,z:2.7)))
    }
    func testTransformAndHeadingConventions() throws {
        let transform = MapTransform(x:12,z:-4,yaw:.pi/2,y:1)
        let p = MapPoint(x:2,z:3), world = transform.world(p), roundTrip = transform.map(world)
        XCTAssertEqual(world.x,9,accuracy:1e-9); XCTAssertEqual(world.z,-2,accuracy:1e-9)
        XCTAssertEqual(roundTrip.x,p.x,accuracy:1e-9); XCTAssertEqual(roundTrip.z,p.z,accuracy:1e-9)
        XCTAssertEqual(transform.mapHeading(.pi/2),0,accuracy:1e-9)
        let engine = try SpatialEngine(fixture().package)
        XCTAssertEqual(engine.relativeBearing(from:.init(x:1,z:1),heading:0,to:.init(x:2,z:1)),.pi/2,accuracy:1e-9)
        XCTAssertEqual(engine.relativeBearing(from:.init(x:1,z:1),heading:.pi,to:.init(x:2,z:1)),-.pi/2,accuracy:1e-9)
    }
    func testOffRouteHysteresisAndArrival() {
        let route = PlannedRoute(destinationId:"goal",waypoints:[.init(x:0,z:0),.init(x:0,z:-8),.init(x:3,z:-8)])
        var guidance = GuidanceEngine(route:route)
        XCTAssertFalse(guidance.update(position:.init(x:2,z:-1),heading:0,time:1).shouldReroute)
        XCTAssertFalse(guidance.update(position:.init(x:2,z:-1),heading:0,time:2).shouldReroute)
        XCTAssertTrue(guidance.update(position:.init(x:2,z:-1),heading:0,time:4).shouldReroute)
        XCTAssertFalse(guidance.update(position:.init(x:2,z:-1),heading:0,time:5).shouldReroute)
        var arrival = GuidanceEngine(route:.init(destinationId:"g",waypoints:[.init(x:0,z:0),.init(x:0,z:-1)]))
        XCTAssertFalse(arrival.update(position:.init(x:0,z:-0.9),heading:0,time:1).arrived)
        XCTAssertFalse(arrival.update(position:.init(x:0,z:-0.9),heading:0,time:2).arrived)
        XCTAssertTrue(arrival.update(position:.init(x:0,z:-0.9),heading:0,time:3).arrived)
    }
    func testApproachAndTurnNowDoNotRepeat() {
        var guidance = GuidanceEngine(route:.init(destinationId:"g",waypoints:[.init(x:0,z:0),.init(x:0,z:-8),.init(x:4,z:-8)]))
        let first = guidance.update(position:.init(x:0,z:-4.5),heading:0,time:1)
        XCTAssertTrue(first.instruction?.contains("right") == true)
        XCTAssertNil(guidance.update(position:.init(x:0,z:-4.6),heading:0,time:2).instruction)
        let turn = guidance.update(position:.init(x:0,z:-7.5),heading:0,time:3)
        XCTAssertTrue(turn.instruction?.contains("now") == true)
    }
}

final class LocalizationTests: XCTestCase {
    let frameId = UUID(), anchorId = UUID()
    func evidence(_ time:Double) -> LocalizationVerifier.Evidence {
        .init(frameTime:time,now:time,didRelocalize:true,trackingNormal:true,anchorId:anchorId,
              anchorName:"touchspace-frame:\(frameId.uuidString.lowercased())",translationError:0,rotationError:0,
              position:.init(x:1,z:1),cameraHeight:1.4,insideScannedRoom:true)
    }
    func verifiedPolicy() -> LocalizationVerifier {
        var verifier = LocalizationVerifier(frameId:frameId,anchorId:anchorId)
        for i in 0...7 { _ = verifier.observe(evidence(Double(i)*0.2)) }
        return verifier
    }
    func testArchiveAndNormalTrackingAreInsufficient() {
        var verifier = LocalizationVerifier(frameId:frameId,anchorId:anchorId)
        for i in 0...10 {
            var sample = evidence(Double(i)*0.2); sample.didRelocalize=false
            XCTAssertNotEqual(verifier.observe(sample),.verified)
        }
        verifier.reset()
        for i in 0...10 {
            var sample = evidence(Double(i)*0.2); sample.anchorId=UUID()
            XCTAssertNotEqual(verifier.observe(sample),.verified)
        }
    }
    func testConsistentEvidenceRequiredAndTrackingLossSuspends() {
        var verifier = LocalizationVerifier(frameId:frameId,anchorId:anchorId)
        XCTAssertNotEqual(verifier.observe(evidence(0)),.verified)
        for i in 1...7 { _ = verifier.observe(evidence(Double(i)*0.2)) }
        XCTAssertEqual(verifier.observe(evidence(1.6)),.verified)
        var limited = evidence(1.8); limited.trackingNormal=false
        XCTAssertNotEqual(verifier.observe(limited),.verified)
        XCTAssertNotEqual(verifier.observe(evidence(2.0)),.verified)
    }
    func testStaleFrameWrongRoomAnchorTransformAndJumpSuspend() {
        let changes: [(inout LocalizationVerifier.Evidence)->Void] = [
            { $0.now += 1 }, { $0.insideScannedRoom=false }, { $0.translationError=0.2 },
            { $0.rotationError=0.2 }, { $0.cameraHeight=5 }, { $0.anchorName="wrong-frame" },
            { $0.position = .init(x:5,z:5) }
        ]
        for change in changes {
            var verifier = verifiedPolicy(), sample = evidence(1.6)
            change(&sample)
            XCTAssertNotEqual(verifier.observe(sample),.verified)
        }
    }
}

final class JSONGuardTests: XCTestCase {
    func testDuplicateKeysIncludingEscapedKeysRejected() throws {
        XCTAssertThrowsError(try JSONGuard.validate(Data(#"{"id":1,"id":2}"#.utf8)))
        XCTAssertThrowsError(try JSONGuard.validate(Data(#"{"id":1,"\u0069d":2}"#.utf8)))
        XCTAssertThrowsError(try JSONGuard.validate(Data(#"{"value":NaN}"#.utf8)))
        try JSONGuard.validate(Data(#"{"a":{"id":1},"b":{"id":2},"label":"escaped \" quote"}"#.utf8))
    }
}
