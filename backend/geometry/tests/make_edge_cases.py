"""Generate edge_cases/*.json: one file per way a real RoomPlan scan can go wrong.

Run from the project folder:  python tests/test_edge_cases.py  (creates the cases if missing)
Each case is described in CASES below together with what the correct result must be.
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)                      # so "import config" finds the main code
SAMPLES = os.path.join(ROOT, "samples")

import json, math, os

OUT = os.path.join(ROOT, "tests", "edge_cases")


# ---------- helpers that write RoomPlan-style surfaces ----------
def _surface(cat, p0, p1, height=2.5, depth=0.0, rot_deg=0.0, story=0, nested=False):
    """Surface from map point p0 to p1 (metres). rot_deg rotates the whole scan."""
    r = math.radians(rot_deg)
    def rot(x, y):
        return math.cos(r) * x - math.sin(r) * y, math.sin(r) * x + math.cos(r) * y
    (x0, y0), (x1, y1) = rot(*p0), rot(*p1)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    L = math.hypot(x1 - x0, y1 - y0)
    a = math.atan2(y1 - y0, x1 - x0)
    ux, uy = math.cos(a), math.sin(a)
    cols = [[ux, 0, -uy, 0], [0, 1, 0, 0], [uy, 0, ux, 0], [cx, height / 2 + 3.0 * story, -cy, 1]]
    t = cols if nested else [v for c in cols for v in c]
    return {"category": cat, "dimensions": [L, height, depth], "transform": t,
            "story": story, "curve": None}


def wall(p0, p1, **kw):
    return _surface({"wall": {}}, p0, p1, **kw)


def door(p0, p1, **kw):
    return _surface({"door": {"isOpen": False}}, p0, p1, height=2.0, **kw)


def obj(cat, c, w, d, **kw):
    return _surface({cat: {}}, (c[0] - w / 2, c[1]), (c[0] + w / 2, c[1]), height=0.8, depth=d, **kw)


def box_walls(x0, y0, x1, y1, **kw):
    return [wall((x0, y0), (x1, y0), **kw), wall((x1, y0), (x1, y1), **kw),
            wall((x1, y1), (x0, y1), **kw), wall((x0, y1), (x0, y0), **kw)]


def save(name, room):
    with open(os.path.join(OUT, name + ".json"), "w") as f:
        json.dump(room, f, indent=1, allow_nan=True)


def main():
    os.makedirs(OUT, exist_ok=True)

    # 01 Only walls. No doors, objects, sections or windows keys at all.
    save("01_only_walls", {"walls": box_walls(0, 0, 4, 3)})

    # 02 No walls. A failed scan. Must stop with a clear message, not a crash.
    save("02_no_walls", {"walls": [], "doors": [], "objects": [obj("bed", (1, 1), 2, 1.5)]})

    # 03 Other encodings: category as plain string, transform as nested 4x4 list.
    r = {"walls": box_walls(0, 0, 4, 3, nested=True),
         "doors": [door((1.5, 0), (2.4, 0), nested=True)]}
    r["doors"][0]["category"] = "door"
    save("03_other_encodings", r)

    # 04 Zero-length and tiny wall fragments mixed into a normal room.
    r = {"walls": box_walls(0, 0, 4, 3) + [wall((2, 1.5), (2, 1.5)), wall((1, 1), (1.04, 1)),
                                         wall((3, 2), (3, 2.06))]}
    save("04_tiny_fragments", r)

    # 05 Broken numbers: one wall has NaN in its transform.
    r = {"walls": box_walls(0, 0, 4, 3)}
    bad = wall((0, 1), (4, 1))
    bad["transform"][12] = float("nan")
    r["walls"].append(bad)
    save("05_nan_values", r)

    # 06 Two floors in one file (multi-story scan). Floor 1 is a different shape.
    r = {"walls": box_walls(0, 0, 4, 3, story=0) + box_walls(1, 1, 7, 5, story=1),
         "doors": [door((1.5, 0), (2.4, 0), story=0)]}
    save("06_two_floors", r)

    # 07 A curved wall (iOS 17+ can report curves). We draw it straight but must warn.
    r = {"walls": box_walls(0, 0, 4, 3)}
    r["walls"][1]["curve"] = {"radius": 2.0, "startAngle": 0.0, "endAngle": 1.0}
    save("07_curved_wall", r)

    # 08 Walls overshoot the corners by 15 cm (crossing like a # sign).
    o = 0.15
    r = {"walls": [wall((-o, 0), (4 + o, 0)), wall((4, -o), (4, 3 + o)),
                   wall((4 + o, 3), (-o, 3)), wall((0, 3 + o), (0, -o))]}
    save("08_overshoot_corners", r)

    # 09 Door detected 12 cm off the wall line. Gap must still be cut through the wall.
    r = {"walls": box_walls(0, 0, 4, 3), "doors": [door((1.5, 0.12), (2.4, 0.12))]}
    save("09_door_off_wall", r)

    # 10 The same wall detected twice, 4 cm apart. Must not become a double-thick wall.
    r = {"walls": box_walls(0, 0, 4, 3) + [wall((0, 0.04), (4, 0.04))]}
    save("10_duplicate_wall", r)

    # 11 Whole scan rotated 44 degrees (close to the ambiguous 45).
    r = {"walls": box_walls(0, 0, 5, 3, rot_deg=44),
         "doors": [door((2, 0), (2.9, 0), rot_deg=44)]}
    save("11_rotated_44", r)

    # 12 Very large space (25 m x 15 m). Does not fit the printer bed at 1:50.
    save("12_too_big", {"walls": box_walls(0, 0, 25, 15)})

    # 13 Very small room (1.2 m x 1.0 m closet) with a narrow 0.6 m door.
    save("13_tiny_room", {"walls": box_walls(0, 0, 1.2, 1.0), "doors": [door((0.3, 0), (0.9, 0))]})

    # 14 Furniture overlapping a wall, and furniture seen through a window outside the room.
    r = {"walls": box_walls(0, 0, 4, 3),
         "objects": [obj("sofa", (2, 0.2), 2, 0.9), obj("table", (8, 1.5), 1.2, 0.8)]}
    save("14_objects_outside", r)

    # 15 A real non-square room: one corner is 82 degrees. Must NOT be forced to 90.
    a = math.radians(82)
    p = (4 + 3 / math.tan(a), 3)
    r = {"walls": [wall((0, 0), (4, 0)), wall((4, 0), p), wall(p, (0, 3)), wall((0, 3), (0, 0))]}
    save("15_real_82_degree_corner", r)

    # 16 Opening (doorway without a door) listed under "openings" instead of "doors".
    r = {"walls": box_walls(0, 0, 4, 3),
         "openings": [_surface({"opening": {}}, (4, 1), (4, 2), height=2.0)]}
    save("16_opening_only", r)

    # ---- found by reading the code line by line (cases 17-24) ----
    import copy
    base = {"walls": box_walls(0, 0, 4, 3), "doors": [door((1.5, 0), (2.4, 0))]}

    # 17 File saved with a UTF-8 BOM (e.g. edited in Windows Notepad) and a non-English label.
    r = copy.deepcopy(base)
    r["sections"] = [{"label": "침실 bedroom", "center": [2, 0, -1.5], "story": 0}]
    with open(os.path.join(OUT, "17_bom_and_korean_text.json"), "w", encoding="utf-8-sig") as f:
        json.dump(r, f, ensure_ascii=False)

    # 18 An object whose category is an empty {}.
    r = copy.deepcopy(base)
    o = obj("bed", (2, 1.5), 2, 1.5)
    o["category"] = {}
    r["objects"] = [o]
    save("18_empty_category", r)

    # 19 "story" written as text instead of a number.
    r = copy.deepcopy(base)
    r["walls"][0]["story"] = "ground"
    save("19_story_as_text", r)

    # 20 The file is a list of rooms instead of one room.
    with open(os.path.join(OUT, "20_list_of_rooms.json"), "w") as f:
        json.dump([base, {"walls": box_walls(4, 0, 7, 3)}], f)

    # 21 Transforms stored row by row by some other tool. Must not silently pile up at 0,0.
    r = copy.deepcopy(base)
    for s in r["walls"] + r["doors"]:
        t = s["transform"]
        s["transform"] = [t[0], t[4], t[8], t[12], t[1], t[5], t[9], t[13],
                          t[2], t[6], t[10], t[14], t[3], t[7], t[11], t[15]]
    save("21_row_major_transform", r)

    # 22 A real 15 cm wall stub standing 8 cm off a wall. Must attach, not vanish or flip.
    r = copy.deepcopy(base)
    r["walls"].append(wall((2.8, 0.08), (2.8, 0.23)))
    save("22_short_stub_near_wall", r)

    # 23 A tiny scan where the door cut removes every wall. Must stop with a clear message.
    save("23_door_eats_everything", {"walls": [wall((0, 0), (0.3, 0))], "doors": [door((0, 0), (0.3, 0))]})

    # 24 Top-level object with the walls only inside "rooms".
    save("24_walls_inside_rooms_key", {"rooms": [base]})

    print("Wrote 24 edge cases into tests/edge_cases/")


if __name__ == "__main__":
    main()
