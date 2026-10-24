import XCTest
@testable import TouchspaceCore

final class CoreTests: XCTestCase {
    func demo() throws -> MapPackage {
        let url=Bundle.module.url(forResource:"touchspace-demo",withExtension:"touchspacemap",subdirectory:"Fixtures")!
        return try MapPackage(data:Data(contentsOf:url))
    }
    func testDeflatedFixtureAndStoredRoundtrip() throws {
        let p=try demo(), data=try p.encoded(), restored=try MapPackage(data:data)
        XCTAssertEqual(p.manifest,restored.manifest); XCTAssertEqual(p.geometry,restored.geometry)
        XCTAssertNil(p.worldData); XCTAssertEqual(p.warnings.count,2)
    }
    func testSharedDeterministicVectors() throws {
        struct V: Decodable {
            struct R: Decodable { var start:String; var end:String; var nodeIds:[String]; var distanceMeters:Double }
            struct U: Decodable { var start:String; var end:String }
            struct D: Decodable { var position:Point; var target:Point; var heading:Double; var direction:String }
            var route:R; var unreachable:U; var directions:[D]
        }
        let url=Bundle.module.url(forResource:"spatial-test-vectors",withExtension:"json",subdirectory:"Fixtures")!
        let v=try JSONDecoder().decode(V.self,from:Data(contentsOf:url)), p=try demo(), e=SpatialEngine(package:p)
        let r=try e.route(from:v.route.start,to:v.route.end)
        XCTAssertEqual(r.nodeIds,v.route.nodeIds); XCTAssertEqual(r.distanceMeters,v.route.distanceMeters,accuracy:1e-8)
        XCTAssertThrowsError(try e.route(from:v.unreachable.start,to:v.unreachable.end))
        for d in v.directions {
            let pose=Pose(coordinateFrameId:p.manifest.coordinateFrameId,position:d.position,heading:d.heading,tracking:.localized,frameVerified:true)
            XCTAssertEqual(e.relative(from:pose,to:d.target).direction,d.direction)
        }
    }
    func testBadCoordinateFramesAndGeometry() throws {
        var p=try demo(); p.navigation.coordinateFrameId=UUID(); XCTAssertThrowsError(try p.validate())
        p=try demo(); p.geometry.walls[0].b.z=4; XCTAssertThrowsError(try p.validate())
        p=try demo(); p.navigation.edges[1].doorId=nil; XCTAssertThrowsError(try p.validate())
        p=try demo(); p.navigation.nodes[0].position.x = -.infinity; XCTAssertThrowsError(try p.validate())
        p=try demo(); p.navigation.nodes.append(p.navigation.nodes[0]); XCTAssertThrowsError(try p.validate())
    }
    func testArchiveCorruptionAndTraversal() throws {
        let p=try demo(); var data=try p.encoded(); data[50] ^= 0xff; XCTAssertThrowsError(try MapPackage(data:data))
        var files=try MapArchive.read(p.encoded()); files["../evil"]=Data([1]); XCTAssertThrowsError(try MapArchive.write(files))
        XCTAssertThrowsError(try MapArchive.read(Data([1,2,3])))
    }
    func testTrackingGate() throws {
        var p=try demo()
        var pose=Pose(coordinateFrameId:p.manifest.coordinateFrameId,position:Point(x:3,z:2),heading:0,tracking:.localized,frameVerified:true)
        XCTAssertFalse(pose.isUsable(for:p.manifest)) // draft cannot localize
        p.manifest.worldMapIncluded=true
        XCTAssertTrue(pose.isUsable(for:p.manifest))
        for status in [Tracking.limited,.failed,.relocalizing] { pose.tracking=status; XCTAssertFalse(pose.isUsable(for:p.manifest)) }
        pose.tracking = .localized; pose.frameVerified=false; XCTAssertFalse(pose.isUsable(for:p.manifest))
        pose.frameVerified=true; pose.timestamp=Date().addingTimeInterval(-11); XCTAssertFalse(pose.isUsable(for:p.manifest))
    }
    func testUnknownDoorBlocksRouteAndNoWallSnapping() throws {
        var p=try demo(); p.navigation.doors[0].traversable=false
        XCTAssertThrowsError(try SpatialEngine(package:p).route(from:"entry",to:"exit"))
        XCTAssertThrowsError(try SpatialEngine(package:p).nearestNode(to:Point(x:4,z:0.2)))
    }
}

