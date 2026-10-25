# TouchSpace AI

**Scan a Space. Feel the Layout. Explore with Confidence.**

TouchSpace AI turns real indoor spaces into 3D-printable tactile maps for blind and visually impaired people, and pairs them with a voice assistant that answers questions about the space. Built for Cal Hacks 13.0.

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
| `shared/` | Settings shared by the web app and the iPhone app (`soundscape.json`) |
| `docs/` | Architecture and usage docs |

## Status

| Phase | State |
| --- | --- |
| 1. Data pipeline: normalized schema, synthetic demo, floor-plan processing, tactile STL generator, tests | Done |
| 2. FastAPI endpoints + React web app (upload, 2D editor, 3D preview, STL download, demo mode) | Done |
| 3. Apple RoomPlan import + iOS scanner | Importer done and tested on synthetic data. Native app builds for simulator; capture and saved-world restore still require device validation. |
| 4. Voice explorer and routing | Done: routing over recorded paths, grounded Q&A, Voice Explorer page, path editor, Cartesia voice, optional Gemini |
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

Open http://localhost:5173 and click **Try Demo**. No API keys are needed. To use Cartesia voice, see [docs/voice.md](docs/voice.md).

To try the RoomPlan import path without an iPhone, upload `sample-data/synthetic-roomplan-capturedroom.json`. It is synthetic data in RoomPlan's format. For real scans, see [ios-scanner/README.md](ios-scanner/README.md) and [docs/roomplan-import.md](docs/roomplan-import.md).

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

| Page | What it does |
| --- | --- |
| Home | Product overview, **Get Started**, **Try Demo**, tactile symbol key |
| Upload scan | Drag-and-drop or file picker for scan JSON, parsing errors with details, demo scan, list of saved maps |
| Floor plan | SVG plan with walls, doors, rooms, objects, paths and landmarks. Add, drag, or arrow-key move landmarks. Rename landmarks and rooms, set the starting point, choose which furniture is printed, check the map. Includes a full text description of the plan. |
| Voice explorer | Ask by voice or text: descriptions, where things are, what's nearby, step-by-step directions over recorded paths. Answers are spoken (Cartesia or the browser), shown as text, and drawn on the plan. |
| Walk-through | Practice walking through the map with headphones, by keyboard or touch. Each ear's noise is muffled when a wall or furniture is close on that side; ticks mean something is in your path; doors, rooms and landmarks are announced. Simulated from the map, not live sensing. Works on a phone over Wi-Fi. |
| 3D tactile map | Interactive 3D model (rotate, zoom, reset, top view), measurements, print checks, print settings with regenerate, **Download STL**, and a text description of the model |

Accessibility: semantic landmarks and headings, skip link, visible focus outlines, labeled inputs, live status messages, keyboard-movable landmarks, text equivalents for both the 2D plan and the 3D model, color never used alone, light and dark themes, and the Atkinson Hyperlegible font.

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

- [docs/voice-explorer.md](docs/voice-explorer.md): routing, grounded answers, the path editor, Gemini
- [docs/soundscape.md](docs/soundscape.md): the walk-through's sound design, shared settings, using it on a phone, plan for live LiDAR
- [docs/voice.md](docs/voice.md): Cartesia setup
- [docs/roomplan-import.md](docs/roomplan-import.md): RoomPlan format and coordinates
- [docs/ACCESSIBILITY_CHECKLIST.md](docs/ACCESSIBILITY_CHECKLIST.md): run before the demo
- [docs/DEMO.md](docs/DEMO.md): 3-minute pitch script and likely questions
- [docs/DEVPOST.md](docs/DEVPOST.md): submission draft

## Tactile model, in short

- Flat base (3 mm), with the top-left corner cut off so the reader can tell which way is up.
- Raised walls (2.5 mm tall, 2 mm wide) with door and opening gaps. A gap narrower than 5 mm at print scale is widened so a finger can find it.
- Landmark symbols: triangle = entrance, square = exit, circle = restroom, three bars = stairs, ring = elevator, plus = information. Symbols are moved clear of walls and doorways automatically.
- A legend strip along the bottom edge, plus optional raised dot paths along recorded routes.
- Every model is checked before export: watertight, one connected solid, fits the print area, all features on the base, correct height.

These dimensions are prototype defaults for FDM printing, not an accessibility standard. Blind users have not tested them yet.
