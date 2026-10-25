# TouchSpace — iOS + Backend MVP Specification

**For coding agent · Existing monorepo · Implementation brief**

## Objective

Build an **AR-first, VoiceOver-accessible iOS indoor exploration app**. Volunteers scan and label spaces with RoomPlan, upload a portable map containing **geometry and saved ARKit world data**, and publish it to a searchable community catalog.

Visitors download the package, **automatically relocalize** in the venue, ask map-grounded questions through the backend LLM, and follow **camera-overlay AR routes with spoken and directional audio cues**.

Keep routing and live guidance deterministic, not LLM-generated.

**Before implementation:** Inspect current iOS targets and actual backend code; retain working conventions and APIs. The supplied backend is a reference snapshot and may differ from the checked-out tree. Focus on a working vertical slice, not refactoring unrelated code.

## 1. User Journeys and Interface

### Home
- Search community maps.
- View downloaded maps.
- Import a `.touchspacemap` file.
- **Scan space**.
- Downloaded geometry must remain browsable offline.

### Map Detail
- Venue/floor, coverage, contributor, verification and recency.
- Simple top-down floor plan.
- Named rooms and destinations.
- **Explore map** (no live position required).
- **Start AR navigation**.

### Auto-Locate
- Start ARKit with the package's `ARWorldMap` as `initialWorldMap`.
- Present camera preview and accessible instructions to look around.
- Expose **Relocalizing / Localized / Tracking limited / Failed**, with Retry and **Map-only exploration**.
- **No manual start-position/heading fallback.**
- Do not assert success merely because the world-map archive loads or tracking becomes `normal`. Verify the expected coordinate-frame anchor, consistent pose/room alignment, and fresh tracking.
- Suspend live navigation if alignment is uncertain.

### AR Explore / Navigate (Primary Screen)
- Full-screen live camera view with a **floor-aligned 3D route line**, waypoint/turn marker, and destination marker (RealityKit/ARKit or existing AR renderer).
- Overlay a compact top status: venue, localization, destination, remaining distance, and next action.
- Persistent bottom controls:
  - **Ask** (microphone and text alternative)
  - **Repeat**
  - **Pause/Resume**
  - **End**
  - **Destinations**
- Collapsible top-down minimap for sighted testers.
- AR graphics supplement, **never replace**, voice guidance.
- Do not cover the camera with a chat transcript by default; use a small dismissible transcript sheet.

### Scanner / Publisher
- Native RoomPlan capture.
- Add room.
- Review geometry and doorway links.
- Label destinations.
- Save package locally.
- Share via iOS share sheet.
- Optionally publish to the community catalog (private by default; explicit consent to make public).
- Support partial scans with honest coverage labels.

### Accessibility
- Native large SwiftUI controls.
- Proper VoiceOver labels and focus order.
- Dynamic Type support.
- Status announcements without excessive chatter.
- Text-input alternative.
- Accessible destination picker.
- Nonvisual feedback for every visually drawn route cue.
- Allow users to interrupt speech, pause cues, or inspect a map without walking.

## 2. Package and Scan-to-Map Pipeline

**Reuse the existing `.touchspacemap` ZIP contract** (`backend/app/touchspace/models.py`, `package.py`):

```text
manifest.json        map ID, floor/coverage, coordinateFrameId,
                     frameAnchorId, provenance

geometry.json        normalized room polygons, walls,
                     obstacle footprints, transforms

landmarks.json       stable named destinations/room associations

navigation.json      nodes, door links, traversability,
                     clearance, edges

worldmap.archive     securely archived ARWorldMap,
                     including frame anchor
```

### Requirements

- Capture RoomPlan geometry and `ARSession.getCurrentWorldMap` **in the same coherent coordinate frame**.
- Preserve the named `touchspace-frame:<coordinateFrameId>` anchor expected by the current package validator.
- Follow the existing **X/Z world-plane** and heading conventions.
- Persist any explicit transforms used to align scan/route/world coordinates.
- Do not silently assume independently scanned rooms align.
- For MVP, prioritize one contiguous same-session zone; multi-zone transforms and per-zone world-map handoff are an extension.
- Export/import with iOS secure `NSKeyedArchiver`/`NSKeyedUnarchiver`, compatible with the backend's structural archive checks.
- The backend cannot prove an archive relocalizes: test actual device restore and anchor matching.
- Normalize real RoomPlan walls, object footprints, room polygons, and openings.
- Add volunteer-confirmed traversal and semantic labels.
- Reject paths through unscanned areas and doors whose traversability is unknown.
- Generate a top-down visual plan from the same geometry and graph.
- Reuse existing ZIP size/path/JSON/schema protections, checksums, visibility, and private/public controls.
- Maps of private spaces must never publish automatically.

## 3. Live AR Localization and Navigation

### Localization

