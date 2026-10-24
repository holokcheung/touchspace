# Demo plan (3-minute pitch + 2 minutes of questions)

## Before judging (15 minutes ahead)

1. Start the backend and frontend (see the README). Open http://localhost:5173 in a fresh browser window.
2. Click **Try Demo** once so the backend is warm, then go back to the home page.
3. If Cartesia is configured, confirm `http://localhost:8000/api/health` shows `"cartesia": true` and play one answer, so the browser has allowed audio.
4. Turn the laptop volume up. Close notifications.
5. Have the printed tactile map on the table, cut corner at the top left.
6. Backup: the demo video is open in another tab in case the Wi-Fi or the laptop fails.

## Script

**0:00 – Problem (20 s)**
> "Walking into an unfamiliar building is hard if you can't see it. Floor plans are visual, signs are visual, and tactile maps exist but are rare and expensive, because someone has to design each one by hand."

**0:20 – Idea (15 s)**
> "TouchSpace turns a phone's LiDAR scan of a room into a 3D-printable tactile map automatically, and pairs it with a voice assistant that answers questions about the same space."

**0:35 – Scan to plan (30 s)**
- Upload page → **Try the public RoomPlan sample**.
  > "This is a real RoomPlan export from an iPhone, from a public open-source project. Our importer reads Apple's format, including its 4×4 transforms, and squares up the plan."
- Show the floor plan: rooms labeled "unconfirmed".
  > "We never trust the scanner's guesses. People confirm room names and mark entrances."

**1:05 – Tactile model (35 s)**
- Switch to the **demo building** (Home → Try Demo, clearly labeled synthetic) → **3D tactile map**.
- Rotate it once, then **View from above**.
  > "Raised walls, door gaps widened so a finger can find them, a different shape for each landmark, a legend, and a cut corner so you know which way is up. Every model is checked before download: watertight, one solid piece, fits the printer."
- Click **Download STL**, then hand the judge the printed map.

**1:40 – Voice (50 s)**
- **Voice explorer** tab. Click the mic, or type:
  - *"Where is the restroom?"*
    > Point out that it names the tactile symbol: "the solid circle".
  - *"How do I get there from the main entrance?"*
    > "The route comes from a shortest-path search over walking paths someone recorded. It gives map directions first, because we don't know which way you're facing, then turns, doors, and doorways you pass. It never says a path is clear, and it always reminds you to use your cane."
- If Cartesia is on: "That voice is Cartesia. Without a key it falls back to the browser's voice."

**2:30 – Accessibility and honesty (20 s)**
> "The whole app works by keyboard and screen reader: text descriptions of the plan and the 3D model, announced status updates, and a microphone with audio cues. We haven't tested it with blind users yet, so that's the next step. The tactile sizes are starting points for print testing."

**2:50 – Close (10 s)**
> "Scan a space, feel the layout, explore with confidence. That's TouchSpace."

## Likely questions

- **"Is the demo building real?"** No, it's synthetic and labeled that way. The apartment is a public RoomPlan export from another MIT-licensed project.
- **"How do routes work on a new scan?"** RoomPlan doesn't record walking paths. Someone who knows the space connects places through doorways in the editor, and the app refuses lines through walls.
- **"Does it track the user?"** No. The user picks a starting point. We deliberately don't claim live positioning.
- **"Why not just use a screen reader on a floor plan image?"** Images carry no structure. We turn geometry into structured, queryable data: distances, directions, routes.
- **"Where does the AI come in?"** Cartesia for natural voice and speech-to-text. Optionally Gemini, to interpret free-form questions; it can only pick from places that exist on the map, and the answer itself is computed from map data. Answers are never invented.
- **"Has a blind person tested it?"** Not yet. Be direct about this.
