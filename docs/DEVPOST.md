# Devpost draft: TouchSpace AI

*Edit freely. Every claim below is something the code does today. Keep the "not yet" items honest.*

**Tagline:** Scan a space. Feel the layout. Explore with confidence.

## Inspiration
Indoor spaces are designed to be seen: floor plans, signs, maps by the door. Tactile maps help blind and low-vision people build a mental picture of a building before and while they explore it, but they're rare because each one is designed by hand. Phones with LiDAR can already capture a room's geometry in a minute. We wanted to connect the two: turn a scan into a map you can feel, and let people ask questions about the same space by voice.

## What it does
- **Scan:** a SwiftUI iOS app wraps Apple's RoomPlan and exports the room exactly as RoomPlan encodes it, with a USDZ preview. It can send the scan to the web app over Wi-Fi.
- **Import and clean up:** the backend reads RoomPlan JSON, including column-major 4×4 transforms, doors linked to their walls, floors, and room-type guesses. It projects everything onto a 2D plan, snaps corners, and squares the plan to the page.
- **Edit:** an accessible floor-plan editor to confirm room names, mark entrances, exits and restrooms, choose which furniture to print, and record walkable paths. Paths through walls are refused.
- **Print:** one click generates a printable tactile STL:
  - raised walls on a base plate;
  - door gaps widened so fingers can find them;
  - six distinct landmark symbols (triangle entrance, square exit, circle restroom, bars for stairs, ring for elevator, plus for information);
  - a legend, and a cut corner for orientation.

  Every model is checked before download: watertight, one solid piece, fits the print bed.
- **Explore by voice:** ask "Where is the restroom?" or "How do I get there from the main entrance?". Answers are built only from the map. Directions come from a shortest-path search over recorded walking paths, and always remind you to keep using your cane or guide dog. Voice runs on Cartesia (Sonic text-to-speech, Ink speech-to-text), with the browser's own speech as a fallback.

## How we built it
- **Backend:** Python, FastAPI, Pydantic, NumPy, Shapely for 2D geometry, Trimesh and Manifold for 3D solids and STL export.
- **Frontend:** React, TypeScript, Vite, Tailwind, and React Three Fiber for the 3D preview. The 2D editor is a hand-built SVG renderer with keyboard support.
- **iOS:** Swift, SwiftUI, RoomPlan.
- **Voice:** Cartesia API (server-side key), Web Speech fallback, audio cues for the mic.
- **Optional Gemini:** interprets free-form questions, restricted by a JSON schema to the map's own place ids. It never writes answers.
- **Tests:** 140+ backend tests (geometry, mesh checks, RoomPlan transforms, fuzzed noisy scans, routing, Q&A, API) and 20+ frontend tests.

## Challenges we ran into
- **RoomPlan's coordinate system:** getting from Y-up world space to a floor plan that isn't mirrored, from column-major matrices, while scans start at arbitrary headings.
- **Noisy coordinates:** real scan coordinates made the 3D boolean union fail until we snapped geometry to a 1 µm grid.
- **Real walls aren't parallel:** a real apartment scan has walls a few degrees off each other. Averaging them left every wall crooked; a weighted median fixed it.
- **Never inventing anything:** making the assistant useful without ever inventing a room, an obstacle-free path, or someone's location.

## Accomplishments we're proud of
- A full pipeline from scan to printable STL, checked automatically.
- Directions that are honest about what they can't know.
- An interface that works by keyboard and screen reader end to end, with text equivalents for the plan and the 3D model.

## What we learned
*(team to fill in)*

## What's next
- **Testing with blind and low-vision users:** we haven't done this yet, and it's the most important next step.
- **Print testing:** validate wall height, gap width and symbol size on real prints.
- **Braille labels:** generated only once they can be verified.
- **Multi-room scans:** stitch scans across rooms and floors, and suggest walkable paths automatically, with human confirmation.

## Built with
python · fastapi · pydantic · numpy · shapely · trimesh · manifold3d · react · typescript · vite · tailwindcss · three.js · react-three-fiber · swift · swiftui · roomplan · cartesia · gemini

## Honesty notes (keep in the submission)
- The demo building is synthetic. The apartment is a public RoomPlan export from another MIT-licensed open-source project.
- The iOS app has not yet been built and run on a LiDAR device during this hackathon. *(Update this if your team does.)*
- No testing with blind users yet.
- AI coding assistants were used during development. *(Disclose this if Cal Hacks rules ask.)*

## Prize tracks to select
Cal Hacks Overall · Best People-First Social Impact Hack · Best Use of Cartesia · Best Hardware Hack (bring the print) · [Microsoft] Built for the Real World · [MLH] Best Use of Gemini API (only if a Gemini key was used live)
