# TouchSpace

**Scan a Space. Feel the Layout. Explore with Confidence.**

TouchSpace turns real indoor spaces into 3D-printable tactile maps for blind and visually impaired people, and pairs them with a voice assistant that answers questions about the space. Built for Cal Hacks 13.0.

## Native iOS AR app

The SwiftUI app now lives in [`ios-scanner/`](ios-scanner/README.md). It captures RoomPlan geometry and AR world data in one `.touchspacemap` package, supports offline map exploration, and restores the saved frame for camera-overlay navigation with local speech. Complete bundles use `/api/touchspace/maps`; the original JSON scan/print API below remains available.

See [setup, architecture and physical-device validation](docs/IOS_MVP.md). Simulator builds and automated tests do not validate real-world relocalization or capture; those require a physical device at the scanned venue.

## Workflow

Scan Room (iPhone/iPad LiDAR + RoomPlan) → Export JSON → Upload → Process Geometry → Generate Tactile Map → Preview 3D → Download STL → Print

## Repository layout

| Path | Contents |
| --- | --- |
| `frontend/` | React + TypeScript + Vite web app |
| `backend/` | FastAPI service: RoomPlan import, floor-plan processing, STL generation, routing, voice Q&A |
| `ios-scanner/` | SwiftUI RoomPlan scanner app |
| `sample-data/` | Synthetic demo fixtures (not real venue scans) |
| `shared/` | Web soundscape settings and shared spatial test fixtures |
| `docs/` | Architecture and usage docs |

## Status

| Phase | State |
| --- | --- |
| 1. Data pipeline: normalized schema, synthetic demo, floor-plan processing, tactile STL generator, tests | Done |
| 2. FastAPI endpoints + React web app | Done; web UI consolidated into a space library and first-person walkthrough. Editing and STL APIs remain on the backend. |
| 3. Apple RoomPlan import + iOS scanner | Importer done and tested on synthetic data. Native app builds for simulator; capture and saved-world restore still require device validation. |
| 4. Voice and routing | Recorded-path routing and grounded Q&A are integrated into the walkthrough with hold-Space voice input and typed fallback. Cartesia and optional Gemini remain supported. |
| Walk-through soundscape | Done on the web: walk the map with headphones, and the noise is muffled on the side of a nearby wall. Settings shared with the iPhone app; live LiDAR version not built. |
| 5. Polish and docs | Not started |

The demo building in `sample-data/demo-building.json` is **synthetic**. It is not a scan of any real place.

## Running it locally

Requires Python 3.11+ and Node 20+.

**1. Backend** (FastAPI on port 8000):

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

**2. Frontend** (Vite on port 5173, proxies `/api` to the backend), in a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 and click **Try Demo** to enter the walkthrough. No API keys are needed. Optional voice and chat provider settings are listed in [.env.example](.env.example); keep provider keys on the backend.

To try the RoomPlan import path without an iPhone, upload `sample-data/synthetic-roomplan-capturedroom.json`. It is synthetic data in RoomPlan's format. For real scans, see [ios-scanner/README.md](ios-scanner/README.md) and [the iOS implementation guide](docs/IOS_MVP.md).

**Tests:**

```bash
cd backend && .venv/bin/python -m pytest
cd frontend && npm test
```

**STL from the command line** (no server needed):

```bash
cd backend
.venv/bin/python -m app.cli generate ../sample-data/demo-building.json -o demo.stl --set wall_height_mm=3
```

## Web app

The web app centers on **practicing navigation**. Choose a saved space, import a
RoomPlan/TouchSpace JSON map, or try a demo, then enter a full-screen first-person
Three.js walkthrough. Old editor, print preview and voice-explorer links redirect into
the walkthrough. The backend's editing and tactile/STL APIs remain available.

- **Move:** arrow keys or W/S and A/D. Shift turns 90°, T turns around. Drag to look;
  hold the on-screen movement controls on touch devices. Collision checks use the
  same walls, doorway gaps and furniture as the audio simulation.
