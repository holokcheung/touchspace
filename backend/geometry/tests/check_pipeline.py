"""Self-check for the geometry pipeline.  Run from the project folder:  python tests/check_pipeline.py

Each check builds something whose correct answer we know in advance,
runs the real pipeline on it, and compares. PASS means the code did what we expect.
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)                      # so "import config" finds the main code
SAMPLES = os.path.join(ROOT, "samples")

import json, math, os, tempfile
import numpy as np
import trimesh
from shapely.geometry import Point
import config
from parse import load_room
from plan import build_plan
from model import build_mesh
from clean import wall_segments

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


def surface(cat, w, h, d, x, z, angle_deg):
    a = math.radians(angle_deg)
    c, s = math.cos(a), math.sin(a)
    return {"category": cat, "dimensions": [w, h, d],
            "transform": [c, 0, -s, 0, 0, 1, 0, 0, s, 0, c, 0, x, h / 2, z, 1]}


def write_json(room):
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(room, f)
    f.close()
    return f.name


# ---------- 1. Size: a 6 m x 4 m room at 1:50 must come out at a predictable size ----------
config.SCALE = 50
room = load_room(os.path.join(SAMPLES, "mock_room.json"))
plan = build_plan(room)
mesh = build_mesh(plan)
expect_x = 6000 / 50 + config.WALL_THICKNESS_MM + 2 * config.MARGIN_MM   # 138.5
expect_y = 4000 / 50 + config.WALL_THICKNESS_MM + 2 * config.MARGIN_MM   # 98.5
expect_z = config.BASE_THICKNESS_MM + config.WALL_HEIGHT_MM              # 7.0
x, y, z = mesh.extents
check("Model size matches the room size and scale",
      abs(x - expect_x) < 0.1 and abs(y - expect_y) < 0.1 and abs(z - expect_z) < 0.1,
      f"got {x:.1f} x {y:.1f} x {z:.1f} mm, expected {expect_x} x {expect_y} x {expect_z}")

# ---------- 2. Door: the entrance gap must be open, the wall next to it must be solid ----------
# Entrance door centre is x = 1.5 m on the wall at z = 0. Map point = (1.5, 0) * 20 mm/m.
door_pt = Point(1.5 * 20, 0)
wall_pt = Point(4.5 * 20, 0)
check("Door gap is open", not plan.walls.contains(door_pt))
check("Wall beside the door is solid", plan.walls.contains(wall_pt))

# ---------- 3. Orientation: no mirror image ----------
# ARKit / RoomPlan: y is up, the scan starts looking toward -z, +x is to the right.
# So an object in FRONT and to the RIGHT of the start point must appear UP and RIGHT on the map.
test = {"walls": [surface({"wall": {}}, 10, 2.5, 0, 0, 0, 0)],
        "objects": [surface({"bed": {}}, 1, 0.5, 1, 2.0, -3.0, 0)]}
r = load_room(write_json(test))
c = r.objects[0].center
check("Front-right object appears up-right on the map (not mirrored)",
      c[0] > 0 and c[1] > 0, f"map position {c.round(2)}")

# ---------- 4. Cleanup on the real sample: walls straightened and corners closed ----------
# A wall end that stops short of another wall by less than SNAP_TOL_M is a scan error and
# must be closed. A wall end far from every wall is a real opening and must stay open.
def loose_ends(segs, tol=0.02):
    from shapely.geometry import LineString
    lines = [LineString(s) for s in segs]
    gaps = []
    for i, (p0, p1) in enumerate(segs):
        for p in (p0, p1):
            d = min(lines[j].distance(Point(p)) for j in range(len(segs)) if j != i)
            if d >= tol:
                gaps.append(d)
    return gaps

from clean import clean
clean_room = load_room(os.path.join(SAMPLES, "test-roomplan.json"))
after_segs = clean(clean_room)
gaps = loose_ends(after_segs)
small = [g for g in gaps if g < config.SNAP_TOL_M]
check("Cleanup closes every small corner gap", len(small) == 0,
      f"{len(small)} small gaps left, {len(gaps)} loose ends are real openings "
      f"({', '.join(f'{g:.2f} m' for g in gaps)})")

angles = [math.degrees(math.atan2(w.axis[1], w.axis[0])) % 90 for w in clean_room.walls]
square = sum(1 for a in angles if min(a, 90 - a) < 1e-6)
check("Cleanup squares the walls", square == len(angles), f"{square}/{len(angles)} walls exactly square")

# ---------- 4b. Messy scan (stress_room.json): rotated, crooked, gappy, split, with a 45-degree wall ----------
stress = load_room(os.path.join(SAMPLES, "stress_room.json"))
segs = clean(stress)
gaps = loose_ends(segs)
check("Messy scan: every small gap closed", all(g >= config.SNAP_TOL_M for g in gaps),
      f"{len(gaps)} loose ends left")
diag = [w for w in stress.walls
        if abs(abs(math.degrees(math.atan2(w.axis[1], w.axis[0]))) % 90 - 45) < 1.0]
check("Messy scan: the 45-degree wall stays at 45 degrees", len(diag) == 1)

# ---------- 5. STL file: can be written and read back ----------
out = os.path.join(tempfile.gettempdir(), "check.stl")
build_mesh(build_plan(load_room(os.path.join(SAMPLES, "test-roomplan.json")))).export(out)
back = trimesh.load(out)
check("STL file writes and reloads", len(back.faces) > 0, f"{len(back.faces)} triangles")

print(f"\n{sum(results)}/{len(results)} checks passed")
