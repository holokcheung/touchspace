# Touchspace AI — iOS MVP implementation spec

> Coding-agent brief. Build inside the **existing monorepo**. Inspect the iOS target, backend stack, authentication, storage, and API patterns before editing. Follow existing conventions; avoid replacing or restructuring unrelated code. The product name is **Touchspace AI**.

## Goal

An accessible, voice-first iOS app that lets people **download a volunteer-scanned indoor map**, automatically relocalize within it via ARKit, ask conversational spatial questions, and navigate using deterministic routes and directional audio. Volunteers can scan, label, export, and share maps. **No custom tactile hardware is required.**

## MVP user flows

1. **Home / Maps:** Show locally downloaded maps, search shared maps via backend, import a map package from Files/share sheet, and open **Scan a space**. Allow offline access to downloaded map geometry.
2. **Map details:** Show name, coverage, contributor, scan/update date, verification status, landmark list, optional visual floor-plan preview, **Explore map** (works without positioning), and **Start live exploration**.
3. **Automatic positioning:** Load the package's saved `ARWorldMap` into `ARWorldTrackingConfiguration.initialWorldMap`; guide the user to pan the camera and wait for ARKit relocalization. Show/speak `relocalizing`, `localized`, `limited`, or `failed`. **Do not offer manual location/heading entry for this MVP.** Do not claim localization or give precise spatial guidance until tracking is normal and the map coordinate frame is verified. On failure, allow map-only Q&A or retry.
4. **Explore / Navigate:** Persistent prominent **Ask Touchspace AI** mic button plus text input; current room and localization status; optional visual plan with pose/route for demo; destination picker; Start / Pause / End navigation; repeat-instruction button. Support questions like "what is to my right?", "how are the rooms connected?", "how can I get to the exit?". Continue natural-language follow-ups using stable object/room IDs.
5. **Audio cues:** Spoken instructions and basic stereo left/right or waypoint beacon, derived from the **next route waypoint relative to current camera heading**. Start with robust 2D stereo; make advanced 3D/head-tracked audio optional. Provide mute, cue frequency, and speech-only fallback. Do not continuously obscure environmental sounds.
6. **Volunteer scan / publish:** Use the built-in RoomPlan capture UI where practical, preserve its ARSession coordinate frame, name rooms/entrances/landmarks, review graph connectivity, save package locally, share via system share sheet, and optionally upload to the community catalog. Publish only with explicit consent.

## Portable map package (mandatory)

Use one versioned archive, e.g. `<map-id>.touchspacemap` (ZIP), containing:

```text
manifest.json               # schemaVersion, mapId, title, floor/coverage, timestamps,
                            # contributor, verification status, units, coordinate-frame ID
geometry.json               # RoomPlan captured-room/structure geometry + transforms
worldmap.archive            # ARWorldMap serialized with NSSecureCoding/NSKeyedArchiver
landmarks.json              # stable IDs, names, semantic types, positions, room membership
navigation.json             # traversable space/graph, doors, walls, connections (may be derived)
```

- The **geometry, landmarks, graph, and ARWorldMap must refer to the same spatial coordinate frame**. Preserve transforms and any anchors necessary for alignment. Never assume that separately captured rooms or sessions align automatically; initially support one coherent scan/session or a demonstrably aligned multi-room capture.
- Serialize AR world data with `ARSession.getCurrentWorldMap` after checking `worldMappingStatus`; deserialize using secure unarchiving. Test restoring the map in a new session and, if possible, on another device.
- Validate schema/version, archive contents, byte size, file paths, coordinate transforms, and graph connectivity on import/upload. Do not execute instructions from map metadata.
- Since relocalization may fail in altered/unfamiliar surroundings, treat package presence as **necessary, not sufficient** for live positioning. Packages missing valid world data may be kept as local drafts for map-only exploration, but must not masquerade as live-navigable shared packages.
- Consider maps of private indoor spaces sensitive. Require explicit publication consent, show contributor/verification metadata, and don't silently upload camera frames or continuous user pose.

## Spatial engine: deterministic, not LLM-generated

- Convert RoomPlan walls, doors/openings, and object footprints into a **2D navigable representation** (occupancy grid or graph), with appropriate obstacle clearance, valid transitions, and units in meters. Unknown/unscanned space is not assumed walkable.
- Implement **A*** or comparable deterministic search for valid paths, plus waypoint extraction/route smoothing and off-route detection. Reject disconnected/unreachable destinations instead of inventing routes. A detected doorway does not prove it is accessible or open.
- Track `ARFrame.camera.transform`, heading, AR tracking quality, current room, route progress, and next waypoint. Handle phone-facing direction versus body-facing direction explicitly; expose uncertainty.
- Expose typed spatial operations to the LLM: `get_pose`, `list_rooms`, `nearby_landmarks`, `relative_direction`, `room_connections`, `get_route`, `route_summary`, `get_map_overview`. **All distances, geometry, connectivity, and directions must originate in deterministic code.**
- On limited/lost/relocalizing tracking, halt location-dependent guidance and announce uncertainty. Map-level Q&A may continue, clearly detached from live pose.
- The scan is a structural approximation, **not** continuous obstacle sensing or a replacement for a cane/guide dog.

