# Native iOS MVP implementation and validation

This implementation follows the actual local checkout. There was no iOS target or `app.touchspace` source module in that tree, so both were added. The existing web scan/print service and its JSON contracts are preserved.

## Run the vertical slice

1. From `backend/`, start `.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000`.
2. Open `ios-scanner/TouchSpace.xcodeproj`, choose your development team, and run TouchSpace on an iOS 17+ LiDAR device. Set its backend URL to the Mac's LAN address in Settings.
3. Choose **Scan space → Start scan → Finish room**. Add an adjacent room while keeping the same AR session alive. An interrupted coordinate frame cannot be joined to a new independent scan.
4. Review floor geometry and furniture, rename scanned areas, confirm passable doorway links, and add named destinations in clear scanned space. Default coverage is partial. No guessed floor rectangle is substituted when RoomPlan lacks a floor polygon. Curved walls and mixed floor levels are rejected for this MVP.
5. Confirm the review and save. Use the native share sheet to move the complete package to another device, or pair and explicitly publish to the community. Saving never publishes.
6. On a visitor device, import or search/download the package. Geometry, rooms and destinations work offline. Start AR navigation at the venue, look around, wait for verified localization, then choose a destination.

The backend loads `backend/.env` and then repository `.env`, without replacing existing process environment variables. `OPENROUTER_API_KEY` is preferred; the local credential's historical `ANTHROPIC_API_KEY` variable is also supported, and is sent only as bearer auth to OpenRouter. Keys are never sent to iOS. The legacy web assistant keeps its own optional Gemini integration.

## Package contract

A `.touchspacemap` file is a ZIP containing exactly:

| File | Content |
| --- | --- |
| `manifest.json` | Version `1.0`, UUID map/frame/anchor IDs, venue/floor/coverage, contributor, review status, capture date, same-session provenance and payload SHA-256 checksums |
| `geometry.json` | Scanned room floor polygons, wall segments, conservative object footprints, floor height and explicit rigid `mapToWorld` transform |
| `landmarks.json` | Stable IDs, human labels, room association and map position |
| `navigation.json` | 0.1 m grid resolution, body clearance, doorway traversal confirmation and optional validated graph nodes/edges |
| `worldmap.archive` | `NSKeyedArchiver` secure ARWorldMap including the expected named ARAnchor |

JSON keys are camelCase. `geometry.json` coordinates use world **X/Z**, in metres, with Y reserved for floor height. This differs from the legacy printing model's X/negative-Z projection: the schemas are isolated, and must not be interchanged without conversion. Heading is clockwise from map negative-Z: heading zero faces negative-Z, positive pi/2 faces positive-X. Bearing is always relative to **phone-facing heading**, never inferred body orientation.

`mapToWorld` maps `(x,z)` to `(cos(yaw)*x - sin(yaw)*z + translationX, sin(yaw)*x + cos(yaw)*z + translationZ)`. Camera poses use the inverse transform, and world heading minus yaw. Captured packages record identity because RoomPlan geometry and the saved world map come from the same live ARSession. Y translation is applied independently. New transforms cannot silently combine independent scans.

The frame anchor is named `touchspace-frame:<lowercase-coordinateFrameId>`; `frameAnchorId` must match its UUID. iOS securely unarchives ARWorldMap and checks this anchor. The backend inspects a bounded binary/XML plist as data and requires the matching anchor to be reachable from an ARWorldMap root. Structural validation **cannot prove** physical relocalization.

Import rejects extra/nested/duplicate ZIP entries, links, oversized packages (64 MB compressed and expanded), JSON over 4 MB, duplicate JSON keys, bad checksums, invalid geometry/references and unsafe confirmed graph edges. No ZIP paths are extracted to disk on import. Packages are immutable once uploaded; a new scan/revision needs a new UUID.

## Localization and guidance

The ARView camera is the primary navigation surface. Routes are real RealityKit entities placed just above the package floor using map-to-world coordinates, with next-waypoint and destination markers. A small optional floor plan uses the same data. A question opens a dismissible sheet and pauses live cues.

