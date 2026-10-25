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

Two importable [synthetic map bundles](../sample-data/mock-maps/README.md) are included: a furnished community clinic and a neighbourhood library. Tap **Try demo spaces**, then **Start 3D walkthrough** for either venue. It opens directly in a full-screen first-person scene. Swipe left/right to turn; the wide up/down chevrons move forward/back half a metre with collision checks. There is no overview tab, bottom toolbar or text chat in the walkthrough. The close button returns to the chooser, which also offers **Explore floor plan**.

Hold the microphone while speaking and release to send. The saved-map assistant answers aloud using local speech synthesis. Holding again interrupts its reply. Try “Where am I?”, “What is nearby?” or “Take me to Treatment bed.” A navigation request draws a validated route from the current virtual position; you move along it manually. Fixture questions use saved geometry without uploading the map or requiring an API key. VoiceOver supports double-tap to start and double-tap again to send.

Physical iPhones use Apple’s on-device recognizer and require microphone/speech permissions plus a speech language. The walkthrough in the Simulator instead records PCM audio and sends it to the configured Mac backend’s existing `/api/stt` endpoint with `local_only=true`. This flag never falls back to Cartesia or any cloud provider. The microphone label says **speech via your Mac**. Approve microphone permission on both Simulator and macOS if prompted; then hold again.

Set up simulator speech once, from the repository root:

```sh
brew install whisper.cpp
bash backend/scripts/setup_local_speech.sh
cd backend
.venv/bin/python -m uvicorn app.main:app --port 8000
```

The setup script downloads a checksum-verified 74 MiB English Whisper model to gitignored `backend/data/speech/`. Existing installations are left intact. `/api/health` reports `features.local_stt=true` when the CLI/model are available. Override their paths with `TOUCHSPACE_WHISPER_CLI` / `TOUCHSPACE_WHISPER_MODEL`. In app Settings use `http://localhost:8000` for this Simulator. Audio is deleted after transcription; only the question text reaches the saved-map assistant. The app gives specific errors for an unreachable server, unavailable model, or silent microphone input. For silent input, check **Simulator → I/O → Audio Input** and macOS microphone permission.

The tested iOS 27.0 Simulator advertises `supportsOnDeviceRecognition=true`, but its downloaded English Apple model cannot run: initially `mini.json` is absent because the model is still in a cryptex, and expanding it reveals only an iPhone H19 specialization while the Simulator expects CPU/JIT models. Merely checking the support flag is insufficient. Changing to Apple’s standard recognition mode also failed. The Mac transcription path avoids this runtime limitation and requires no cloud key.

Synthetic provenance disables physical venue localization; simulated poses remain separate from verified AR tracking. Native tests cover import, movement, routes and voice cancellation/permission timing. UI tests use a DEBUG-only injected transcription (`--ui-test-voice`) for gestures. A separate integration test feeds a synthesized WAV through the actual simulator networking → local Whisper → map-answer/speech pipeline twice:

```sh
# After build-for-testing with -derivedDataPath /tmp/touchspace-derived,
# and with the local speech backend running:
python3 ios-scanner/scripts/test_local_speech.py
```

The source fixture is `TouchSpaceTests/Fixtures/reception-question.wav`, generated with macOS `say -v Samantha -r 145` and converted to mono 16 kHz PCM with `afconvert`. The integration test does not fake recognition results; microphone hardware and audible playback still require a manual check. Apple’s native recognizer also has an opt-in integration test for a physical-device setup with working speech assets.