- Load stored `ARWorldMap` through `ARWorldTrackingConfiguration.initialWorldMap`.
- Subscribe to camera transforms, tracking state, and relocalization events.
- Convert camera position and phone-facing heading into the shared map frame, applying recorded rigid transforms where needed (cf. BlindSpot/InView).
- Distinguish **phone heading** from the user's body heading.
- On failed/degraded alignment, remove or freeze AR route overlays, stop precise audio instructions, and offer retry.
- Route-progress projection does **not** correct ARKit drift.

### Planning

Build a **~10 cm occupancy grid** from RoomPlan floor polygons, walls, and furniture (InView pattern).

- Inflate obstacles by configurable human/device clearance.
- Open only validated doorway passages.
- Mark unknown cells blocked.
- Generate a navigable graph/grid.
- Use **A*** for a fixed destination.
- Dijkstra may be used to evaluate multiple candidate destinations.
- Smooth routes only where the entire replacement segment is collision-free.
- Retain door and turn waypoints.

Existing `app.touchspace.spatial.SpatialEngine` already validates graph edges and runs A*: **extend/reuse it** rather than introduce a conflicting route truth.

Keep iOS route guidance and backend tool results consistent with the package graph and shared route test fixtures.

Optionally record a walked trajectory (~0.75 m samples; Gnarly pattern) as **provisional** connections, but never override scanned obstacles without explicit confirmation.

### AR Visualization

- Render a clearly contrasting line/segments just above the detected floor to avoid z-fighting.
- Include next waypoint, turn cue, and destination anchor.
- Draw using route waypoints in the **same AR world frame**, updated from camera pose.
- Do not fake a screen-space line.
- Gracefully hide overlays when tracking is unavailable.
- A route summary must remain accessible via speech.

### Instruction Engine (Local, Deterministic)

- Project current pose onto route segments.
- Track along-path progress.
- Detect off-route deviations.
- Reroute with hysteresis.

Start with configurable thresholds inspired by BlindSpot/InView:

- **~25–30°** to announce a turn.
- **~60°** for a substantial turn.
- Approach warning **~4 m** before maneuver.
- Then turn-now, arrival, and heading-correction prompts.

Additional requirements:

- Suppress repeated announcements.
- Prioritize urgent status changes.
- Interrupt queued nonurgent speech when necessary.
- Use `AVSpeechSynthesizer` as a reliable local fallback.
- Existing backend voice facilities may enhance narration but must not gate navigation.

### Directional Sound

- Basic stereo/3D waypoint beacon based on **relative bearing to the next waypoint**.
- Make optional with Speech-only and Mute modes.
- Avoid constant audio that masks environmental sounds.
- Do not call an LLM every frame.

## 4. Backend Integration — Use Existing TouchSpace Module

The reference backend **already** contains:

- `app.touchspace.api`
- `app.touchspace.models`
- `app.touchspace.package`
- `app.touchspace.storage`
- `app.touchspace.spatial`
- `app.touchspace.chat`
- SQLite catalog
- Package upload validation

### Existing API Endpoints

| Endpoint | iOS Use |
|---|---|
| `GET /api/touchspace/maps?q=` | Search public community maps |
| `POST /api/touchspace/maps` | iOS package upload; `visibility`, `publication_consent` |
| `GET /api/touchspace/maps/{id}` | Map metadata |
| `GET /api/touchspace/maps/{id}/download` | Download complete package including AR data |
| `POST /api/touchspace/chat` | LLM-assisted, map-grounded Q&A and destination actions |

**Extend these endpoints/models as necessary; do not create a parallel route namespace or duplicate the catalog.**

Preserve the original scan/print API and isolate new changes to `app.touchspace` and the iOS feature.

### Frontend–Backend Data Flow

**Map upload:**

iOS → Backend map package upload → Validation → Storage → Community catalog

**AI Q&A:**

iOS message + map ID + fresh verified pose → Backend map lookup/context enrichment + spatial tools/LLM → Grounded answer + optional typed navigation action → iOS local route guidance

Never ship LLM keys or a permanent server-wide upload token inside the app. Implement a safe demo publishing credential mechanism consistent with available authentication.

## 5. AI-Native Q&A and Model Provider

Replace the Gemini-specific client in `app.touchspace.chat` with a small **Anthropic Messages-compatible** adapter.

### Provider Configuration

Target OpenRouter's Anthropic-compatible endpoint:

```text
POST https://openrouter.ai/api/v1/messages
Authorization: Bearer $OPENROUTER_API_KEY
```

The test API key is already provided in `backend/.env`.

Implementation requirements:

- Inspect the existing variable name without printing the secret.
- Update backend settings to load `backend/.env` if needed.
- Note that `app.main` currently reads the repository-root `.env` only.
- Prefer existing process environment variables over dotenv values.
- Never expose the key to iOS, logs, tests, or committed files.
- Remove the old `TOUCHSPACE_GEMINI_*` settings dependency.
- Adjust the current model-name validator to accept OpenRouter IDs containing `/`.