- **Ask:** hold **Space** while speaking and release to send, or hold the microphone.
  Enter on the microphone toggles recording for keyboard/assistive-technology users.
  A typed question is always available. Speech uses Cartesia when configured, with
  browser recognition/synthesis fallbacks. Local surroundings answers use the exact
  virtual position and heading; other questions use the existing grounded map Q&A.
- **Floor plan:** a collapsible side panel follows your position and shows recorded
  routes, landmarks, a start-location picker, stair avoidance and a readable/spoken
  map description. Routes explicitly identify the recorded landmark they start from;
  they do not invent a path from an arbitrary virtual point to the graph.
- **Spatial audio:** headphone noise muffles near walls/furniture on either side,
  ticks warn about obstacles ahead, and doorway/bump/out-of-map cues remain.
  Sound ducks while you use the assistant. Volume and spoken announcements live in
  the Audio panel.
- **DotPad:** the authoritative web [module](frontend/src/dotpad/README.md) retains the pin
  preview and uses the vendor Web SDK 3.0.4 to send graphics and room/heading braille
  to a 60 × 40 pin DotPad over Bluetooth or USB. Hardware needs Chrome on localhost
  or HTTPS; physical-device validation is still required. It connects directly from
  the walkthrough, with no Python gateway or iOS bridge.

The separate floor-plan/path editing, print settings, STL download, marketing sections,
and standalone Voice Explorer UI have been removed from the web navigation. Map
import, both samples, saved maps, keyboard/touch controls, audio cues, text descriptions,
and grounded Q&A remain together in the navigation workflow.

`npm run build:walk` still produces a self-contained HTML walkthrough with bundled
maps, 3D, audio and the DotPad module. Without a backend its assistant describes local
surroundings; connected map Q&A requires the main app. This is virtual practice from
recorded maps, not live position tracking or obstacle sensing.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Health check, plus which optional services are configured |
| POST | `/api/scans` | Upload scan JSON (multipart `file`), then parse, clean up, and save it |
| POST | `/api/demo` | Create an editable copy of the synthetic demo building |
| GET | `/api/maps` | List saved maps |
| GET / PUT | `/api/maps/{id}` | Read or replace a map. Responses include validation issues and 3D model status. |
| POST | `/api/maps/{id}/route` | Shortest route between two places over recorded paths, with spoken directions |
| POST | `/api/maps/{id}/ask` | Answer a question using only this map's data |
| POST | `/api/tts` | Speak text with Cartesia (503 means use the browser voice) |
| POST | `/api/stt` | Transcribe a recording with Cartesia |
| POST | `/api/maps/{id}/generate` | Generate the tactile model, optionally with new `settings` |
| GET | `/api/maps/{id}/model` | Model status (`none` / `ready` / `stale`) and the generation report |
| GET | `/api/maps/{id}/stl` | Download the binary STL |

Errors return `{"error": {"code", "message", "details"}}`. Maps are stored as JSON files under `backend/data/` (gitignored).

## More docs

- [iOS setup and testing](ios-scanner/README.md): scanning, demo walkthroughs and speech
- [iOS implementation guide](docs/IOS_MVP.md): map packages, localization and device validation
- [Product specification](docs/SPEC.md): native app and backend requirements
- [DotPad module](frontend/src/dotpad/README.md): browser hardware setup and validation
- [Soundscape settings](shared/soundscape.json): web audio and movement configuration

## Tactile model, in short

- Flat base (3 mm), with the top-left corner cut off so the reader can tell which way is up.
- Raised walls (2.5 mm tall, 2 mm wide) with door and opening gaps. A gap narrower than 5 mm at print scale is widened so a finger can find it.
- Landmark symbols: triangle = entrance, square = exit, circle = restroom, three bars = stairs, ring = elevator, plus = information. Symbols are moved clear of walls and doorways automatically.
- A legend strip along the bottom edge, plus optional raised dot paths along recorded routes.
- Every model is checked before export: watertight, one connected solid, fits the print area, all features on the base, correct height.

These dimensions are prototype defaults for FDM printing, not an accessibility standard. Blind users have not tested them yet.