## LLM and audio behavior

- LLM is a conversational interface over the structured map, tool outputs, and (when localized) current pose, **not** the routing or localization engine. Support open-ended map overview, relative-direction questions, destination resolution, and follow-up references. Ground every spatial claim; say "unknown" when map data is insufficient.
- Prefer **backend-hosted LLM calls** (never ship provider secrets in iOS). Include `mapId`, conversation/session ID, user message, and optional current pose/heading/tracking state with each request. Backend loads the server-stored or provided validated map graph and calls deterministic spatial tools. Return reply text, optional structured action (e.g. destination/route), and source IDs/measurements; do not trust free-form model text as a navigation command.
- Live waypoint cues / time-sensitive instructions should be generated locally from route and pose (template speech + stereo audio), not from continuous LLM calls. iOS may use AVSpeechSynthesizer and AVAudioEngine/AVAudioEnvironmentNode as supported by the project.

## Backend changes — isolate from existing modules

Inspect existing routes, auth, DB, object/file storage, dependency injection, and config. Implement a cohesive **`touchspace` feature/module** with its own route prefix, services, persistence models/migrations, tests, and environment keys. Reuse existing shared infrastructure; do not rewrite unrelated backend behavior.

Suggested contract (adapt to established API style):

| Endpoint | Purpose |
|---|---|
| `GET /api/touchspace/maps?q=` | Search/list public maps (metadata only) |
| `POST /api/touchspace/maps` | Upload/validate/publish a package and its metadata |
| `GET /api/touchspace/maps/{id}` | Map details / verification / coverage |
| `GET /api/touchspace/maps/{id}/download` | Download complete package including AR world data |
| `POST /api/touchspace/chat` | LLM session turn with map ID, query, optional validated pose/context; typed spatial-tool results |

- Store package binaries in the project's existing object/file storage (not DB blobs unless that is the repo's only existing pattern); DB stores metadata, ownership, visibility, version, checksum, and storage location. Support explicit private vs public maps. Guard upload sizes/types and access; reject ZIP traversal and incompatible formats.
- Reuse existing user/auth implementation if present. Keep uploads private by default. Public map browsing may be read-only without authentication if consistent with the app; publishing requires authorization or an existing project-appropriate guard.
- Avoid duplicated graph logic if possible: standardize `navigation.json` plus deterministic coordinate/route test vectors, and ensure backend tool queries and iOS guidance agree on map coordinates.
- API contracts and models should be documented or generated per the repo's conventions; add minimal integration tests.

## Accessibility / UI constraints

- SwiftUI native controls if compatible with the existing iOS codebase; full VoiceOver labels, focus order, large touch targets, Dynamic Type. A visual map is **supplemental**, not the only way to inspect or select destinations.
- Speak important state changes once, not continuously. Keep Ask / Repeat / Pause / End accessible during navigation; voice interaction must not be mandatory (typed input fallback).
- Distinguish verified scan facts, volunteer-provided labels, and unknown data. Present clear incomplete-map and tracking-failure warnings.

## Build order / definition of done

**P0:** import/export complete package → show map details → restore ARWorldMap and report honest relocalization status → live pose → deterministic route to a labelled destination → spoken instructions → spatial Q&A grounded in map + pose. Preserve a demoable small venue test map.

**P1:** volunteer scan-and-label UI; publish/search/download packages via isolated backend; basic directional stereo waypoint cues; pause/retry/error states; VoiceOver audit.

**P2 (only if time):** richer 3D audio, user preferences/accessible route weights, multi-floor support, automatic live obstacles, moderation UI, collaborative map editing.

Acceptance checks:
- A volunteer scans and exports an archive containing **both** JSON room geometry and a restorable `ARWorldMap`.
- A separate install/device can import or download it and **attempt automatic relocalization**, with accurate status and no fabricated success.
- After successful relocalization, rotate the phone: "what is to my right?" updates correctly. If tracking is lost, precise guidance stops.
- A* produces a valid route for a reachable destination and explicitly rejects an unreachable one.
- An AI Q&A response uses structured map facts; an unspecified landmark or unknown property does not trigger an invented answer.
- Package search, upload, download, and chat work without breaking existing backend endpoints; new feature code remains isolated.
- VoiceOver users can access the full critical flow without interpreting the visual map.

## Implementation notes

Keep the smallest demonstrable vertical slice working before expanding scope. Inspect existing repository code and environment first, record unavoidable assumptions in the PR, and do not add an unrelated framework or second backend. **Do not claim reliable real-world collision avoidance.**

Relevant Apple references: [ARWorldMap](https://developer.apple.com/documentation/arkit/arworldmap), [Save/load world data](https://developer.apple.com/documentation/arkit/saving-and-loading-world-data), [Multiuser world-map sharing](https://developer.apple.com/documentation/arkit/creating-a-multiuser-ar-experience), [AVAudioEnvironmentNode](https://developer.apple.com/documentation/avfaudio/avaudioenvironmentnode).
