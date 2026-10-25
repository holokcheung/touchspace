// swift-tools-version: 5.9
import PackageDescription
let package = Package(
    name:"TouchSpaceCore",
    platforms:[.macOS(.v13)],
    products:[.library(name:"TouchSpaceCore",targets:["TouchSpaceCore"])],
    targets:[
        .target(name:"TouchSpaceCore",path:"TouchSpace/Core"),
        .testTarget(name:"TouchSpaceCoreTests",dependencies:["TouchSpaceCore"],path:"TouchSpaceTests",exclude:["Fixtures"])
    ]
)
