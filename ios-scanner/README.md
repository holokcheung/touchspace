# TouchSpace for iOS

Native SwiftUI app for RoomPlan capture, complete map sharing, offline exploration and automatically localized AR navigation. Requires iOS 17+. Capture requires a LiDAR iPhone/iPad; restoring a world map requires an ARKit-capable physical device at the scanned venue.

Open `TouchSpace.xcodeproj`, select the **TouchSpace** scheme and set your development team under Signing & Capabilities. The project and pinned Swift package resolution are checked in. To regenerate it after changing target configuration:

```sh
xcodegen generate --spec ios-scanner/project.yml
```

From the repository root, start the existing backend:

```sh
cd backend
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

In the app's Settings, enter the backend's LAN URL for a physical phone (`http://<Mac-LAN-IP>:8000`) or `http://localhost:8000` for the simulator. HTTPS is required for a hosted backend. No API key belongs in the app.

Set `TOUCHSPACE_PUBLISH_CODE` on the backend to enable demo pairing and uploads. Pair in **Map detail → Upload or publish**. Credentials expire after one hour and live in Keychain. Pairing again from the same installation restores access to its private uploads, provided the server retains its signing key. Public publishing needs both the public toggle and a separate permission confirmation.

The app sends a `.touchspacemap` ZIP, including all JSON payloads and `worldmap.archive`, to `/api/touchspace/maps`. The legacy `/api/scans` RoomPlan-JSON upload remains available for the web/printing workflow.

Run portable algorithm/policy tests on a Mac:

```sh
cd ios-scanner
swift test
```

Run native tests/build from the repository root (substitute an installed simulator):

```sh
xcodebuild -project ios-scanner/TouchSpace.xcodeproj -scheme TouchSpace \
  -destination 'platform=iOS Simulator,name=iPhone 18 Pro' \
  CODE_SIGNING_ALLOWED=NO test
```

The simulator supports UI and unit testing, not real RoomPlan capture or saved-world relocalization. See [the implementation and device validation guide](../docs/IOS_MVP.md).

## Testing without LiDAR

Two importable [synthetic map bundles](../sample-data/mock-maps/README.md) are included: a furnished community clinic and a neighbourhood library. Tap **Try demo spaces** on Home to open the demo chooser, then select **Explore floor plan** or **Start 3D walkthrough** for either venue. The chooser opens even when both bundles are already downloaded. The demo renders a real 3D scene from the geometry, supports collision-checked virtual movement and route playback, and answers fixture questions locally. **AR model** additionally previews a miniature map on camera-capable physical devices without LiDAR. Synthetic provenance still disables physical venue localization; a non-restorable placeholder occupies the normal world-map entry. Simulated poses remain separate from verified AR tracking. Native tests exercise import, virtual movement, route playback, local questions and the full simulator UI flow.
