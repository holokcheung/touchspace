# Touchspace AI iOS apps

The current app is [TouchspaceAI.xcodeproj](TouchspaceAI.xcodeproj). See the [main setup guide](../README.md) and [validation guide](../docs/ios-testing.md). Regenerate it with `xcodegen generate --spec project.yml`.

## Legacy RoomPlan scanner reference

The separate `TouchSpaceScanner.xcodeproj` below is preserved for the existing web import workflow. Its generator is `legacy-scanner.yml`.

A small SwiftUI app that scans a room with Apple RoomPlan and exports the result for TouchSpace AI.

**Status:** source code and Xcode project are complete, but the app has **not been built or run yet**. The machine it was written on has no Xcode. Expect to fix small compile errors on the first build. Nothing here has been tested on a device.

## What it does

1. Checks `RoomCaptureSession.isSupported`. RoomPlan needs a LiDAR iPhone or iPad (iPhone 12 Pro or newer Pro models, iPad Pro 2020 or newer).
2. **Start a new scan** opens Apple's `RoomCaptureView`, with its coaching overlay. Coaching instructions are also announced to VoiceOver.
3. **Done** stops capture. RoomPlan post-processes the scan and shows its result.
4. Name the scan and **Save** it. The app writes:
   - `touchspace-<name>.json`: the `CapturedRoom`, encoded with `JSONEncoder` exactly as RoomPlan defines it. There is no custom schema.
   - `touchspace-<name>.usdz`: a parametric 3D model, for previewing.
5. From a saved scan you can:
   - share the JSON or USDZ (AirDrop, Files, Mail, and so on);
   - preview the USDZ in Quick Look;
   - **Send to TouchSpace**: upload the JSON straight to the backend on your computer.

## Build and run

Requirements: a Mac with Xcode 15 or newer, an Apple ID (a free account works for running on your own device), and a LiDAR device running iOS 17 or newer.

1. Open `ios-scanner/TouchSpaceScanner.xcodeproj` in Xcode.
2. Select the **TouchSpaceScanner** target, then **Signing & Capabilities**. Choose your **Team**. If the bundle ID `ai.touchspace.scanner` is taken, change it to something unique.
3. Plug in the device, select it as the run destination, and press **Run**.
4. On the device, trust the developer certificate if asked: Settings → General → VPN & Device Management.

The simulator can build the app, but RoomPlan reports itself unsupported there, so scanning needs a real device.

If you add or remove Swift files, regenerate the project:

```bash
brew install xcodegen
cd ios-scanner && xcodegen generate --spec legacy-scanner.yml
```

## Sending scans to your computer

1. On the computer, start the backend so other devices can reach it:
   ```bash
   cd backend && .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```
2. Find the computer's IP address. On a Mac, use System Settings → Wi-Fi → Details.
3. In the app, open a saved scan and set **Server address** to `http://<that-ip>:8000`. Tap **Send to TouchSpace**. The phone and computer must be on the same Wi-Fi network.
4. The scan appears on the TouchSpace website under **Upload scan → Your maps**.

Without the network route, share the JSON to your computer (AirDrop works well) and upload it on the website.

## After importing

RoomPlan does not record room names, entrances, exits, restrooms or walkable routes. Mark these in the TouchSpace floor-plan editor before printing. RoomPlan's room-type guesses, such as "Living room (unconfirmed)", and detected stairs are labeled so you can confirm them.

## Files

| File | Purpose |
| --- | --- |
| `TouchSpaceScannerApp.swift` | App entry point |
| `ContentView.swift` | Home screen: support check, start scan, saved scans |
| `ScanFlowView.swift` | Full-screen scan → process → name → save flow |
| `RoomCaptureViewController.swift` | Hosts `RoomCaptureView`, implements the RoomPlan delegates |
| `ScanStore.swift` | Saves the `CapturedRoom` JSON and USDZ in the app's Documents folder |
| `ScanDetailView.swift` | Scan summary, share, Quick Look, upload |
| `Uploader.swift` | Multipart `POST /api/scans` to the TouchSpace backend |
| `SoundscapeSettings.swift` | Decodes `shared/soundscape.json` (bundled) for a future live LiDAR soundscape; not used by a screen yet. See [docs/soundscape.md](../docs/soundscape.md). |
| `legacy-scanner.yml` | XcodeGen spec for the legacy scanner |
