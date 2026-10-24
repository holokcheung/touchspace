"""Generate a random, realistically messy RoomPlan-style scan.

Run from the project folder:
       python tests/make_random_room.py            (random layout every time)
       python tests/make_random_room.py --seed 7   (the same layout every time for seed 7)
Writes tests/random_rooms/random_room_<seed>.json and prints the command to turn it into a map.

How a layout is made: a rectangular flat is split again and again into smaller rooms
(like cutting paper). Every cut becomes an interior wall with a door in it.
Then scan noise is added: whole-scan rotation, crooked walls, short wall ends.
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)                      # so "import config" finds the main code
SAMPLES = os.path.join(ROOT, "samples")

import argparse, json, math, random

LABELS = ["bedroom", "bathroom", "kitchen", "livingRoom", "diningRoom", "unidentified"]
FURNITURE = {"bed": (2.0, 1.6), "sofa": (2.0, 0.9), "table": (1.2, 0.8), "storage": (1.0, 0.5),
             "toilet": (0.4, 0.7), "sink": (0.6, 0.5), "chair": (0.5, 0.5), "refrigerator": (0.7, 0.7)}


def split(rect, depth, rng, out_rooms, out_cuts):
    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    can_v, can_h = w >= 5.0, h >= 5.0          # each side must stay at least 2.5 m
    if depth == 0 or not (can_v or can_h) or (depth < 3 and rng.random() < 0.25):
        out_rooms.append(rect)
        return
    vertical = can_v and (not can_h or w >= h)
    if vertical:
        x = rng.uniform(x0 + 2.5, x1 - 2.5)
        out_cuts.append(((x, y0), (x, y1)))
        split((x0, y0, x, y1), depth - 1, rng, out_rooms, out_cuts)
        split((x, y0, x1, y1), depth - 1, rng, out_rooms, out_cuts)
    else:
        y = rng.uniform(y0 + 2.5, y1 - 2.5)
        out_cuts.append(((x0, y), (x1, y)))
        split((x0, y0, x1, y), depth - 1, rng, out_rooms, out_cuts)
        split((x0, y, x1, y1), depth - 1, rng, out_rooms, out_cuts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()
    seed = args.seed if args.seed is not None else random.randint(0, 9999)
    rng = random.Random(seed)

    W, H = rng.uniform(6, 11), rng.uniform(5, 9)
    rot = math.radians(rng.uniform(0, 90))

    def surface(cat, p0, p1, height=2.5, depth=0.0, noise=0.0, shrink=0.0):
        c, s = math.cos(rot), math.sin(rot)
        def R(x, y):
            return c * x - s * y, s * x + c * y
        (x0, y0), (x1, y1) = R(*p0), R(*p1)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        L = max(math.hypot(x1 - x0, y1 - y0) - shrink, 0.01)
        a = math.atan2(y1 - y0, x1 - x0) + math.radians(noise)
        ux, uy = math.cos(a), math.sin(a)
        t = [ux, 0, -uy, 0, 0, 1, 0, 0, uy, 0, ux, 0, cx, height / 2, -cy, 1]
        return {"category": cat, "dimensions": [L, height, depth], "transform": t, "story": 0}

    def noisy_wall(p0, p1):
        return surface({"wall": {}}, p0, p1, noise=rng.uniform(-1.5, 1.5), shrink=rng.uniform(0, 0.2))

    rooms, cuts = [], []
    split((0, 0, W, H), 3, rng, rooms, cuts)

    walls = [noisy_wall((0, 0), (W, 0)), noisy_wall((W, 0), (W, H)),
             noisy_wall((W, H), (0, H)), noisy_wall((0, H), (0, 0))]
    walls += [noisy_wall(a, b) for a, b in cuts]

    doors = []
    def add_door(a, b):
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        t = rng.uniform(0.3, 0.7)
        cx, cy = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
        dx, dy = (b[0] - a[0]) / L * 0.45, (b[1] - a[1]) / L * 0.45
        doors.append(surface({"door": {"isOpen": rng.random() < 0.5}},
                             (cx - dx, cy - dy), (cx + dx, cy + dy), height=2.0))
    add_door((0, 0), (W, 0))                                 # entrance
    for a, b in cuts:
        add_door(a, b)

    objects, sections = [], []
    for (x0, y0, x1, y1) in rooms:
        for _ in range(rng.randint(1, 3)):
            kind = rng.choice(list(FURNITURE))
            w, d = FURNITURE[kind]
            if x1 - x0 < w + 0.6 or y1 - y0 < d + 0.6:
                continue
            cx, cy = rng.uniform(x0 + w / 2 + 0.3, x1 - w / 2 - 0.3), rng.uniform(y0 + d / 2 + 0.3, y1 - d / 2 - 0.3)
            objects.append(surface({kind: {}}, (cx - w / 2, cy), (cx + w / 2, cy), height=0.8, depth=d))
        c, s = math.cos(rot), math.sin(rot)
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        sections.append({"label": rng.choice(LABELS), "center": [c * mx - s * my, -0.25, -(s * mx + c * my)], "story": 0})

    room = {"walls": walls, "doors": doors, "openings": [], "windows": [], "objects": objects,
            "sections": sections}
    folder = os.path.join(ROOT, "tests", "random_rooms")
    os.makedirs(folder, exist_ok=True)
    name = f"random_room_{seed}.json"
    with open(os.path.join(folder, name), "w") as f:
        json.dump(room, f, indent=1)
    print(f"Wrote tests/random_rooms/{name}: {W:.1f} m x {H:.1f} m, {len(rooms)} rooms, "
          f"{len(walls)} walls, {len(doors)} doors, {len(objects)} objects, "
          f"rotated {math.degrees(rot):.0f} deg")
    print(f"Make the map:  python main.py tests/random_rooms/{name} -o random_{seed}.stl")


if __name__ == "__main__":
    main()
