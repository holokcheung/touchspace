# Touchspace AI

A native, accessible iOS app for exploring volunteer-scanned indoor maps with voice or text. Import a portable package, inspect its rooms and landmarks offline, attempt automatic ARKit positioning, and follow deterministic routes with speech and optional stereo waypoint cues.

The implementation follows [app-spec.md](app-spec.md). The app and its isolated backend module use the **Touchspace AI** name. No tactile hardware is required. The existing web/STL tools remain available as a separate reference workflow; see [legacy web documentation](docs/legacy-web.md).

## Run the iOS app

Open [ios-scanner/TouchspaceAI.xcodeproj](ios-scanner/TouchspaceAI.xcodeproj) in Xcode and run the **TouchspaceAI** scheme. Use iOS 17 or later and Xcode 16 or later (tested with Xcode 27.1). For a real device, choose your signing team in the app target. There are no external Swift package dependencies; `TouchspaceCore` is a local Swift package and uses system zlib.

The simulator supports import, map details, offline Q&A, catalog, settings, and the demo. RoomPlan scanning requires a LiDAR-equipped iPhone/iPad; live exploration requires a real saved world map and successful ARKit relocalization. The demo never fabricates those capabilities.

1. Tap **Try the map-only demo** to add the bundled small venue.
2. Open **Small venue demo**, read its metadata and warnings, and tap **Explore map**.
3. Ask or type “how are the rooms connected?” or “where is the exit?”. Follow-up questions retain stable landmark IDs. Direction questions clearly report that the map-only demo has no live position.
4. On a supported device, choose **Scan a space**, capture one enclosed room, finish, label rooms/entrances/landmarks, review connectivity, and save the complete package. World-map capture uses the same uninterrupted AR session. Inadequate world mapping produces an explicitly labelled map-only draft.
5. Share the saved `.touchspacemap` through the system share sheet. Another installation/device can import it from Files or an incoming share/open action and attempt **Start live exploration**.

Positioning requires normal tracking and the recovered saved frame anchor. Limited/lost/stale tracking halts guidance. Resume explicitly recalculates a route locally. Directions follow the phone, not necessarily the person's body. Maps are structural approximations, not live collision avoidance or a replacement for a cane/guide dog.

## Run the backend

Python 3.11+ is required (tested with Python 3.12). From the repository root:

```bash
uv venv --python 3.12 backend/.venv
uv pip install --python backend/.venv/bin/python -r backend/requirements-dev.txt
cp .env.example .env
cd backend
.venv/bin/python -m uvicorn app.main:app --reload --env-file ../.env --port 8000
```

Alternatively, use `python3 -m venv backend/.venv` and pip. Set `TOUCHSPACE_UPLOAD_TOKEN` in `.env` to at least 24 random characters to enable uploads. Without it, local app features and public browsing still work. Optional `TOUCHSPACE_GEMINI_API_KEY` (or existing `GEMINI_API_KEY`) enables backend conversational intent interpretation; `TOUCHSPACE_GEMINI_MODEL` chooses the model. Provider keys stay on the server. Without a key or during a provider outage, Q&A uses a deterministic fallback.

In iOS **Settings**, enter `http://localhost:8000` for the simulator, or an HTTPS server URL for a real device. Store the upload credential through the app's secure field. Uploads are private by default; public publication requires a separate explicit consent toggle and saved world data. **Use server assistant for this map** is opt-in and sends each question and its optional current pose only when submitted. Local maps are not silently uploaded for chat; upload privately or download a server-stored map first.

- [API contract, storage, authentication, LLM grounding, and limits](docs/touchspace-api.md)
- [Portable package format and shared coordinate conventions](docs/map-package.md)
- [Tests, device acceptance procedure, and remaining verification](docs/ios-testing.md)
- Interactive API documentation: `http://localhost:8000/docs`

## Test

```bash
backend/.venv/bin/python -m pytest backend/tests
swift test --package-path ios-scanner/TouchspaceCore
xcodebuild -project ios-scanner/TouchspaceAI.xcodeproj \
  -scheme TouchspaceAI -destination 'platform=iOS Simulator,name=iPhone 18 Pro' \
  -parallel-testing-enabled NO test CODE_SIGNING_ALLOWED=NO
```

Choose an installed simulator name from `xcrun simctl list devices available`. The client/server integration test needs the documented local backend on port 8765; it skips when that server is absent. [Testing instructions](docs/ios-testing.md) include its exact command and required device checks. `xcodegen generate --spec ios-scanner/project.yml` regenerates the checked-in Xcode project if source membership or settings change.

The synthetic venue fixture is [sample-data/touchspace-demo.touchspacemap](sample-data/touchspace-demo.touchspacemap), with canonical JSON in `sample-data/touchspace-demo/` and route/direction vectors in `sample-data/spatial-test-vectors.json`. It includes a reachable exit and a disconnected store room. Regenerate it using `python3 sample-data/scripts/make_touchspace_demo.py` and copy the archive/vectors into the app/test resource folders when changing fixtures.

## Layout

| Directory | Purpose |
| --- | --- |
| `ios-scanner/TouchspaceAI/` | SwiftUI maps, exploration, ARKit positioning, RoomPlan scanning, speech/dictation, catalog client |
| `ios-scanner/TouchspaceCore/` | Portable models, bounded ZIP codec, spatial engine, A*, occupancy-grid construction, guidance state, offline Q&A |
| `backend/app/touchspace/` | Package validation, SQLite catalog, file storage, authorized publication, deterministic tools, hosted intent interpretation |
| `backend/tests/test_touchspace_*` | Package, spatial, API, chat, and provider contract tests |
| `ios-scanner/TouchspaceAITests/` | Persistence, frame validation, scan transforms, and Swift client/server integration |
| `ios-scanner/TouchspaceAIUITests/` | Map-only critical flow, typed questions, hardware fallback, large text, accessibility audit |
| `frontend/` | Existing web editor/STL reference workflow |
| `sample-data/` | Clearly identified synthetic fixtures; no fake ARWorldMap |
