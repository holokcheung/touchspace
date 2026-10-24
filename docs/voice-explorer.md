# Voice Explorer, routing and grounded answers

The Voice Explorer (`/maps/{id}/voice`) answers spoken or typed questions about one map. Answers are built only from that map's data.

## What it can answer

| Ask | Example | Built from |
| --- | --- | --- |
| Overview | "Describe this room." | Map name, size, rooms, entrances, exits, landmarks, starting point |
| Where | "Where is the restroom?" | Landmark position, the room containing it, compass distance to the two nearest places, the editor's description, tactile symbol, distance from the start along paths |
| Nearby | "What is near the entrance?" | Places within 6 m, with direction and distance |
| Directions | "How do I get there from the main entrance?" | Shortest route over recorded paths (Dijkstra) |
| List | "What places are there?" | All landmarks |
| Where am I | "Where am I?" | Says plainly that position isn't tracked, and names the chosen starting point |

Understanding:
- **Synonyms:** bathroom, toilet and washroom mean restroom; lift means elevator; reception and info desk mean information.
- **Small slips:** "restrom" still matches "Restroom".
- **Follow-ups:** "there" refers to the previous answer's place.
- **Ambiguity:** with two similar names, it asks "Did you mean Bedroom 1 or Bedroom 2?".
- **Unknown places:** the answer lists the places it does know.

## What it will not do

- **No invented places, obstacles or routes.** If two places aren't connected by recorded paths, it says so.
- **No position tracking.** The person chooses a starting point.
- **No safety claims.** Directions end with: *"These directions follow the paths recorded on this map. They can't detect obstacles, so keep using your cane, guide dog, or usual travel skills."*
- **Detected places are flagged.** Places RoomPlan only guessed (e.g. "Bathroom (unconfirmed)") say so in answers.

## Directions

`backend/app/services/routing.py`:
- **Graph:** the shortest route uses only `navigation.edges` with `traversable = true`.
- **Avoid stairs:** drops edges marked `has_steps` and nodes linked to a stairs landmark (unless the stairs are the destination). If every route needs stairs, it says so.
- **First leg:** we don't know which way the person faces, so the first leg uses map directions, matching the printed tactile map: *"Head north, toward the top of the map, for about 4.5 meters."*
- **Later legs:** relative turns (*bear left*, *turn right*, *turn around*) from the actual path geometry.
- **Doors:** doorways on the path become *"…to the Restroom door, then go through it."* Doorways passed along a leg are mentioned with their side (*"passing the Meeting Room A door on your left"*).

API:
- `POST /api/maps/{id}/route` with `{origin, destination, avoid_stairs}` (landmark or node ids).
- `POST /api/maps/{id}/ask` with `{question, context}`. Pass back the returned `context` to keep follow-ups working.

## Walking paths for real scans

RoomPlan doesn't produce a navigation graph, so imported scans start with none. In the floor-plan editor, **Walkable paths** lets someone who knows the space:
- connect places and doorways;
- mark a path as having steps;
- remove paths.

A straight line through a wall is refused with a hint to go through the doorway. Doorways are named by what's on each side ("Door between Bathroom and Bedroom 2").

## Gemini (optional)

With `GEMINI_API_KEY` set:
1. The rule parser runs first.
2. Only if it gets nowhere ("I need to wash my hands") is Gemini asked to classify the question. The response schema restricts it to one of our intents and to the map's real place ids.
3. Its output becomes a plain question ("How do I get to Restroom?") that the normal pipeline answers.

Gemini never writes the answer text. Answers it helped with show "Gemini helped interpret this question" in the UI and `understood_by: "gemini"` in the API. Code: `backend/app/services/gemini.py`.

**Not yet verified against the live Gemini API** (no key was available). The default model is `gemini-3.8-flash`, taken from Google's current docs; override it with `GEMINI_MODEL`.

## Voice input and output

The page uses `speak()` and `createListener()` from `frontend/src/lib/voice.ts`: Cartesia when configured, the browser otherwise (see [voice.md](voice.md)).
- **Mic cues:** a rising tone (plus a short vibration on phones that support it) means the mic is open. A falling tone means it closed.
- **Screen readers:** answers also appear in a `role="log"` live region. "Speak answers aloud" can be turned off so it doesn't talk over VoiceOver or NVDA.
