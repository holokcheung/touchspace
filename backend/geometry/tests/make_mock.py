"""Generate mock_room.json that imitates RoomPlan output (6 m x 4 m, two rooms)."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)                      # so "import config" finds the main code
SAMPLES = os.path.join(ROOT, "samples")

import json, math

def surface(category, width, height, depth, x, z, angle_deg):
    a = math.radians(angle_deg)          # rotation about world-up (y)
    c, s = math.cos(a), math.sin(a)
    # column-major 4x4: col0 = local x, col1 = up, col2 = local z, col3 = position
    t = [c, 0, -s, 0,   0, 1, 0, 0,   s, 0, c, 0,   x, height / 2, z, 1]
    return {"category": category, "dimensions": [width, height, depth], "transform": t}

W = lambda *a: surface({"wall": {}}, *a)
room = {
    "walls": [
        W(6.0, 2.5, 0, 3.0, 0.0, 0),    # bottom
        W(6.0, 2.5, 0, 3.0, 4.0, 0),    # top
        W(4.0, 2.5, 0, 0.0, 2.0, 90),   # left
        W(4.0, 2.5, 0, 6.0, 2.0, 90),   # right
        W(4.0, 2.5, 0, 3.5, 2.0, 90),   # interior partition
    ],
    "doors": [
        surface({"door": {"isOpen": False}}, 0.9, 2.0, 0, 1.5, 0.0, 0),   # entrance
        surface({"door": {"isOpen": True}}, 0.9, 2.0, 0, 3.5, 3.0, 90),  # between rooms
    ],
    "openings": [],
    "windows": [surface({"window": {}}, 1.2, 1.0, 0, 6.0, 2.0, 90)],
    "objects": [
        surface({"table": {}}, 1.6, 0.75, 0.8, 1.7, 2.2, 0),
        surface({"sofa": {}}, 2.0, 0.8, 0.9, 4.8, 3.3, 0),
    ],
}
json.dump(room, open(os.path.join(SAMPLES, "mock_room.json"), "w"), indent=2)
print("Wrote samples/mock_room.json")
