# Touchspace AI validation

The automated suite tests components in order: package/coordinate validation and deterministic routing; API storage/access/publication; typed spatial Q&A/provider contracts; native persistence and positioning guards; simulator UI flow; then the actual Swift client against the running backend. A successful simulator run does not certify physical AR positioning.

## Automated tests

```bash
backend/.venv/bin/python -m pytest backend/tests
swift test --package-path ios-scanner/TouchspaceCore
```

Core Swift tests run on macOS and share the canonical X/Z heading and route vectors with Python. They check deflated import/stored export, CRC/path corruption, invalid frames and transforms, unreachable destinations, doorway restrictions, graph clearance, lost-tracking shutdown, off-route pause, pending-answer expiry, offline follow-ups, and equivalent server timestamp serialization.

The full backend suite includes all legacy API/geometry/STL tests. Feature tests cover private-by-default storage, unauthorized reads/chat, explicit public consent, missing world data, ZIP traversal/duplicates/malformed documents, schema/frame mismatches, wall/obstacle crossings, chunked/declared body limits, provider HTTP schema/ID validation, grounded follow-ups, unknown properties, pose freshness, heading rotation, and reachable/unreachable routes. Keyed world-map data in backend tests is explicitly a **structural test double** and is never shipped as a real map.

For the native client/server integration test, start a temporary backend in a separate terminal from `backend/`:

```bash
TOUCHSPACE_DATA_DIR=/tmp/touchspace-integration-data \
TOUCHSPACE_UPLOAD_TOKEN=integration-test-upload-credential-24-plus \
TOUCHSPACE_GEMINI_API_KEY='' GEMINI_API_KEY='' \
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```

This is an isolated test credential, not a production secret. The integration test uploads the bundled draft privately, downloads it with checksum verification through the real Swift API client, compares geometry, and asks a grounded question through the real backend. It skips if no server is listening on 8765. Do not point that test port at a production catalog.

```bash
xcrun simctl list devices available
xcodebuild -project ios-scanner/TouchspaceAI.xcodeproj \
  -scheme TouchspaceAI \
  -destination 'platform=iOS Simulator,name=iPhone 18 Pro' \
  -derivedDataPath ios-scanner/DerivedData \
  -parallel-testing-enabled NO test CODE_SIGNING_ALLOWED=NO

xcodebuild -project ios-scanner/TouchspaceAI.xcodeproj \
  -scheme TouchspaceAI -destination 'generic/platform=iOS' \
  -derivedDataPath ios-scanner/DerivedData build CODE_SIGNING_ALLOWED=NO
```

Use an installed simulator. On a freshly booted runtime, allow it to finish booting before starting tests (`xcrun simctl bootstatus <UDID> -b`). Xcode may emit SDK build-version/AppIntents metadata warnings in this environment. The initial cold runtime failed to launch the test host; a warm-runtime rerun passed. The project has no AppIntents dependency.

The UI tests access the critical map-only flow using labelled native controls, use typed input without microphone permission, check unsupported-scanner messaging, and run an automated accessibility description/trait audit at the largest accessibility text size. This is not a substitute for a manual VoiceOver and real-device audio audit.

## Required real-device acceptance run

These steps need LiDAR/camera hardware and a real venue. They have **not** been established by simulator tests.

1. On a LiDAR-equipped device, scan one enclosed room in a single uninterrupted session. Capture the complete floor, walls, doors, and furniture. Finish only when the scene has enough visual features. Name the room and landmarks, identify an entrance/exit where present, and review graph connectivity and doorway labels.
2. Save and share the package. Inspect the ZIP for all four JSON documents plus `worldmap.archive`. Confirm the same frame UUID in every document, the saved anchor ID/name, retained RoomPlan transforms, and a successful secure ARWorldMap decode. If mapping is insufficient, ensure only a map-only draft is offered and public publication is blocked.
3. Import into a fresh install or a second compatible device. Start live exploration in the same room. Slowly pan the camera. The app must remain relocalizing/limited until tracking is normal and the expected saved anchor is recovered; no manual coordinate/heading entry exists.
4. Once localized, select a reachable landmark, start navigation, and rotate the phone. Relative direction and stereo pan must follow the next waypoint in phone-facing coordinates. Compare a “what is to my right?” answer while facing opposite ways. Do not equate phone heading to body direction.
5. Cover the camera, move out of surveyed bounds, interrupt/background the app, and exercise a changed scene. Precise guidance must stop and announce uncertainty. Retry and explicitly resume. Test relocalization timeout, no camera permission, unavailable dictation, mute, repeat, speech-only mode, and cue intervals with real stereo headphones.
6. Export/import again and test another device if available. Confirm package geometry and IDs survive and a disconnected destination is rejected. Do not count archive presence alone as successful localization.
7. With VoiceOver enabled and large Dynamic Type, complete import, details, map-only Q&A, destination selection, start/pause/repeat/end, scanner fallback, and publish consent without interpreting the visual plan. Inspect focus order, pronunciation, interruptions, control reachability, and overlapping speech.
8. Configure a real server-side Gemini key and confirm a live provider turn, validated tool selection, fallback during provider failure, and no invented landmark/property. Provider HTTP payload/schema behavior is mocked in automated tests; a paid/live provider request was not made during implementation.

## Deliberate MVP limits

One coherent room per scan/session and one floor per package; separate sessions are never guessed into alignment. The synthetic demo covers multiple labelled rooms for deterministic tests, but cannot localize a device. The server structurally checks AR archives and labels them `present-unverified`; only iOS can perform secure ARKit decoding and a real device can attempt relocalization. Upload authorization is a single operator credential because the original project has no user-account infrastructure. There is no live obstacle sensing or reliable collision avoidance.

## Recorded implementation validation (2026-10-25)

- Naming recheck: the app, specification, backend module, tests, documentation, and file registration consistently use Touchspace AI / `touchspace`. The API prefix is `/api/touchspace`; configuration uses `TOUCHSPACE_UPLOAD_TOKEN`, `TOUCHSPACE_GEMINI_API_KEY`, and `TOUCHSPACE_GEMINI_MODEL`. Set these names when configuring the server.
- Backend: **179 tests passed** after integration with the latest main branch, including all 141 existing tests and the 38 isolated package/API/chat tests. The test client emits a dependency deprecation warning; no test failures remain.
- Preserved web workflow: **44 tests passed**, and its TypeScript/production build passed after integration with the latest main branch.
- Portable Swift core: **13 tests passed** on macOS, including pending-answer rejection when tracking, heading, position, or freshness changes.
- iOS simulator: **6 app/integration tests and 3 UI/accessibility tests passed** on iPhone 18 Pro / iOS 27.0, built with Xcode 27.1. The integration test made real Swift-to-FastAPI upload/download/chat requests against isolated temporary storage.
- Both simulator and generic iOS device targets built successfully without signing. This verifies compilation, not an installed device's AR/speech/audio behavior.
- Screenshot review confirmed that submitted questions dismiss the keyboard, scroll to their grounded answer, and retain prominent Ask/Repeat/Pause/End controls. Prominent buttons use the existing dark teal brand color with white text.
- Real-device scanning/relocalization, stereo headphone and manual VoiceOver checks, and a live provider request remain explicitly unverified. Follow the device procedure above.
