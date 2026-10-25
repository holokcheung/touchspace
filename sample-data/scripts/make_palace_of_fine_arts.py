"""Write sample-data/palace-of-fine-arts.json: the first floor of the Palace of Fine Arts exhibition
hall, San Francisco (the Cal Hacks venue), simplified for a 60 x 40 pin DotPad.

Traced by hand from the venue's public floor plan (palaceoffinearts.com, "PFA Master Floorplan",
first floor), in that drawing's pixel coordinates, then scaled to meters with the building's
length in OpenStreetMap (about 274 m end to end; (c) OpenStreetMap contributors, ODbL).
APPROXIMATE: walls are simplified to the outer shell so it reads at DotPad size; every named
area is a spoken landmark. Rotated so north is up (the venue's plan has west up).

Run from the repo root:  python sample-data/scripts/make_palace_of_fine_arts.py
"""

from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTS = [ROOT / "palace-of-fine-arts.json", ROOT.parent / "frontend" / "standalone" / "maps" / "palace-of-fine-arts.json"]

M_PER_PX = 273.8 / 1038.8  # OSM building length / the same length on the plan page


def pt(px: float, py: float) -> tuple[float, float]:
    """Plan page pixels -> meters with north up. On the venue's plan, page right is north (Marina
    Blvd) and page down is east (Baker St), per the compass on its parking page."""
    return round(py * M_PER_PX, 2), round(px * M_PER_PX, 2)


# ---- outer shell, clockwise from the west end (page pixels)
OUTER = [(57, 215), (200, 170), (330, 148), (450, 140), (560, 150), (650, 182), (750, 222), (850, 285),
         (910, 350), (960, 415), (1010, 470), (1050, 520)]
EAST_END = [(985, 548), (905, 572), (860, 605), (835, 570)]
INNER = [(800, 505), (770, 470), (720, 425), (630, 382), (550, 345), (450, 328), (350, 340), (250, 362), (160, 392)]
SHELL = OUTER + EAST_END + INNER  # closes back to (57, 215)

walls: list[dict] = []


def add_wall(wid: str, a, b, thickness: float = 0.3) -> None:
    walls.append({"id": wid, "start": dict(zip("xy", pt(*a))), "end": dict(zip("xy", pt(*b))), "thickness": thickness})


for i, (a, b) in enumerate(zip(SHELL, SHELL[1:] + SHELL[:1])):
    add_wall(f"w_shell_{i:02d}", a, b, 0.4)

# The enclosed rooms (round Breakouts 1-2, Breakouts 3-4, staff offices) stay as named areas below
# but get no walls: at about 7 m per pin they would fill the narrow hall with a clump of pins.
C, R = (505, 250), 45
ring = [(C[0] + R * math.cos(2 * math.pi * k / 12), C[1] + R * math.sin(2 * math.pi * k / 12)) for k in range(12)]
STAFF = [(650, 215), (760, 240), (812, 330), (795, 360), (745, 345), (645, 300)]

wall_by_id = {w["id"]: w for w in walls}


