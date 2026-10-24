"""Run every file in edge_cases/ through the pipeline and check the expected result.

Run from the project folder:  python tests/test_edge_cases.py
Previews are written to edge_cases/out/ so each case can also be checked by eye.
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)                      # so "import config" finds the main code
SAMPLES = os.path.join(ROOT, "samples")

import io, math, os, contextlib, tempfile, traceback
from shapely.geometry import Point, LineString
import config
from parse import load_room
from plan import build_plan
from model import build_mesh, export_stl
from main import preview_png

DIR = os.path.join(ROOT, "tests", "edge_cases")
T = config.WALL_THICKNESS_MM
MM = 1000.0 / config.SCALE          # mm per metre on the map


def mm(x, y):
    return Point(x * MM, y * MM)


def parts(geom):
    return [g for g in getattr(geom, "geoms", [geom]) if not g.is_empty]


def wall_angles(room):
    return [math.degrees(math.atan2(w.axis[1], w.axis[0])) % 90 for w in room.walls]


def all_square(room):
    return all(min(a, 90 - a) < 1e-6 for a in wall_angles(room))


# name -> (what must be true, test function(room, plan, log) -> (ok, detail))
EXPECT = {
    "01_only_walls": ("Runs with no doors, objects or labels",
        lambda r, p, log: (len(parts(p.walls)) == 1 and p.objects is None, f"{len(parts(p.walls))} wall pieces")),
    "02_no_walls": ("Stops with a clear 'no walls' message", None),   # handled specially below
    "03_other_encodings": ("String category and nested transform still work, door is cut",
        lambda r, p, log: (not p.walls.contains(mm(1.95, 0)), "door point open")),
    "04_tiny_fragments": ("Tiny and zero-length walls ignored, no stray blobs",
        lambda r, p, log: (len(parts(p.walls)) == 1, f"{len(parts(p.walls))} wall pieces")),
    "05_nan_values": ("Broken wall skipped with a warning, rest of the map fine",
        lambda r, p, log: (len(parts(p.walls)) == 1 and "skipped" in log.lower()
                           and all(math.isfinite(v) for v in p.walls.bounds), log.strip()[:80])),
    "06_two_floors": ("Only one floor drawn (no overlapping floor plans)",
        lambda r, p, log: (abs((p.walls.bounds[2] - p.walls.bounds[0]) - (4 * MM + T)) < 1.0,
                           f"width {p.walls.bounds[2] - p.walls.bounds[0]:.1f} mm")),
    "07_curved_wall": ("Curved wall drawn straight, with a warning",
        lambda r, p, log: ("curve" in log.lower(), log.strip()[:80])),
    "08_overshoot_corners": ("Overshooting wall ends trimmed, no spikes at corners",
        lambda r, p, log: ((p.walls.bounds[2] - p.walls.bounds[0]) <= 4 * MM + T + 0.1,
                           f"width {p.walls.bounds[2] - p.walls.bounds[0]:.1f} mm, expect {4 * MM + T}")),
    "09_door_off_wall": ("Door 12 cm off the wall still cuts the wall",
        lambda r, p, log: (not p.walls.contains(mm(1.95, 0)) and not p.walls.contains(mm(1.95, 0.12)),
                           "door point open")),
    "10_duplicate_wall": ("Duplicate wall does not make a double-thick wall",
        lambda r, p, log: (p.walls.intersection(LineString([(2 * MM, -10), (2 * MM, 10)])).length <= T + 0.3,
                           f"thickness {p.walls.intersection(LineString([(2 * MM, -10), (2 * MM, 10)])).length:.2f} mm")),
    "11_rotated_44": ("44-degree rotation straightened, walls closed",
        lambda r, p, log: (all_square(r) and len(parts(p.walls)) == 1, f"{len(parts(p.walls))} wall pieces")),
    "12_too_big": ("Warns that the map is too big and suggests a scale", None),   # handled specially
    "13_tiny_room": ("Tiny room and narrow door still produce an open door",
        lambda r, p, log: (not p.walls.contains(mm(0.6, 0)), "door point open")),
    "14_objects_outside": ("Furniture trimmed off walls, outside furniture dropped",
        lambda r, p, log: (p.objects is not None and len(parts(p.objects)) == 1
                           and not p.objects.intersects(p.walls)
                           and p.objects.bounds[2] < 4 * MM, f"{len(parts(p.objects)) if p.objects else 0} objects")),
    "15_real_82_degree_corner": ("A real 82-degree corner is kept, not forced to 90",
        lambda r, p, log: (any(abs(a - 82) < 0.5 or abs(a - 8) < 0.5 for a in wall_angles(r)),
                           f"angles mod 90: {[round(a, 1) for a in wall_angles(r)]}")),
    "16_opening_only": ("Openings without doors are cut like doors",
        lambda r, p, log: (not p.walls.contains(mm(4, 1.5)), "opening point open")),
    "17_bom_and_korean_text": ("BOM and Korean text are read; label kept",
        lambda r, p, log: (p.labels and "침실" in p.labels[0]["label"], str(p.labels[:1]))),
    "18_empty_category": ("Empty category becomes 'unknown', no crash",
        lambda r, p, log: (r.objects and r.objects[0].kind == "unknown", r.objects[0].kind if r.objects else "none")),
    "19_story_as_text": ("Text story counts as floor 0, all 4 walls kept",
        lambda r, p, log: (len(r.walls) == 4, f"{len(r.walls)} walls")),
    "20_list_of_rooms": ("List of rooms merged into one map",
        lambda r, p, log: (abs((p.walls.bounds[2] - p.walls.bounds[0]) - (7 * MM + T)) < 1.0,
                           f"width {p.walls.bounds[2] - p.walls.bounds[0]:.1f} mm")),
    "21_row_major_transform": ("Row-major transforms detected; walls in the right places",
        lambda r, p, log: ("row by row" in log and not p.walls.contains(mm(2, 1.5))
                           and p.walls.contains(mm(4, 1.5)), "walls placed correctly")),
    "22_short_stub_near_wall": ("Short real stub attaches to the wall, does not collapse",
        lambda r, p, log: (p.walls.contains(mm(2.8, 0.15)), "stub present")),
    "23_door_eats_everything": ("Stops with a clear message when nothing is left", None),
    "24_walls_inside_rooms_key": ("Walls inside a 'rooms' key are found",
        lambda r, p, log: (len(r.walls) == 4 and not p.walls.contains(mm(1.95, 0)), f"{len(r.walls)} walls")),
}


def run_case(name):
    path = os.path.join(DIR, name + ".json")
    log = io.StringIO()
    with contextlib.redirect_stdout(log):
        try:
            room = load_room(path)
            plan = build_plan(room)
            mesh = build_mesh(plan)
            export_stl(mesh, os.path.join(tempfile.gettempdir(), name + ".stl"))
            preview_png(plan, os.path.join(DIR, "out", name + ".png"))
            error = None
        except Exception as e:  # noqa: BLE001
            room = plan = None
            error = e
    text = log.getvalue()

    if name == "02_no_walls":
        ok = error is not None and "no walls" in str(error).lower()
        return ok, f"error: {error}" if error else "no error raised"
    if name == "23_door_eats_everything":
        ok = isinstance(error, ValueError) and "nothing is left" in str(error).lower()
        return ok, f"error: {error}" if error else "no error raised"
    if error is not None:
        return False, f"CRASH {type(error).__name__}: {error}"
    if name == "12_too_big":
        return ("--scale" in text, text.strip().splitlines()[-1][:90])
    # Every closed room must stay hollow: a point in the middle of the room is not wall.
    inside = {"13_tiny_room": mm(0.6, 0.5), "11_rotated_44": None}.get(name, mm(2, 1.5))
    if inside is not None and plan.walls.contains(inside):
        return False, "room interior is filled solid with wall"
    return EXPECT[name][1](room, plan, text)


def main():
    if not os.path.isdir(DIR):                # first run: create the cases automatically
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import make_edge_cases
        make_edge_cases.main()
    os.makedirs(os.path.join(DIR, "out"), exist_ok=True)
    names = sorted(f[:-5] for f in os.listdir(DIR) if f.endswith(".json"))
    passed = 0
    for n in names:
        desc = EXPECT.get(n, ("(no expectation written)", None))[0]
        try:
            ok, detail = run_case(n)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"CHECK CRASH {e}"
        passed += ok
        print(f"[{'PASS' if ok else 'FAIL'}] {n:<26} {desc}\n         -> {detail}")
    print(f"\n{passed}/{len(names)} edge cases passed. Previews in tests/edge_cases/out/")


if __name__ == "__main__":
    main()
