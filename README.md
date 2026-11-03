# TouchSpace

[![Cal Hacks 13.0 Anthropic Track Winner](https://img.shields.io/badge/Cal_Hacks_13.0-Anthropic_Prize_Winner-D4AF37?style=flat-square)](https://devpost.com/software/touchspace)

**Scan a Space. Feel the Layout. Explore with Confidence.**

[![Watch the TouchSpace demo: the web walkthrough alongside a Dot Pad displaying the tactile map](https://github.com/user-attachments/assets/048edcb6-0cf2-4992-b2d2-cbb1808a2591)](https://www.youtube.com/watch?v=zCSkCPO-3cc)

_Watch the TouchSpace demo_


TouchSpace turns indoor spaces into interactive tactile and audio maps for blind and visually impaired people. It helps people learn an unfamiliar place **before visiting**, from the comfort of home, through touch, spatial sound, and a first-person 3D walkthrough.

Built at Cal Hacks 13.0 (2026), where it won Anthropic's **Claude for Public Benefit** prize.

[Project introduction on Devpost](https://devpost.com/software/touchspace) · [Watch the demo](https://www.youtube.com/watch?v=zCSkCPO-3cc)

## What it does

A set of turn-by-turn directions cannot convey the whole layout of a building. TouchSpace brings several ways of exploring the same map together so users can build a spatial understanding and decide where they want to go.

- **Interactive tactile maps:** feel walls, doorway gaps, landmarks, your virtual position, and highlighted routes on a Dot Pad refreshable tactile display.
- **Spatial audio:** hear nearby walls and furniture through stereo sound, with cues for obstacles ahead, doorway crossings, and the edge of the mapped area.
- **3D exploration:** practice moving through a space with keyboard, mouse, or touch controls while a floor plan follows your position.
- **Voice questions:** ask about surroundings, destinations, and routes. Claude helps interpret free-form questions; answers and directions are computed from recorded map data.
- **Community sharing:** capture and label spaces with the iOS app, then share complete map packages for others to download and explore.

The intended workflow is **scan → review and label → share → explore**. The iOS and web apps currently support different map formats; see [map compatibility](#map-compatibility) before transferring a scan between them.

## iOS app

The native SwiftUI app uses Apple RoomPlan and LiDAR on supported iPhones and iPads to capture walls, doorways, floor boundaries, and furniture. Contributors review the floor plan, name rooms and destinations, and confirm passable doorways before saving a `.touchspacemap` package containing geometry, labels, navigation data, and AR world data.

Maps can be shared as files or uploaded to the backend's community catalog from the app. Downloaded maps support offline floor-plan exploration and a virtual 3D walkthrough. Two built-in demo spaces let you try exploration without LiDAR. The iOS voice assistant uses the configured backend and requires an Anthropic API key.

## Web app

The website opens to a library of saved spaces. Choose a map, import a RoomPlan or TouchSpace JSON file, or try a sample to enter the walkthrough. The **Floor plan**, **Audio**, and **DotPad** panels keep visual, auditory, and tactile exploration together.

Use headphones and enable spatial audio in the Audio panel. Sound changes as you approach walls and furniture; movement checks collisions against the mapped geometry. Spoken announcements and a readable map description provide additional context.

| Action | Controls |
| --- | --- |
| Move forward / backward | ↑ / ↓ or W / S |
| Turn left / right | ← / → or A / D; drag the 3D view to look around |
| Turn 90° | Shift + left / right turn key |
| Turn around | T |
| Describe surroundings | E or Enter while focused on the walkthrough |
| Ask a spoken question | Hold Space or the microphone button; release to send |
| Toggle recording accessibly | Focus the microphone button and press Enter |

On-screen movement controls also support touch and holding to repeat. A typed question is available alongside voice input.

Try “Where am I?”, “Where is the restroom?”, or “Take me to the elevator.” Surroundings descriptions use your virtual position and heading. Route answers use the map's recorded path graph, identify their starting landmark, and highlight the route in the 3D view, floor plan, and tactile display. The Floor plan panel includes a starting-location picker and an option to avoid stairs. A recorded route starts at a mapped landmark; it does not include a verified connection from an arbitrary virtual position to that landmark.

## Tactile map

The web app connects directly to a **Dot Pad with a 60 × 40 pin graphic display**. Raised walls, open doorway gaps, landmark symbols, and an X marking the walker update as you explore. Planned routes appear as spaced raised dots. A braille line shows the current room and heading using basic uncontracted English braille.

Open **DotPad** in the walkthrough to see the pin preview, which works without hardware. To use a physical display, open the app in **Chrome on localhost or HTTPS**, choose **Connect Bluetooth** or **Connect USB**, and select the device in the browser picker.

| Control | Effect |
| --- | --- |
| Zoom in / out in the panel | Switch between overview, 2×, and 4× zoom |
| Dot Pad function button 1 / 2 | Zoom out / in |
| Dot Pad function button 3 | Dismiss the highlighted route from all views |
| Lower all pins | Clear the display until the next movement update |

The map stays north up. Overview fits the whole space; zoomed views follow the walker. See the [DotPad guide](frontend/src/dotpad/README.md) for connection troubleshooting, symbols, rendering details, and hardware validation limits.

## Running locally

Requires **Python 3.11+** and **Node.js 20+ with npm**. The web demo needs neither an iPhone nor a Dot Pad, and works without API keys.

### Backend

From the repository root:

```sh
cd backend
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

The API runs at [http://localhost:8000](http://localhost:8000). [Health status](http://localhost:8000/api/health) reports optional service availability; [interactive API documentation](http://localhost:8000/docs) lists the endpoints.

### Frontend

In a second terminal, from the repository root:

```sh
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) and select **Try Demo**. Vite proxies `/api` requests to the backend on port 8000. Imported and demo maps are saved under `backend/data/` by default.

The library also offers:

- **Demo building:** a synthetic layout with labeled destinations and recorded routes.
- **Public RoomPlan sample:** a third-party apartment scan; room labels are unconfirmed. See its [source and license](sample-data/third-party/README.md).
- **Palace of Fine Arts:** an approximate first-floor reconstruction from the Cal Hacks venue's official floor plan. See the [source and limitations](sample-data/palace-of-fine-arts/README.md).

To test JSON import without a phone, choose **Import a scan** and upload [`sample-data/synthetic-roomplan-capturedroom.json`](sample-data/synthetic-roomplan-capturedroom.json).

### Optional voice and Claude configuration

Copy [`.env.example`](.env.example) to `.env` at the repository root and fill in the settings you need. If a `.env` already exists, update it rather than replacing it. Restart the backend after changing settings. Keys stay on the backend.

| Setting | Purpose |
| --- | --- |
| `ANTHROPIC_API_KEY` | Enables Claude interpretation of web questions and the iOS map assistant |
| `CARTESIA_API_KEY` | Enables web speech recognition and synthesis through Cartesia |
| `CARTESIA_VOICE_ID` | Optionally selects a Cartesia voice |
| `TOUCHSPACE_INTERPRETER_MODEL` | Overrides the web question interpreter's Claude model |
| `TOUCHSPACE_LLM_MODEL` | Overrides the iOS assistant's Claude model |
| `TOUCHSPACE_PUBLISH_CODE` | Enables pairing and uploads to the iOS community catalog |

Without provider keys, the web app still supports typed questions, rule-based map answers, local surroundings descriptions, and browser speech where available. Browser speech support varies; typed input remains available. The iOS assistant requires an online backend with `ANTHROPIC_API_KEY` configured.

The backend reads `backend/.env` before the root `.env`; existing process environment variables take precedence over both. Additional storage, CORS, speech, and publishing settings are documented in [`.env.example`](.env.example).

### iOS setup

On a Mac with Xcode and the iOS SDK installed:

1. Open [`ios-scanner/TouchSpace.xcodeproj`](ios-scanner/TouchSpace.xcodeproj), select the **TouchSpace** scheme, and set your development team under **Signing & Capabilities**.
2. Run on an iOS 17+ device. RoomPlan capture requires a LiDAR-equipped iPhone or iPad; the simulator can explore bundled demo maps.
3. To connect a physical phone, start the backend with `.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000` from `backend/`. Set the app's backend URL to `http://<Mac-LAN-IP>:8000` on the same network, or `http://localhost:8000` for the simulator.
4. For community uploads, set `TOUCHSPACE_PUBLISH_CODE` on the backend, restart it, and pair through **Map detail → Upload or publish**. Maps are private by default; public publishing requires explicit consent.

The Xcode project is checked in; XcodeGen is only needed to regenerate it. See the [iOS guide](ios-scanner/README.md) for native testing and optional local Whisper transcription for simulator voice input. The current provider configuration is [`.env.example`](.env.example): iOS chat uses `ANTHROPIC_API_KEY` directly.

### Checks and builds

Run each command from the directory shown:

| Directory | Command | Purpose |
| --- | --- | --- |
| `backend/` | `.venv/bin/python -m pytest` | Backend tests |
| `frontend/` | `npm test` | Frontend tests |
| `frontend/` | `npm run build` | Type-check and build the web app |
| `ios-scanner/` | `swift test` | Portable core tests on macOS |

For a standalone web walkthrough, run `npm run build:walk` in `frontend/`. It creates `frontend/dist-walk/touchspace-walk.html` with bundled sample maps, 3D exploration, spatial audio, and the DotPad module. Its assistant describes local surroundings; questions about other places and routes require the main app. Serve it on localhost or HTTPS for hardware access.

## Map compatibility

The two clients currently use separate map formats and catalogs:

| Client | Import format | Backend API |
| --- | --- | --- |
| Web walkthrough | RoomPlan `CapturedRoom` / `CapturedStructure` JSON or normalized TouchSpace `FloorMap` JSON | `/api/scans`, `/api/maps`, and `/api/maps/{id}/ask` |
| iOS app | Complete `.touchspacemap` ZIP packages | `/api/touchspace/maps` and `/api/touchspace/chat` |

**The website does not currently import `.touchspacemap` packages or browse the iOS community catalog.** The iOS scanner saves packages rather than exporting the JSON format accepted by the website. Completing that handoff is part of the intended scan-to-tactile workflow; the web samples and JSON importer can be used independently today.

## Repository layout

| Path | Contents |
| --- | --- |
| [`frontend/`](frontend/) | React, TypeScript, Vite, and Three.js walkthrough; spatial audio and DotPad integration |
| [`backend/`](backend/) | FastAPI service for map import, storage, spatial questions, routes, speech, and the community catalog |
| [`ios-scanner/`](ios-scanner/) | SwiftUI and RoomPlan capture, map review, package sharing, and exploration |
| [`sample-data/`](sample-data/) | Synthetic fixtures, third-party scan, and venue reconstruction with provenance |
| [`shared/`](shared/) | Soundscape configuration and spatial test fixtures |
| [`docs/`](docs/) | Additional design and implementation notes; some describe earlier project directions |

## Current status

TouchSpace is a hackathon prototype. Full scan-to-tactile integration, capture on real devices, and tactile readability still need further validation.

The web walkthrough is virtual practice using recorded maps. It does not track a visitor's physical position or detect live obstacles. Maps may be partial or outdated, and recorded routes do not establish accessibility. TouchSpace is not a replacement for a cane, guide dog, or other mobility aid.

Next steps include connecting the iOS package workflow to web exploration, validating the complete workflow on real hardware, and testing with blind and visually impaired users. Broader mapping coverage, richer braille labels, and support for additional tactile displays remain future work.
