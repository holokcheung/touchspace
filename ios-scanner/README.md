# TouchSpace iOS RoomPlan scanner

This source is a minimal companion app for a physical iPhone or iPad that supports RoomPlan. It saves the framework's `CapturedRoom` using `JSONEncoder`, plus a USDZ when export succeeds, then opens the system share sheet.

## Add to Xcode

1. Create a new iOS App project named `TouchSpaceScanner` with SwiftUI and iOS 16.0 or later.
2. Add `TouchSpaceScannerApp.swift` and `ContentView.swift` from this folder to the app target.
3. In the target's Info settings, add `Privacy - Camera Usage Description` (`NSCameraUsageDescription`) with: `Camera access is used to scan room geometry for an accessible map.`
4. Build and run on a RoomPlan-compatible iPhone or iPad with LiDAR. Room scanning does not work in Simulator.
5. Finish a scan and use Share export to send the `.json` file to the web app.

The source exports the processed `CapturedRoom` object as Codable JSON. It does not export raw `CapturedRoomData`. The backend has not been tested on physical LiDAR hardware in this environment.
