// swift-tools-version: 5.9
import PackageDescription
let package = Package(name: "TouchspaceCore", platforms: [.iOS(.v17), .macOS(.v13)], products: [.library(name: "TouchspaceCore", targets: ["TouchspaceCore"])], targets: [.target(name: "CZip", linkerSettings: [.linkedLibrary("z")]), .target(name: "TouchspaceCore", dependencies: ["CZip"]), .testTarget(name: "TouchspaceCoreTests", dependencies: ["TouchspaceCore"], resources: [.copy("Fixtures")])])
