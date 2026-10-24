"""Generate stress_room.json: a deliberately messy scan to test clean.py.

What makes it hard (each one is a real RoomPlan failure mode):
  1. The whole scan is rotated 17 degrees (phone was not aligned with the walls).
  2. Every wall is off square by up to 1.5 degrees.
  3. Wall ends stop 5-12 cm short of each other, so corners have gaps.
  4. The long bottom wall is split into two pieces 6 cm out of line.
  5. One corner is cut by a 45-degree wall, which must STAY at 45 degrees.
  6. L-shaped outline with an interior wall, three doors, mixed furniture.
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)                      # so "import config" finds the main code
SAMPLES = os.path.join(ROOT, "samples")

import json, math, random

random.seed(7)
ROT = math.radians(17)


def to_world(x, y):
    """Clean map frame -> rotated -> RoomPlan (X, Z), using map = (X, -Z)."""
    c, s = math.cos(ROT), math.sin(ROT)
    rx, ry = c * x - s * y, s * x + c * y
    return rx, -ry


def surface(cat, p0, p1, height=2.5, depth=0.0, noise_deg=0.0, shrink=0.0):
    (x0, y0), (x1, y1) = p0, p1
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    L = math.hypot(x1 - x0, y1 - y0) - shrink
    a = math.atan2(y1 - y0, x1 - x0) + ROT + math.radians(noise_deg)
    ux, uy = math.cos(a), math.sin(a)
    X, Z = to_world(cx, cy)
    t = [ux, 0, -uy, 0,   0, 1, 0, 0,   uy, 0, ux, 0,   X, height / 2, Z, 1]
    return {"category": cat, "dimensions": [L, height, depth], "transform": t}


def wall(p0, p1, offset=(0, 0)):
    p0 = (p0[0] + offset[0], p0[1] + offset[1])
    p1 = (p1[0] + offset[0], p1[1] + offset[1])
    return surface({"wall": {}}, p0, p1, noise_deg=random.uniform(-1.5, 1.5),
                   shrink=random.uniform(0.10, 0.24))


def door(c, along_x, width=0.9, is_open=False):
    h = width / 2
    p0, p1 = ((c[0] - h, c[1]), (c[0] + h, c[1])) if along_x else ((c[0], c[1] - h), (c[0], c[1] + h))
    return surface({"door": {"isOpen": is_open}}, p0, p1, height=2.0)


def obj(cat, c, w, d, angle_deg=0):
    a = math.radians(angle_deg)
    p0 = (c[0] - math.cos(a) * w / 2, c[1] - math.sin(a) * w / 2)
    p1 = (c[0] + math.cos(a) * w / 2, c[1] + math.sin(a) * w / 2)
    return surface({cat: {}}, p0, p1, height=0.8, depth=d)


def section(label, c):
    X, Z = to_world(*c)
    return {"label": label, "center": [X, -0.25, Z], "story": 0}


room = {
    "walls": [
        wall((0, 0), (4.9, 0)),                 # bottom, piece 1
        wall((5.0, 0), (8, 0), offset=(0, 0.06)),  # bottom, piece 2, 6 cm out of line
        wall((8, 0), (8, 3)),                   # right
        wall((8, 3), (7, 4)),                   # 45-degree corner cut
        wall((7, 4), (4, 4)),                   # top of the wide part
        wall((4, 4), (4, 7)),                   # step of the L
        wall((4, 7), (0, 7)),                   # top
        wall((0, 7), (0, 0)),                   # left
        wall((0, 3), (4, 3)),                   # interior wall
    ],
    "doors": [
        door((2.0, 0), along_x=True),            # entrance
        door((1.5, 3), along_x=True, is_open=True),  # living room -> bedroom
        door((4, 5.5), along_x=False),           # bedroom -> outside of the L
    ],
    "openings": [], "windows": [],
    "objects": [
        obj("bed", (2.0, 5.3), 2.0, 1.6),
        obj("sofa", (6.0, 0.8), 2.2, 0.9),
        obj("table", (6.2, 2.4), 1.2, 0.8, angle_deg=30),
        obj("toilet", (0.5, 1.0), 0.4, 0.7),
        obj("chair", (5.2, 2.4), 0.5, 0.5),
    ],
    "sections": [section("livingRoom", (5.5, 1.8)), section("bedroom", (2.0, 5.0))],
}
json.dump(room, open(os.path.join(SAMPLES, "stress_room.json"), "w"), indent=2)
print("Wrote samples/stress_room.json")