def door_on(did: str, px: float, py: float, width_m: float, kind: str = "door") -> dict:
    """A gap centered on the wall nearest the given page point."""
    x, y = pt(px, py)
    best = None
    for w in walls:
        ax, ay, bx, by = w["start"]["x"], w["start"]["y"], w["end"]["x"], w["end"]["y"]
        L2 = (bx - ax) ** 2 + (by - ay) ** 2
        t = max(0.0, min(1.0, ((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / L2))
        qx, qy = ax + t * (bx - ax), ay + t * (by - ay)
        d = math.hypot(x - qx, y - qy)
        if best is None or d < best[0]:
            best = (d, w["id"], qx, qy)
    _, wid, qx, qy = best
    return {"id": did, "position": {"x": round(qx, 2), "y": round(qy, 2)}, "width": width_m, "wall_id": wid}


doors = [
    door_on("d_public_entrance", 355, 343, 4.0),
    door_on("d_business_entrance", 950, 559, 6.0),
    door_on("d_loading", 393, 142, 4.0),
]

# ---- named areas. Small rooms first: the first polygon containing a point names it.
def poly(points) -> list[dict]:
    return [dict(zip("xy", pt(*p))) for p in points]


def band(x0: float, x1: float) -> list:
    """Shell area between two page x values, outer arc then inner arc."""
    o = [p for p in OUTER if x0 <= p[0] <= x1]
    i = [p for p in INNER if x0 <= p[0] <= x1]
    return [(x0, _y_at(OUTER, x0))] + o + [(x1, _y_at(OUTER, x1)), (x1, _y_at(INNER[::-1], x1))] + i + [(x0, _y_at(INNER[::-1], x0))]


def _y_at(line, x: float) -> float:
    for (ax, ay), (bx, by) in zip(line, line[1:]):
        if min(ax, bx) <= x <= max(ax, bx) and ax != bx:
            return ay + (by - ay) * (x - ax) / (bx - ax)
    return line[-1][1]


rooms = [
    {"id": "r_breakout12", "name": "Breakouts 1 and 2", "polygon": poly(ring)},
    {"id": "r_breakout3", "name": "Breakout 3", "polygon": poly([(570, 210), (648, 232), (640, 266), (559, 252)])},
    {"id": "r_breakout4", "name": "Breakout 4", "polygon": poly([(559, 252), (640, 266), (632, 300), (548, 292)])},
    {"id": "r_staff", "name": "Staff offices (no access)", "polygon": poly(STAFF)},
    {"id": "r_pavilion", "name": "Pavilion", "polygon": poly(band(57, 240) )},
    {"id": "r_atrium", "name": "Atrium", "polygon": poly(band(240, 420))},
    {"id": "r_broadway1", "name": "Broadway 1", "polygon": poly(band(420, 600))},
    {"id": "r_broadway2", "name": "Broadway 2", "polygon": poly(band(600, 740))},
    {"id": "r_broadway3", "name": "Broadway 3", "polygon": poly([(750, 222), (850, 285), (880, 318), (790, 490), (770, 470), (720, 425)])},
    {"id": "r_east", "name": "East wing", "polygon": poly([(880, 318), (910, 350), (960, 415), (1010, 470), (1050, 520)] + EAST_END + [(800, 505), (790, 490)])},
]


def landmark(lid: str, name: str, kind: str, px: float, py: float, description: str) -> dict:
    x, y = pt(px, py)
    return {"id": lid, "name": name, "type": kind, "position": {"x": x, "y": y}, "description": description, "source": "manual"}


landmarks = [
    landmark("lm_public_entrance", "Public entrance", "entrance", 355, 333, "Main public doors on the lagoon side, facing the rotunda."),
    landmark("lm_business_entrance", "Business entrance", "entrance", 950, 548, "Doors at the east end, next to the theater."),
    landmark("lm_loading", "Loading doors", "other", 393, 152, "Loading doors on the Palace Drive side."),
    landmark("lm_palace_games", "Palace Games", "room", 668, 207,
             "Escape rooms along the Palace Drive wall, past the restrooms and catering prep. Their own public door is on Palace Drive."),
    landmark("lm_restroom_north", "Restrooms by catering prep", "restroom", 572, 185, "Restrooms on the Palace Drive side, next to Palace Games."),
    landmark("lm_restroom_east", "Restroom, east end", "restroom", 1000, 500, "Restroom at the east end, near Breakout 7."),
    landmark("lm_restroom_south", "Restroom by the business entrance", "restroom", 878, 580, "Restroom beside the business entrance."),
    landmark("lm_stairs", "Stairs to the mezzanine", "stairs", 862, 425, "Stairs up to the mezzanine, between Breakout 5 and Breakout 7."),
    landmark("lm_theater", "Theater", "room", 852, 532, "Performing arts theater near the business entrance."),
    landmark("lm_pavilion", "Pavilion", "room", 210, 257, "Open area at the west end of the hall."),
    landmark("lm_green_rooms", "Green rooms", "room", 120, 327, "Small rooms at the west end."),
    landmark("lm_atrium", "Atrium", "room", 328, 284, "Open area just inside the public entrance."),
    landmark("lm_catering", "Catering prep", "room", 487, 176, "Catering prep area on the Palace Drive side."),
    landmark("lm_breakout1", "Breakout 1", "room", 482, 238, "West half of the round room."),
    landmark("lm_breakout2", "Breakout 2", "room", 527, 262, "East half of the round room."),
    landmark("lm_breakout3", "Breakout 3", "room", 597, 243, "North room of the block east of the round room."),
    landmark("lm_breakout4", "Breakout 4", "room", 590, 282, "South room of the block east of the round room."),
    landmark("lm_broadway1", "Broadway 1", "room", 463, 300, "Main floor south of the round room."),
    landmark("lm_broadway2", "Broadway 2", "room", 650, 338, "Main floor in the middle of the hall."),
    landmark("lm_broadway3", "Broadway 3", "room", 755, 387, "Main floor toward the east end."),
    landmark("lm_back_of_house", "Available back of house", "room", 527, 336, "Back-of-house space along the lagoon wall."),
    landmark("lm_breakout5", "Breakout 5", "room", 838, 378, "Room beside the stairs."),
    landmark("lm_breakout6", "Breakout 6", "room", 773, 440, "Room along the lagoon wall near the east end."),
    landmark("lm_breakout7", "Breakout 7", "room", 925, 432, "Room at the east end."),
    landmark("lm_staff", "Staff offices (no access)", "room", 712, 290, "Staff offices along the Palace Drive wall. No access."),
]

floor_map = {
    "schema_version": "1.0",
    "id": "palace-of-fine-arts",
    "name": "Palace of Fine Arts, first floor",
    "units": "meters",
    "source": {
        "kind": "manual",
        "description": "Traced from the Palace of Fine Arts public floor plan (palaceoffinearts.com) and scaled with "
                       "OpenStreetMap (c) OpenStreetMap contributors. Approximate and simplified for the DotPad. "
                       "North up.",
    },
    "floor_level": 0,
    "walls": walls,
    "doors": doors,
    "openings": [],
    "windows": [],
    "objects": [],
    "rooms": rooms,
    "landmarks": landmarks,
    "start_landmark_id": "lm_public_entrance",
}

if __name__ == "__main__":
    text = json.dumps(floor_map, indent=2) + "\n"
    for out in OUTS:
        out.write_text(text)
        print(f"wrote {out}")