The localization gate requires ARKit's restoration/relocalizing event, fresh normal-tracking frames, the exact saved frame anchor/name/transform, plausible camera height inside a scanned room, and at least 1.2 seconds of consistent poses. Archive decoding or normal tracking alone never authorizes navigation. Tracking jumps, interruptions, stale frames or uncertain alignment clear the AR overlay, stop precise cues and require relocalization plus Resume. A watchdog fails restoration after 45 seconds. There is no manual start pose or heading fallback. ARKit drift inside a plausible room cannot always be detected; route projection never corrects that drift.

Swift and Python use the same A* implementation contract and shared fixture at `shared/fixtures/routes.json`. Unknown floor is blocked; furniture and walls receive clearance; only confirmed door gaps open. A confirmed two-room passage may bridge the measured wall thickness only when its two sides meet the associated scanned floor polygons. Transitions between room IDs also require an associated confirmed doorway even if a wall is missing. Diagonal corner cutting is forbidden. Every route segment is sampled at 5 cm; only collision-checked collinear simplification is applied, retaining doorway samples. Default body clearance is 0.3 m and is recorded in the package (supported range 0.2–0.8 m).

Local progress projection drives approach/turn/arrival/phone-heading cues. Off-route separation over 0.8 m for more than two seconds triggers a local reroute, with five-second hysteresis. Announcements are suppressed by maneuver ID; urgent status changes interrupt speech. AVSpeechSynthesizer is independent of backend availability. Optional low-volume stereo waypoint pulses are at least two seconds apart and stop during speech. Speech-only is the default; Mute and Interrupt speech are available.

## Backend and credentials

Map/catalog/chat endpoints are under `/api/touchspace`; the original `/api/scans`, `/api/maps` and printing/voice endpoints retain their contracts. Simulator walkthrough speech also uses the existing `/api/stt` endpoint with a new optional `local_only=true` form field, which selects local Whisper and prohibits cloud-provider fallback. Existing callers retain the Cartesia behavior.

| Method / endpoint | Behavior |
| --- | --- |
| `GET /maps?q=` | Public-only venue search |
| `POST /publishing/session` | Pair using server code plus installation UUID; receive one-hour bearer credential |
| `POST /maps` | Multipart complete package; private default; public requires `publication_consent=true` |
| `GET /maps/{id}` | Manifest and visibility, with private-owner enforcement |
| `GET /maps/{id}/download` | Original complete ZIP, with private-owner enforcement |
| `POST /chat` | Map/session/message plus optional fresh verified pose; grounded answer and validated destination action |

SQLite metadata and immutable ZIPs live in `TOUCHSPACE_DATA_DIR/touchspace`. Demo signing material is created with mode 0600 in `.auth-secret`, unless an explicit random `TOUCHSPACE_AUTH_SECRET` is configured. Keep it stable when restarting or sharing the data directory across workers. Installation IDs and credentials are stored in device-only Keychain storage. Pairing, uploads and chat have small per-host demo rate limits. These are demo credentials, not a production identity/venue-authorization service.

## Provider and grounding

The adapter posts Anthropic `content`, `tool_use`, `tool_result`, `max_tokens` and `input_schema` payloads to `https://openrouter.ai/api/v1/messages`, using bearer auth. It never switches to `/chat/completions`.

The spec's suggested `qwen/qwen3-8b` returned a retirement error during the live smoke test. `qwen/qwen3.7-flash` passed normal text and forced typed-tool/result tests, and is the current configurable default. Thinking is disabled so small token budgets produce answers rather than only reasoning blocks. Configure `TOUCHSPACE_LLM_MODEL`, `TOUCHSPACE_LLM_MAX_TOKENS` (default 500) and `TOUCHSPACE_LLM_TIMEOUT` (default 12 seconds). No image/VLM endpoint or camera image upload is enabled.

The model resolves semantic intent and stable-ID references across bounded conversation history, and may call overview, landmark, nearby, connectivity, bearing, route and comparison tools. Tool names/arguments and spatial outcomes are validated. The loop allows at most three rounds with five calls each; history is capped at eight turns, idle sessions expire and the in-memory catalog is bounded. Overview results are paginated. Logs include token usage and error class, excluding prompts, keys and precise poses. Provider timeout/error falls back to local deterministic interpretation and saved-map facts.

