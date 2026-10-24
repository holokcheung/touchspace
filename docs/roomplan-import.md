# RoomPlan import

`backend/app/services/roomplan.py` converts Apple RoomPlan JSON into the TouchSpace map format (`FloorMap`). Everything downstream (floor-plan cleanup, tactile STL, routing, voice) only sees `FloorMap`.

## Input

The JSON that `JSONEncoder().encode(capturedRoom)` produces on the device: a `CapturedRoom`, or a `CapturedStructure`. For a structure, the merged top-level lists are used if present; otherwise each room in `rooms` is merged.

Encoding facts the importer relies on, from Apple's documentation and observed exports:

| Field | Encoding |
| --- | --- |
| `walls`, `doors`, `windows`, `openings`, `floors` | `CapturedRoom.Surface` |
| `objects` | `CapturedRoom.Object` |
| `sections` (iOS 17+) | `{label, center, story}`: room-type guesses |
| `category`, `confidence`, section `label` | Single-key objects, e.g. `{"wall": {}}`, `{"door": {"isOpen": true}}`, `{"high": {}}`. Plain strings are also accepted. |
| `transform` | `simd_float4x4` as **16 floats, column-major**. Column 0 is local x (along a wall), column 1 is up, column 2 is the normal, column 3 is the element's center. |
| `dimensions` | `[width, height, depth]` in meters. Depth is 0 for surfaces. |
| `parentIdentifier` | For doors, windows and openings: the identifier of their wall |
| `polygonCorners` | Floor outline (and non-rectangular walls) in the element's local frame |

## Coordinate conversion

RoomPlan uses ARKit world space: meters, +Y up, right-handed. The world's heading depends on how the phone was held when scanning started.

- Each wall's endpoints are its transform applied to the local points `(±width/2, 0, 0)`. The full matrix is used, not just the translation, so rotated walls come out right.
- World → plan: `x = X`, `y = −Z`. This is the view from above, not mirrored: looking down −Y with +X to the right, −Z points up the page.
- An object's plan rotation is the heading of its local x axis: `atan2(−u.z, u.x)`. Its footprint is `dimensions[0]` × `dimensions[2]`.
- Floors become room outlines by transforming each `polygonCorners` point. If there are no corners, the floor's width and depth are used instead.
- After import, the floor-plan processor:
  - rotates the plan so the main walls run along the page edges;
  - snaps nearly-meeting corners together;
  - attaches doors that have no `parentIdentifier` to the nearest wall;
  - moves the plan to the origin.

## What is deliberately *not* inferred

- **Wall thickness:** RoomPlan surfaces have none. A 0.15 m default is used, and the tactile model uses its own wall width anyway.
- **Room names:** each recognized section (`bedroom`, `bathroom`, `kitchen`, `livingRoom`, `diningRoom`) becomes a *detected* named area, such as "Bedroom 2 (unconfirmed)", at its center. A floor outline takes a section's name only when that is the only kind of area inside it. Otherwise it's "Room 1", "Room 2", and so on. A `bathroom` guess is never turned into a restroom landmark.
- **Entrances, exits, restrooms:** never assumed. The editor asks the user to mark them.
- **Stairs:** a `stairs` object becomes a *detected* stairs landmark that says it needs confirming.
- **Walkable routes:** RoomPlan has no navigation graph, so imported maps start with an empty one.
- **Furniture on the print:** every object is left off the tactile model until the user opts in.

## Robustness

- The plan is squared to the page using the length-weighted *median* wall direction. Real scans have groups of walls a few degrees apart, and averaging them would leave every wall slightly crooked.
- Elements that can't be read (wrong-length transform, non-finite numbers, zero width) are skipped, and the upload response lists the problems. If no wall is usable, the upload fails with details.
- Tilted or curved walls produce warnings. Curved walls are straightened to their chord.
- Tactile generation snaps 2D geometry to a 1 µm grid before extruding. Scan coordinates carry float noise that otherwise makes degenerate triangles.

## Tests and fixtures

- `sample-data/synthetic-roomplan-capturedroom.json` is **synthetic** data in RoomPlan's format: a 7 × 5 m room, rotated 23° and shifted. It carries `_touchspace_synthetic: true`, so imports are labeled synthetic. Regenerate it with `python sample-data/scripts/make_synthetic_roomplan.py`.
- `backend/tests/test_roomplan.py` covers:
  - column-major decoding and the no-mirroring rule;
  - recovery at five scan headings;
  - object rotation;
  - `parentIdentifier` mapping;
  - structure merging;
  - bad-element handling;
  - 12 randomized noisy scans that must all produce printable models;
  - upload through the API.

- `sample-data/third-party/open3dfloorplan-test-roomplan.json` is a **public RoomPlan export** from another MIT-licensed project (see `sample-data/third-party/README.md`). It is a 2-bedroom apartment with 20 walls, 4 doors, 4 windows and 13 objects, and it imports and prints cleanly. Real exports encode section labels as plain strings (`"bedroom"`), and the importer accepts both forms.

**Still to do:** import a scan made by the team with the TouchSpace iOS app, and add it as another regression fixture (with permission from whoever owns the space).
