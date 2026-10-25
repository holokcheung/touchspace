# Synthetic TouchSpace map bundles

Two fictional venues for testing without a LiDAR device. These are **not scans of real places**. Both import in the iOS app, browse offline, share as complete ZIPs, and support an interactive 3D walkthrough with collision-checked movement and spoken questions/guidance. The catalog and map-grounded Q&A endpoints also accept them. No provider key is needed to generate or validate them.

| Bundle | Layout and test cases | Plan |
| --- | --- | --- |
| [Harbour Community Clinic](harbour-clinic.touchspacemap) | 150 m²; 6 rooms, 6 destinations, 11 furniture footprints. Waiting/reception, corridor, consultation, accessible restroom, treatment and staff supplies. Staff supplies is unreachable because its only door is unknown. | [Floor plan](harbour-clinic.svg) |
| [Neighbourhood Library](neighbourhood-library.touchspacemap) | 160 m²; 4 rooms, 7 destinations, 8 furniture footprints. Returns, children's room, reading room and three long shelf rows. A blocked shortcut forces a detour, two “Study desk” labels test clarification, and a staff door leads beyond the partial scan. Includes a nonidentity map-to-world transform. | [Floor plan](neighbourhood-library.svg) |

The geometry uses metre-scale X/Z coordinates, wall thickness 0.15 m, body clearance 0.30 m and grid resolution 0.10 m. Furniture footprints, confirmed/unknown/blocked doorway states and explicit validated graph edges are included. Each ZIP contains exactly the normal five package files, with correct SHA-256 checksums. The adjacent folders contain readable copies plus `route-scenarios.json` with layout-only starting positions, expected distances/waypoints and impossible-route cases.

## Import on iOS

Build the updated app, then choose **Import from community** and select either `.touchspacemap` file. You can transfer the files using Files, AirDrop or a share sheet. The map displays **Synthetic fixture · Interactive demo**. The updated app also bundles both files: **Try demo spaces** on Home opens a chooser for both venues without transferring files. Select **Start 3D walkthrough** or **Explore floor plan**; the chooser appears on every tap, including when the bundles are already downloaded.

- **Explore map** opens an interactive floor plan, destination/room list and offline route previews between saved places.
- **3D walkthrough** opens directly into a full-screen first-person scene. Swipe left/right to turn and use the wide up/down chevrons to step forward/back. Walls, furniture, unknown areas and unconfirmed doors block movement. The overview tab and bottom toolbar have been removed.
- **Hold to ask** records while the microphone is held; release to submit. Answers are spoken, without a chat transcript. Questions use the local saved-map assistant, without a map upload or API key. Ask where a destination is, what's nearby, which way it lies relative to the virtual camera, or “Take me to Treatment bed.” Navigation requests draw a validated yellow route for you to follow manually. Ambiguous labels require clarification; impossible routes are refused.
- On a physical iPhone, voice requires microphone/speech permissions and an on-device speech language. In the Simulator, voice uses offline Whisper on your Mac through the configured backend; run the [local speech setup](../../ios-scanner/README.md) first. Audio is processed locally, never sent to a cloud provider, and deleted after transcription. Approve initial microphone permission and hold again. UI tests inject speech; a separate integration test transcribes a real WAV through the local server.

Floor geometry and routes come from the bundle; 3D wall/furniture heights are illustrative because the portable geometry contains floor footprints.

The explicit `synthetic-fixture` provenance keeps these maps unverified. `worldmap.archive` contains a small, versioned binary-plist **placeholder** with matching frame/anchor IDs and `relocalizable=false`. It does not contain an Apple ARWorldMap, feature points, camera imagery or fabricated scan data. Real scan packages still require the usual secure ARWorldMap archive. Merely relabeling a fixture as a real scan fails archive validation.

**Physical venue localization and live navigation remain disabled for these maps.** Simulated navigation does not require a fabricated ARWorldMap. Virtual poses have a separate type and are never encoded as verified tracking or sent to the backend. These fixtures cannot test restored-world alignment or real venue guidance. The backend still refuses live-pose actions on fixtures, even if a client submits `verified=true`.

## Test community search and Q&A locally

Optionally seed the two fictional venues into the **local demo catalog**:

```sh
# Run from the repository root. Seeding is explicit and safe to repeat.
backend/.venv/bin/python sample-data/scripts/make_mock_bundles.py --seed-catalog

# In another terminal, from backend/:
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

This uses the configured local data directory; it makes no HTTP upload and publishes nothing to a remote service. The local catalog entries are public so the app's **Search community** can discover them. Search for `synthetic`, `clinic` or `library`, then download and explore. Configure the app's backend URL as usual. Existing entries with these fixed IDs are retained on repeated seeding.

Example questions (spoken in the walkthrough, or sent to the backend chat endpoint):

- Clinic: “Describe the map”; “Where is Reception desk?”; “What is near Reception desk?”
- Library: “Where is Returns desk?”; “Where is Study desk?” (clarification expected).
- In the 3D walkthrough: “Navigate to Main entrance” (a simulation route action only). The backend API continues to refuse physical navigation on synthetic fixtures.

To test upload rather than local seeding, pair with your server and use **Upload or publish**. Synthetic maps retain their provenance on upload/download. As with real maps, uploads default to private and public uploads require explicit consent.

## Regenerate and verify

```sh
# Deterministic geometry, UUIDs, archive placeholders, checksums and ZIP timestamps.
backend/.venv/bin/python sample-data/scripts/make_mock_bundles.py

# Includes import/checksum/placeholder, routing, catalog and Q&A checks; no paid API calls.
cd backend
.venv/bin/python -m pytest tests/test_mock_bundles.py
```

Generation validates both bundles using the same production package validator and SpatialEngine. The source generator is [make_mock_bundles.py](../scripts/make_mock_bundles.py). No local catalog mutation occurs unless `--seed-catalog` is supplied.
