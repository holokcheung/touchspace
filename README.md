# TouchSpace AI

**Scan a Space. Feel the Layout. Explore with Confidence.**

TouchSpace AI turns real indoor spaces into 3D-printable tactile maps for blind and visually impaired people, and pairs them with a voice assistant that answers questions about the space. Built for Cal Hacks 13.0.

## Workflow

Scan Room (iPhone/iPad LiDAR + RoomPlan) → Export JSON → Upload → Process Geometry → Generate Tactile Map → Preview 3D → Download STL → Print

## Repository layout

| Path | Contents |
| --- | --- |
| `frontend/` | React + TypeScript + Vite web app |
| `backend/` | FastAPI service: scan import, floor-plan processing, and STL generation |
| `ios-scanner/` | SwiftUI RoomPlan scanner app |
| `sample-data/` | Synthetic demo plus a public RoomPlan-shaped fixture |
| `docs/` | Architecture and usage docs |

## Status

| Phase | State |
| --- | --- |
| 1. Data pipeline: normalized schema, synthetic demo, floor-plan processing, tactile STL generator, tests | Done |
| 2. FastAPI endpoints + React web app (upload, 2D editor, 3D preview, STL download, demo mode) | Done |
| 3. Apple RoomPlan import + iOS scanner | Implemented; physical-device build and scan still need verification |
| 4. Voice explorer and routing | Not started |
| 5. Polish and docs | Not started |

The demo building in `sample-data/demo-building.json` is **synthetic**. It is not a scan of any real place.

The public sample in `sample-data/roomplan-real-sample.json` uses the serialized `CapturedRoom`-style fields and is useful for exercising the importer. Its public source does not establish that it was emitted directly by Apple's `JSONEncoder` from a physical LiDAR scan; see [`sample-data/README.md`](sample-data/README.md) for provenance and the file hash. The iOS scanner in `ios-scanner/` encodes Apple's `CapturedRoom` directly, but it has not been built or run on LiDAR hardware in this environment.

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

Open http://localhost:5173 and click **Try Demo**. No API keys are needed.

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
| Upload scan | Drag-and-drop or file picker for scan JSON, parsing errors with details, synthetic demo, public RoomPlan sample, list of saved maps |
| Floor plan | SVG plan with walls, doors, rooms, objects, paths and landmarks. Add, drag, or arrow-key move landmarks. Rename landmarks and rooms, set the starting point, choose which furniture is printed, check the map. Includes a full text description of the plan. |
| 3D tactile map | Interactive 3D model (rotate, zoom, reset, top view), measurements, print checks, print settings with regenerate, **Download STL**, and a text description of the model |

Accessibility: semantic landmarks and headings, skip link, visible focus outlines, labeled inputs, live status messages, keyboard-movable landmarks, text equivalents for both the 2D plan and the 3D model, color never used alone, light and dark themes, and the Atkinson Hyperlegible font.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Health check, plus which optional services are configured |
| POST | `/api/scans` | Upload scan JSON (multipart `file`), then parse, clean up, and save it |
| POST | `/api/demo` | Create an editable copy of the synthetic demo building |
| POST | `/api/samples/roomplan` | Import the checked-in public RoomPlan-shaped fixture |
| GET | `/api/maps` | List saved maps |
| GET / PUT | `/api/maps/{id}` | Read or replace a map. Responses include validation issues and 3D model status. |
| POST | `/api/maps/{id}/generate` | Generate the tactile model, optionally with new `settings` |
| GET | `/api/maps/{id}/model` | Model status (`none` / `ready` / `stale`) and the generation report |
| GET | `/api/maps/{id}/stl` | Download the binary STL |

Errors return `{"error": {"code", "message", "details"}}`. Maps are stored as JSON files under `backend/data/` (gitignored).

## Tactile model, in short

- Flat base (3 mm), with the top-left corner cut off so the reader can tell which way is up.
- Raised walls (2.5 mm tall, 2 mm wide) with door and opening gaps. A gap narrower than 5 mm at print scale is widened so a finger can find it.
- Landmark symbols: triangle = entrance, square = exit, circle = restroom, three bars = stairs, ring = elevator, plus = information. Symbols are moved clear of walls and doorways automatically.
- A legend strip along the bottom edge, plus optional raised dot paths along recorded routes.
- Every model is checked before export: watertight, one connected solid, fits the print area, all features on the base, correct height.

These dimensions are prototype defaults for FDM printing, not an accessibility standard. Blind users have not tested them yet.
