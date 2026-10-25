import Foundation
import XCTest
#if SWIFT_PACKAGE
@testable import TouchSpaceCore
#else
@testable import TouchSpace
#endif

final class SimulationTests: XCTestCase {
    func package(_ slug:String) throws -> MapPackage {
        #if SWIFT_PACKAGE
        let root = URL(fileURLWithPath:#filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("sample-data/mock-maps/\(slug)")
        var data: [String:Any] = [:]
        for name in ["manifest","geometry","landmarks","navigation"] { data[name] = try JSONSerialization.jsonObject(with:Data(contentsOf:root.appendingPathComponent(name+".json"))) }
        return try JSONDecoder().decode(MapPackage.self,from:JSONSerialization.data(withJSONObject:data))
        #else
        return try PackageCodec.load(XCTUnwrap(Bundle(for:Self.self).url(forResource:slug,withExtension:"touchspacemap")))
        #endif
    }
    func testVirtualWalkRemainsCollisionFreeAndArrives() throws {
        for (slug,destination) in [("harbour-clinic","clinic-treatment"),("neighbourhood-library","library-travel")] {
            var engine = try SimulationEngine(package:package(slug))
            try engine.plan(to:destination)
            XCTAssertGreaterThan(engine.route?.distance ?? 0,5)
            try engine.follow()
            var arrived = false, previous = engine.pose.position
            for _ in 0..<600 {
                if let update = engine.tick(seconds:0.1) { arrived = update.arrived || arrived }
                XCTAssertTrue(engine.spatial.clearSegment(previous,engine.pose.position))
                previous = engine.pose.position
                if arrived { break }
            }
            XCTAssertTrue(arrived)
            XCTAssertFalse(engine.following)
            let target = try XCTUnwrap(engine.package.landmarks.landmarks.first { $0.id == destination })
            XCTAssertLessThan(engine.pose.position.distance(to:target.position),0.65)
        }
    }
    func testManualCollisionPauseResetAndUnknownDoor() throws {
        var package = try SpatialTests().fixture().package
        package.manifest.provenance = "synthetic-fixture"
        package.landmarks.landmarks[1].kind = "entrance"
        var engine = try SimulationEngine(package:package)
        XCTAssertTrue(engine.move(0.5))
        let position = engine.pose.position
        XCTAssertFalse(engine.move(0.5))
        XCTAssertEqual(engine.pose.position,position)
        try engine.plan(to:"desk"); try engine.follow(); _ = engine.tick(seconds:0.1)
        engine.pause(); let paused = engine.pose.position
        _ = engine.tick(seconds:0.2); XCTAssertEqual(engine.pose.position,paused)
        engine.reset(); XCTAssertNil(engine.route); XCTAssertEqual(engine.pose.position,.init(x:1,z:2.5))
        var clinic = try SimulationEngine(package:self.package("harbour-clinic"))
        XCTAssertThrowsError(try clinic.plan(to:"clinic-supplies"))
        XCTAssertNil(clinic.route); XCTAssertFalse(clinic.following)
    }
    func testChatRequestKeepsVirtualCoordinatesSeparateFromPhysicalTracking() throws {
        let package = try package("harbour-clinic")
        let pose = SimulatedPose(position:.init(x:1,z:2.4),heading:0)
        let request = MapChatRequest(package:package,session:UUID(),message:"Could you show me the treatment area?",simulatedPose:pose)
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with:JSONEncoder().encode(request)) as? [String:Any])
        XCTAssertNil(body["pose"])
        let virtual = try XCTUnwrap(body["simulatedPose"] as? [String:Any])
        XCTAssertNil(virtual["verified"])
        XCTAssertEqual(virtual["coordinateFrameId"] as? String,package.manifest.coordinateFrameId.uuidString)
        XCTAssertNotNil(body["mapPackage"])
        let physical = MapChatRequest(package:package,session:UUID(),message:"What's nearby?")
        XCTAssertNil(physical.simulatedPose); XCTAssertNil(physical.pose)
    }
    func testReplanningOwnsItsGridAndPreservesVirtualPoseAndReset() throws {
        let package = try package("harbour-clinic")
        var original = try SimulationEngine(package:package)
        XCTAssertTrue(original.move(0.5))
        var replanned = try SimulationEngine(package:package,currentPose:original.pose)
        XCTAssertFalse(original.spatial === replanned.spatial)
        XCTAssertEqual(original.pose,replanned.pose)
        replanned.reset(); XCTAssertEqual(replanned.pose.position,.init(x:1,z:2.4))
        XCTAssertThrowsError(try SimulationEngine(package:package,currentPose:.init(position:.init(x:0,z:0),heading:0)))
    }
    func testRealCaptureCannotEnterSimulationEngine() throws {
        let package = try SpatialTests().fixture().package
        XCTAssertThrowsError(try SimulationEngine(package:package))
    }
    func testConcaveFloorsTriangulateWithoutFillingUnknownArea() throws {
        let polygon: [MapPoint] = [.init(x:0,z:0),.init(x:3,z:0),.init(x:3,z:1),.init(x:1,z:1),.init(x:1,z:3),.init(x:0,z:3)]
        for points in [polygon,Array(polygon.reversed())] {
            let indices = try PolygonMesh.triangles(points)
            XCTAssertEqual(indices.count,(points.count-2)*3)
            var area = 0.0
            for i in stride(from:0,to:indices.count,by:3) {
                let a=points[Int(indices[i])],b=points[Int(indices[i+1])],c=points[Int(indices[i+2])]
                area += abs((b.x-a.x)*(c.z-a.z)-(b.z-a.z)*(c.x-a.x))/2
                XCTAssertTrue(polygonContains((a+b+c)*(1/3.0),points))
            }
            XCTAssertEqual(area,5,accuracy:1e-8)
        }
    }
}