final class GuidanceTests: XCTestCase {
    func testNoLocalizationFromNormalTrackingAlone() {
        var g=LocalizationGate()
        g.update(normalTracking:true,recoveredFrameAnchor:false); XCTAssertFalse(g.canGuide)
        g.update(normalTracking:false,recoveredFrameAnchor:true); XCTAssertFalse(g.canGuide)
        g.update(normalTracking:true,recoveredFrameAnchor:true); XCTAssertTrue(g.canGuide)
        g.update(normalTracking:false,recoveredFrameAnchor:true); XCTAssertEqual(g.status,.limited); XCTAssertFalse(g.canGuide)
        g.fail(); XCTAssertEqual(g.status,.failed); XCTAssertFalse(g.frameVerified)
    }
    func testGuidanceStopsOnLostTrackingAndOffRoute() throws {
        var p=try CoreTests().demo(); p.manifest.worldMapIncluded=true
        let e=SpatialEngine(package:p), r=try e.route(from:"entry",to:"exit")
        var g=Guidance(); g.start(r)
        var pose=Pose(coordinateFrameId:p.manifest.coordinateFrameId,position:Point(x:1,z:2),heading:0,tracking:.localized,frameVerified:true)
        g.update(pose:pose,engine:e); XCTAssertEqual(g.state,.navigating); XCTAssertEqual(g.cue?.direction,"right")
        pose.tracking = .limited; g.update(pose:pose,engine:e); XCTAssertEqual(g.state,.trackingLost); XCTAssertNil(g.cue)
        pose.tracking = .localized; g.update(pose:pose,engine:e); XCTAssertEqual(g.state,.trackingLost) // explicit resume required
        g.start(r); pose.position=Point(x:1,z:0.5); g.update(pose:pose,engine:e); XCTAssertEqual(g.state,.offRoute)
    }
    func testGroundedOfflineQuestionsAndStableFollowup() throws {
        let p=try CoreTests().demo(); var a=LocalAssistant()
        XCTAssertTrue(a.answer("where is the exit",package:p,pose:nil).sourceIds.contains("main-exit"))
        XCTAssertTrue(a.answer("tell me about it",package:p,pose:nil).sourceIds.contains("main-exit"))
        XCTAssertNil(a.answer("take me there",package:p,pose:nil).destinationId)
        XCTAssertTrue(a.answer("what color is the exit",package:p,pose:nil).reply.contains("unknown"))
    }
}

final class GraphBuilderTests:XCTestCase {
    func testSurveyedGridAvoidsObstaclesAndUnknownSpace() throws {
        var p=try CoreTests().demo()
        p.geometry.rooms=Array(p.geometry.rooms.prefix(1)); p.geometry.walls=[]
        p.navigation=try GraphBuilder.build(manifest:p.manifest,geometry:p.geometry,doors:[])
        p.landmarks.landmarks=[]; try p.validate()
        let engine=SpatialEngine(package:p)
        XCTAssertGreaterThan(p.navigation.nodes.count,0)
        for n in p.navigation.nodes { XCTAssertTrue(engine.segmentValid(n.position,n.position)); XCTAssertLessThanOrEqual(n.position.x,4) }
        let a=try engine.nearestNode(to:Point(x:0.8,z:0.8)), b=try engine.nearestNode(to:Point(x:3,z:3))
        let route=try engine.route(from:a.id,to:b.id); XCTAssertGreaterThan(route.distanceMeters,0)
    }
}


final class PackageBoundaryTests:XCTestCase {
    func testEquivalentCatalogDatesAndArchivePathTampering() throws {
        let p=try CoreTests().demo()
        var manifest=p.manifest; manifest.createdAt="2026-10-24T00:00:00.000+00:00"
        XCTAssertTrue(p.manifest.matchesCatalog(manifest))
        manifest.contributor="Different contributor";XCTAssertFalse(p.manifest.matchesCatalog(manifest))
        var data=try p.encoded()
        // Both local and central filenames are untrusted, even if their lengths remain valid.
        let old=Data("geometry.json".utf8), bad=Data("../evilx.json".utf8)
        while let range=data.range(of:old) { data.replaceSubrange(range,with:bad) }
        XCTAssertThrowsError(try MapArchive.read(data))
    }
}

final class CanonicalValidationTests:XCTestCase {
    func testExportCannotCreateUnreadablePackage() throws {
        var p=try CoreTests().demo();p.manifest.contributor="   "
        XCTAssertThrowsError(try p.encoded())
        p=try CoreTests().demo();p.geometry.rooms[0].name=""
        XCTAssertThrowsError(try p.encoded())
        p=try CoreTests().demo();p.manifest.mapId="map-id\n"
        XCTAssertThrowsError(try p.encoded())
        var files=try MapArchive.read(try CoreTests().demo().encoded());files["worldmap.archive"]=Data()
        XCTAssertThrowsError(try MapArchive.write(files))
    }
}

final class PendingAnswerTests:XCTestCase {
    func testPoseAnswerExpiresOnLossMovementRotationAndStaleness() throws {
        var p=try CoreTests().demo();p.manifest.worldMapIncluded=true
        let request=Pose(coordinateFrameId:p.manifest.coordinateFrameId,position:Point(x:3,z:2),heading:0,tracking:.localized,frameVerified:true)
        XCTAssertTrue(request.stillMatches(request,for:p.manifest))
        var current=request;current.tracking = .limited;XCTAssertFalse(current.stillMatches(request,for:p.manifest))
        current=request;current.position.x += 1;XCTAssertFalse(current.stillMatches(request,for:p.manifest))
        current=request;current.heading = .pi/2;XCTAssertFalse(current.stillMatches(request,for:p.manifest))
        XCTAssertFalse(request.stillMatches(request,for:p.manifest,now:Date().addingTimeInterval(11)))
        XCTAssertFalse(request.stillMatches(nil,for:p.manifest))
    }
}
