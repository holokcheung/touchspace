import XCTest
import ARKit
import AVFoundation
import TouchspaceCore
@testable import TouchspaceAI

@MainActor final class AppTests: XCTestCase {
    func testLibraryPersistsCompleteOfflinePackage() throws {
        let url=FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at:url) }
        let library=MapLibrary(directory:url)
        library.addDemo(); XCTAssertNil(library.error); XCTAssertEqual(library.maps.count,1)
        XCTAssertFalse(library.maps[0].package.manifest.worldMapIncluded)
        let restored=MapLibrary(directory:url); XCTAssertEqual(restored.maps.count,1)
        XCTAssertEqual(restored.maps[0].package.geometry.rooms.count,3)
        XCTAssertThrowsError(try WorldMapValidator.decode(restored.maps[0].package))
    }
    func testScanGeometryPreservesSessionTransform() {
        var transform=matrix_identity_float4x4
        transform.columns.3=SIMD4<Float>(2,1,3,1)
        XCTAssertEqual(ScanGeometry.project(SIMD3<Float>(1,0,2),transform),Point(x:3,z:5))
    }
    func testClientServerPackageRoundtrip() async throws {
        let client=try APIClient(address:"http://localhost:8765",token:"integration-test-upload-credential-24-plus")
        guard (try? await client.search("")) != nil else { throw XCTSkip("Start the integration backend on port 8765; see docs/ios-testing.md.") }
        let root=FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at:root) }
        let library=MapLibrary(directory:root); library.addDemo()
        let package=try XCTUnwrap(library.maps.first?.package)
        let record=try await client.upload(package,publicly:false,consent:false)
        XCTAssertEqual(record.visibility,"private");XCTAssertEqual(record.worldDataStatus,"absent-draft")
        let restored=try await client.download(record)
        XCTAssertEqual(restored.geometry,package.geometry)
        let response=try await client.chat(mapId:restored.manifest.mapId,sessionId:UUID(),message:"how are the rooms connected?",pose:nil)
        XCTAssertTrue(response.sourceIds.contains("gallery-door"));XCTAssertNil(response.action)
    }
    func testServerAddressValidation() throws {
        XCTAssertNoThrow(try APIClient(address:"https://maps.example.com"))
        XCTAssertNoThrow(try APIClient(address:"http://localhost:8000"))
        for bad in ["file:///etc/passwd","http://public.example.com","https://user:secret@example.com","https://example.com?token=secret"] {
            XCTAssertThrowsError(try APIClient(address:bad))
        }
    }
    func testDictationAudioConfigurationAcceptsMixing() async throws {
        try await AudioSessionController.shared.configureRecording()
        XCTAssertEqual(AVAudioSession.sharedInstance().category,.playAndRecord)
        XCTAssertTrue(AVAudioSession.sharedInstance().categoryOptions.contains(.mixWithOthers))
        try AVAudioSession.sharedInstance().setCategory(.playback,mode:.default,options:[.mixWithOthers])
    }
    func testFrameTransformMustBeIdentity() {
        XCTAssertTrue(WorldMapValidator.identity(matrix_identity_float4x4))
        var t=matrix_identity_float4x4; t.columns.3.x=1
        XCTAssertFalse(WorldMapValidator.identity(t))
        t=matrix_identity_float4x4; t.columns.0.x = .nan; XCTAssertFalse(WorldMapValidator.identity(t))
    }
}