Exact spatial statements are verbalized deterministically from tool results rather than trusting unrestricted model prose. This intentionally prevents a hallucinated final sentence from adding coordinates, directions or routes. Freshness is checked against request receipt (within three seconds, matching frame and verified pose); bearing describes phone orientation at question time. iOS rechecks its current localization and computes a fresh local route before acting on any returned destination ID. Pose verification on the server is a client assertion with geometry/freshness checks, not cryptographic proof of device tracking.

## Automated checks

```sh
cd backend
.venv/bin/python -m pytest
TOUCHSPACE_RUN_LLM_SMOKE=1 .venv/bin/python -m pytest tests/test_touchspace_smoke.py

cd ../ios-scanner
swift test
xcodebuild -project TouchSpace.xcodeproj -scheme TouchSpace \
  -destination 'platform=iOS Simulator,name=iPhone 18 Pro' \
  CODE_SIGNING_ALLOWED=NO test
```

Python tests cover packages/checksums/anchors, traversal, collisions, shared route results, graph-edge rejection, pose orientation/freshness, pairing/private access/public consent, upload/download/chat, provider wire format, multiple typed tools, malformed calls, timeout fallback, history and loop bounds. Swift tests cover the same route fixture, transforms, heading, instruction thresholds/hysteresis, JSON protection, and localization evidence failure/recovery. Unit-test archive doubles are structural fixtures, **not device-restorable maps**.

## Synthetic fixtures without LiDAR

See [the two realistic mock bundles](../sample-data/mock-maps/README.md) for a clinic and library, generation commands, plan previews, route scenarios and optional local catalog seeding. Synthetic bundles use the explicit `synthetic-fixture` provenance and must remain unverified. Their `worldmap.archive` is a versioned, non-restorable binary-plist placeholder with matching frame/anchor IDs and `relocalizable=false`; the package validator recognizes it only for synthetic provenance. The iOS app labels them as interactive demos and provides a dedicated floor-plan explorer plus a full-screen first-person walkthrough. Swipe to turn, use wide chevrons for collision-checked forward/back steps, and hold the microphone to ask the local saved-map assistant. Releasing sends the question and the answer is spoken. Navigation requests draw a validated route from the current virtual pose for manual movement; no overview tab, bottom toolbar or text chat appears in the walkthrough. Physical-device transcription requires microphone/speech permission and an installed speech language. Simulator walkthroughs use local Whisper on the Mac backend because the tested Simulator advertises support for an Apple speech model that cannot load on its CPU. Setup and diagnostics are in the [iOS README](../ios-scanner/README.md). UI automation injects recognized speech; a separate integration run transcribes a real WAV through the local backend and checks the resulting map answer/speech twice. Actual microphone capture and audible playback require a manual check. Simulated poses are a separate non-Codable type and never become verified physical poses. Venue localization and physical navigation remain disabled for fixtures. Real RoomPlan packages still require securely archived ARWorldMap data. The backend refuses live pose-dependent queries and navigation actions for synthetic fixtures. These fixtures support software testing, not the physical checks below.

## Required physical-device validation

These checks cannot be completed in a simulator and have **not been claimed as passed**:

1. Scan and label a real room and adjoining doorway; save, close the app, reopen and restore the package. Verify the saved frame anchor appears after real relocalization.
2. Share/publish from device A, download on device B, and restore at the venue. Confirm archive structural validation accepts Apple's actual captured archive and physically relocalizes.
3. Walk and rotate: floor route, waypoint and destination must remain anchored to the physical space. Check phone-relative Q&A from opposite headings.
4. Follow a validated doorway route around furniture. Confirm unknown/blocked doors and unreachable destinations refuse guidance.
5. Cover the camera, background the app and force tracking loss. AR overlay and precise speech/beacons must stop. Retry, then explicitly Resume.
6. Use VoiceOver and the largest Dynamic Type sizes for import, map exploration, destination selection, asking by text, interrupting speech, pausing, ending, retrying, capture review and sharing. Validate stereo cues with headphones.
7. Check a failed restore at a different venue, poor lighting and an incomplete scan. The app must keep offering map-only exploration without a manual pose shortcut.

This prototype is not certified collision avoidance and does not replace established mobility aids. Multi-zone/floor handoffs, live obstacle sensing, community editing and VLM Q&A remain outside this MVP.
