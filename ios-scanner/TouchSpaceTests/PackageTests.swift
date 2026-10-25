#if !SWIFT_PACKAGE
import Foundation
import XCTest
import ZIPFoundation
@testable import TouchSpace

final class PackageTests: XCTestCase {
    func testMissingWorldArchiveAndPathsRejected() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at:directory,withIntermediateDirectories:true)
        defer { try? FileManager.default.removeItem(at:directory) }
        let url = directory.appendingPathComponent("invalid.touchspacemap")
        do {
            let archive = try Archive(url:url,accessMode:.create)
            let data = Data("{}".utf8)
            try archive.addEntry(with:"../manifest.json",type:.file,uncompressedSize:Int64(data.count)) { offset,count in data.subdata(in:Int(offset)..<(Int(offset)+count)) }
        }
        XCTAssertThrowsError(try PackageCodec.readEntries(url))
        try FileManager.default.removeItem(at:url)
        do {
            let archive = try Archive(url:url,accessMode:.create)
            let data = Data("{}".utf8)
            try archive.addEntry(with:"manifest.json",type:.file,uncompressedSize:Int64(data.count)) { offset,count in data.subdata(in:Int(offset)..<(Int(offset)+count)) }
        }
        XCTAssertThrowsError(try PackageCodec.readEntries(url))
    }
    func testGeneratedSyntheticBundlesImportWithoutAuthorizingAR() throws {
        for name in ["harbour-clinic","neighbourhood-library"] {
            let url = try XCTUnwrap(Bundle(for:Self.self).url(forResource:name,withExtension:"touchspacemap"))
            let package = try PackageCodec.load(url)
            XCTAssertTrue(package.manifest.isSynthetic)
            XCTAssertEqual(package.manifest.verification,"unverified")
            XCTAssertGreaterThanOrEqual(package.geometry.rooms.count,4)
            XCTAssertGreaterThanOrEqual(package.landmarks.landmarks.count,6)
            XCTAssertThrowsError(try PackageCodec.worldMap(url,manifest:package.manifest))
            var manifest = package.manifest
            manifest.provenance = "roomplan-same-session"
            let entries = try PackageCodec.readEntries(url)
            // A fixture archive cannot be promoted to a real capture simply by relabeling it.
            XCTAssertThrowsError(try PackageCodec.decodeWorldMap(entries["worldmap.archive"]!,manifest:manifest))
            manifest.frameAnchorId = UUID()
            XCTAssertThrowsError(try PackageCodec.validateSyntheticWorldMap(entries["worldmap.archive"]!,manifest:manifest))
        }
    }
    func testInvalidRoomAssociationRejectedBeforeARDecode() throws {
        var package = try SpatialTests().fixture().package
        package.landmarks.landmarks[0].position = .init(x:-50,z:0)
        XCTAssertThrowsError(try PackageCodec.validate(package))
    }
}
#endif
