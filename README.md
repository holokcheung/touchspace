# TouchSpace AI

**Scan a Space. Feel the Layout. Explore with Confidence.**

TouchSpace AI turns real indoor spaces into 3D-printable tactile maps for blind and visually impaired people, and pairs them with a voice assistant that answers questions about the space. Built for Cal Hacks 13.0.

## Workflow

Scan Room (iPhone/iPad LiDAR + RoomPlan) → Export JSON → Upload → Process Geometry → Generate Tactile Map → Preview 3D → Download STL → Print

## Repository layout

| Path | Contents |
| --- | --- |
| `frontend/` | React + TypeScript + Vite web app |
| `backend/` | FastAPI service: RoomPlan import, floor-plan processing, STL generation, routing, voice Q&A |
| `ios-scanner/` | SwiftUI RoomPlan scanner app |
| `sample-data/` | Synthetic demo fixtures (not real venue scans) |
| `docs/` | Architecture and usage docs |

## Status

| Phase | State |
| --- | --- |
| 1. Data pipeline: normalized schema, synthetic demo, floor-plan processing, tactile STL generator, tests | Done |
| 2. FastAPI endpoints + React web app | Not started |
| 3. Apple RoomPlan import + iOS scanner | Not started |
| 4. Voice explorer and routing | Not started |
| 5. Polish and docs | Not started |

The demo building in `sample-data/demo-building.json` is **synthetic**. It is not a scan of any real place.

## Backend quick start

Requires Python 3.11+.

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

Generate a printable STL from the demo map:

```bash
cd backend
.venv/bin/python -m app.cli generate ../sample-data/demo-building.json -o demo.stl
```

Override print settings with `--set`, for example `--set wall_height_mm=3 --set include_paths=true`.

## Tactile model, in short

- Flat base (3 mm), with the top-left corner cut off so the reader can tell which way is up.
- Raised walls (2.5 mm tall, 2 mm wide) with door and opening gaps. A gap narrower than 5 mm at print scale is widened so a finger can find it.
- Landmark symbols: triangle = entrance, square = exit, circle = restroom, three bars = stairs, ring = elevator, plus = information. Symbols are moved clear of walls and doorways automatically.
- A legend strip along the bottom edge, plus optional raised dot paths along recorded routes.
- Every model is checked before export: watertight, one connected solid, fits the print area, all features on the base, correct height.

These dimensions are prototype defaults for FDM printing, not an accessibility standard. Blind users have not tested them yet.
