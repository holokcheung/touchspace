"""Step 2: cleaned scan -> 2D tactile floor plan (shapely polygons, millimetres).

Everything is solved in 2D. 3D only happens once, at the end, in model.py.
"""
import math
from dataclasses import dataclass, field
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union
from shapely import affinity
import config
from clean import clean


@dataclass
class FloorPlan:
    walls: object           # (Multi)Polygon of raised walls, door gaps already cut
    objects: object         # (Multi)Polygon of low furniture bumps, or None
    base: Polygon           # rectangle for the base plate
    labels: list = field(default_factory=list)  # [{"label", "x_mm", "y_mm"}] for UI / voice / braille


def _mm(v):
    return v * 1000.0 / config.SCALE


def _door_cutter(d, t):
    half = max(_mm(d.width), config.MIN_DOOR_GAP_MM) / 2.0
    c = _mm(d.center)
    seg = LineString([c - d.axis * half, c + d.axis * half])
    return seg.buffer(t * 2, cap_style="flat")


def build_plan(room):
    segs_m = clean(room)
    t = config.WALL_THICKNESS_MM

    # Walls: fixed tactile thickness. Square caps close any tiny gap left at corners.
    walls = unary_union([LineString([_mm(p0), _mm(p1)]).buffer(t / 2, cap_style="square")
                         for p0, p1 in segs_m])

    # Doors and openings: cut through the wall, never narrower than a finger.
    if room.doors:
        walls = walls.difference(unary_union([_door_cutter(d, t) for d in room.doors]))

    # Drop tiny wall stubs left beside door cuts. They feel like random bumps, not walls.
    # Only pieces shorter than about SNAP_TOL_M in real life go. A 50 cm wall between a door
    # and a corner is real and must stay (an earlier, larger limit deleted those by mistake).
    min_area = t * max(_mm(config.SNAP_TOL_M), 2 * t)
    walls = unary_union([p for p in getattr(walls, "geoms", [walls]) if p.area >= min_area])
    if walls.is_empty:
        raise ValueError("Nothing is left after cutting the doors. The scan is too small or broken.")

    # Landmark objects: low bumps that never touch a wall.
    objects = None
    keep = [o for o in room.objects if o.kind not in config.EXCLUDED_OBJECTS]
    if config.INCLUDE_OBJECTS and keep:
        rects = []
        for o in keep:
            w, d = _mm(o.width), _mm(o.depth)
            r = box(-w / 2, -d / 2, w / 2, d / 2)
            r = affinity.rotate(r, math.degrees(math.atan2(o.axis[1], o.axis[0])), origin=(0, 0))
            c = _mm(o.center)
            rects.append(affinity.translate(r, c[0], c[1]).buffer(-0.5))
        # Keep only the part inside the building, away from the walls, and drop crumbs.
        inside = walls.convex_hull
        objects = unary_union(rects).intersection(inside).difference(walls.buffer(1.5))
        min_area = (2 * t) ** 2
        objects = unary_union([g for g in getattr(objects, "geoms", [objects])
                               if g.geom_type == "Polygon" and g.area >= min_area]) or None
        if objects is not None and objects.is_empty:
            objects = None

    labels = [{"label": s.label, "x_mm": round(float(_mm(s.center[0])), 1),
               "y_mm": round(float(_mm(s.center[1])), 1)} for s in room.sections]

    minx, miny, maxx, maxy = walls.bounds
    m = config.MARGIN_MM
    base = box(minx - m, miny - m, maxx + m, maxy + m)
    return FloorPlan(walls=walls, objects=objects, base=base, labels=labels)