Use the Anthropic Messages wire format:

- `content` blocks
- `tool_use`
- `tool_result`
- `max_tokens`
- `input_schema`

Do **not** use the OpenAI-style `/chat/completions` response format.

If using an Anthropic SDK rather than `httpx`, verify its base URL and bearer-auth settings against OpenRouter's documentation.

### Cheap Configurable Test Models

Suggested configuration:

```env
TOUCHSPACE_LLM_MODEL=qwen/qwen3-8b
TOUCHSPACE_VLM_MODEL=qwen/qwen3-vl-8b-instruct
```

- Text LLM: conversational Q&A and spatial tool calling.
- VLM: optional, user-initiated still-image understanding.

These are inexpensive OpenRouter options, not required final choices.

Confirm actual Anthropic Messages/tool compatibility with the selected model/provider through a smoke test. If unsupported, choose another inexpensive compatible model via configuration rather than silently changing API protocol.

There is no frame streaming and no VLM dependence for geometry or routing.

### Backend LLM Orchestration

Upgrade the current one-operation interpreter to support:

- Multi-turn semantic exploration.
- Stable-ID reference resolution.
- Multiple typed spatial tool calls.
- Overview queries.
- Nearby landmarks.
- Room connectivity.
- Relative bearing.
- Route comparison.
- Bounded tool loop (e.g. maximum 3 rounds).

The backend should:

1. Load the requested stored map package.
2. Enrich context with map geometry, semantic labels, and fresh verified pose.
3. Interpret the user's request using the LLM.
4. Execute the selected spatial tools deterministically.
5. Feed verified tool outputs back to the model.
6. Generate a natural-language response grounded in those results.
7. Return validated structured actions when navigation is requested.

**Coordinates, distances, traversability, and directions come exclusively from `SpatialEngine` and typed tools.**

The LLM must not invent locations, routes, live obstacles, or tracking confidence.

Additional requirements:

- Validate tool names and arguments.
- Handle unknown or unverified information explicitly.
- Validate structured navigation actions before returning them.
- Fall back to deterministic replies when the provider times out or fails.

### Preserve Existing Integration

Keep `POST /api/touchspace/chat` and existing request/response contracts where possible.

iOS sends:

- Map ID
- Session ID
- User message
- Fresh verified pose, when available

Do not continuously upload position updates.

Any optional image must be sent only after explicit user action, subject to privacy and size limits.

Model-derived observations remain unverified until corroborated.

### Testing and Cost Controls

Add mock-provider unit tests and opt-in integration smoke tests using the key already in `backend/.env`.

Minimum tests:

- One normal text Q&A request.
- One typed spatial tool invocation.
- One VLM image test, only if image Q&A is enabled.

Implement:

- API timeouts.
- Small configurable `max_tokens`.
- Bounded conversation history.
- Bounded tool-call loops.
- Model selection through environment variables.
- Usage and error-class logging.

Do not log API keys, camera images, prompts, or precise user positions by default.

## 6. Acceptance Criteria and Delivery Order

### P0 — Core Functionality

- Import/export a valid complete map package.
- RoomPlan scan and semantic labeling.
- Restore saved ARWorldMap across sessions.
- Automatic relocalization with verified coordinate-frame anchor.
- AR camera-overlay waypoint route using validated A* geometry.
- Local deterministic speech instructions.
- Backend map-grounded Q&A through the Anthropic-compatible OpenRouter endpoint.
- Live pose-dependent queries, including left/right orientation.
- All critical actions accessible through VoiceOver.

### P1 — Sharing and Enhanced Navigation

- Upload/search/download public maps using existing endpoints.
- Optional stereo waypoint beacon.
- Reliable off-route rerouting.
- Speech prioritization.
- Tracking/error recovery.
- Private-by-default publishing.
- iOS share-sheet support.

### P2 — Further Enhancements

- Multi-zone/floor world-map handoffs.
- Richer 3D head-tracked audio.
- Live obstacle sensing.
- Alternative route preferences.
- Community map editing.

## 7. Demonstration and Tests

The finished MVP should demonstrate:

1. **Map sharing:** Publish a scan on one device and load it on another.
2. **Localization:** Relocalize using saved AR world data.
3. **AR tracking:** Rotate or move while the route remains physically anchored.
4. **Routing:** Follow instructions through a doorway without the calculated path crossing walls or furniture.
5. **AI spatial Q&A:** Change heading and receive correspondingly different, grounded answers.
6. **Tracking loss:** Deliberately lose tracking and verify that precise AR/audio guidance stops.
7. **Failure handling:** An impossible route or ambiguous landmark produces an honest refusal or clarification.
8. **LLM integration:** Verify that the OpenRouter Anthropic-compatible endpoint supports the selected model's tool-calling workflow.

Add unit tests for graph algorithms, coordinate transforms, and provider response handling, plus API integration tests.

**Safety:** Do not market the system as certified collision avoidance or a replacement for established mobility aids.