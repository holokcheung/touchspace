"""What the phone has told us, reduced to what a 60 × 40 pin display can show.

Everything here is in plan meters, the same frame as FloorMap: x right, y up, seen from
above. ARKit world points and James's iOS MapPoint (x, z) both become (x, -z), which is the
RoomPlan importer's projection, so a live scan and its camera pose line up.

Heading is a compass angle in radians: 0 faces plan up (ARKit -Z), pi/2 faces plan right.
That is the iOS app's convention ("clockwise from -Z").
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from app.models.map import FloorMap
from app.services.roomplan import _collect, decode_matrix, import_roomplan

Pt = tuple[float, float]
Seg = tuple[Pt, Pt]

# A doorway counts as part of a wall when both of its ends are this close to the wall line.
GAP_SNAP_M = 0.3


@dataclass(frozen=True)
class Pose:
    x: float
    y: float
    heading: float  # radians, compass style


@dataclass
class Plan:
    name: str
    walls: list[Seg] = field(default_factory=list)
    gaps: list[Seg] = field(default_factory=list)  # doors and openings, as segments on walls
    rooms: list[tuple[str, list[Pt]]] = field(default_factory=list)
    symbols: list[tuple[str, Pt]] = field(default_factory=list)  # (landmark type, position)
    obstacles: list[list[Pt]] = field(default_factory=list)  # outlines of furniture marked for tactile

    def bounds(self) -> tuple[float, float, float, float] | None:
        pts = [p for w in self.walls for p in w] + [p for _, poly in self.rooms for p in poly]
        if not pts:
            return None
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)

    def room_at(self, p: Pt) -> str | None:
        for name, poly in self.rooms:
            if point_in(p, poly):
                return name
        return None


def point_in(p: Pt, poly: list[Pt]) -> bool:
    inside = False
    for a, b in zip(poly, poly[1:] + poly[:1]):
        if (a[1] > p[1]) != (b[1] > p[1]) and p[0] < a[0] + (p[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1]):
            inside = not inside
    return inside


def _num(v: Any, name: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValueError(f"{name} must be a finite number")
    return float(v)


def _map_point(p: Any, name: str) -> Pt:
    """iOS MapPoint {"x", "z"} -> plan (x, -z)."""
    if not isinstance(p, dict):
        raise ValueError(f"{name} must be an object with x and z")
    return _num(p.get("x"), f"{name}.x"), -_num(p.get("z"), f"{name}.z")


def _plan_point(p: Any, name: str) -> Pt:
    """FloorMap Point2D {"x", "y"} or [x, y], already in plan meters."""
    if isinstance(p, dict):
        return _num(p.get("x"), f"{name}.x"), _num(p.get("y"), f"{name}.y")
    if isinstance(p, (list, tuple)) and len(p) == 2:
        return _num(p[0], f"{name}[0]"), _num(p[1], f"{name}[1]")
    raise ValueError(f"{name} must be a point")


# --------------------------------------------------------------------------- maps


def plan_from_floormap(fmap: FloorMap) -> Plan:
    walls = {w.id: w for w in fmap.walls}
    gaps: list[Seg] = []
    for g in [*fmap.doors, *fmap.openings]:
        wall = walls.get(g.wall_id) if g.wall_id else None
        if wall is None:
            wall = min(fmap.walls, key=lambda w: _dist_to_seg(g.position.as_tuple(), (w.start.as_tuple(), w.end.as_tuple())), default=None)
        if wall is None or wall.length == 0:
            continue
        ux, uy = (wall.end.x - wall.start.x) / wall.length, (wall.end.y - wall.start.y) / wall.length
        h = g.width / 2
        gaps.append(((g.position.x - ux * h, g.position.y - uy * h), (g.position.x + ux * h, g.position.y + uy * h)))
    return Plan(
        name=fmap.name,
        walls=[(w.start.as_tuple(), w.end.as_tuple()) for w in fmap.walls],
        gaps=gaps,
        rooms=[(r.name, [p.as_tuple() for p in r.polygon]) for r in fmap.rooms],
        symbols=[(lm.type.value, lm.position.as_tuple()) for lm in fmap.landmarks if lm.show_on_tactile is not False],
        obstacles=[_footprint(o) for o in fmap.objects if o.include_in_tactile and not o.hidden],
    )


def _footprint(o) -> list[Pt]:
    """Rotated rectangle of a MapObject (rotation: radians CCW from +x)."""
    c, s = math.cos(o.rotation), math.sin(o.rotation)
    hw, hd = o.width / 2, o.depth / 2
    return [(o.position.x + dx * c - dy * s, o.position.y + dx * s + dy * c)
            for dx, dy in ((-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd))]


def plan_from_roomplan(data: dict, name: str = "Live scan") -> Plan:
    """A RoomPlan CapturedRoom as `JSONEncoder().encode(room)` writes it on the phone, or
    {"rooms": [room, ...]} for several rooms scanned in one AR session."""
    if not _collect(data)["walls"]:
        return Plan(name=name)  # the first updates of a scan have no walls yet
    fmap, _warnings = import_roomplan(data, name=name)
    return plan_from_floormap(fmap)


def plan_from_ios_geometry(geometry: dict, doors: list | None = None, name: str = "Saved map") -> Plan:
    """James's iOS MapGeometry (+ optional MapNavigation.doors), coordinates as MapPoint (x, z)."""
    if not isinstance(geometry, dict):
        raise ValueError("geometry must be an object")
    walls = [(_map_point(w.get("start"), f"walls[{i}].start"), _map_point(w.get("end"), f"walls[{i}].end"))
             for i, w in enumerate(geometry.get("walls") or [])]
    rooms = [(str(r.get("name") or f"Room {i + 1}"), [_map_point(p, f"rooms[{i}]") for p in r.get("polygon") or []])
             for i, r in enumerate(geometry.get("rooms") or [])]
    gaps = [(_map_point(d.get("start"), f"doors[{i}].start"), _map_point(d.get("end"), f"doors[{i}].end"))
            for i, d in enumerate(doors or [])]
    return Plan(name=name, walls=walls, gaps=gaps, rooms=[r for r in rooms if len(r[1]) >= 3])


def plan_from_message(msg: dict) -> Plan:
    """Whichever map format a phone message carries."""
    name = str(msg.get("name") or "")[:60]
    if isinstance(msg.get("room"), dict):
        return plan_from_roomplan(msg["room"], name or "Live scan")
    if isinstance(msg.get("geometry"), dict):
        return plan_from_ios_geometry(msg["geometry"], msg.get("doors"), name or "Saved map")
    if isinstance(msg.get("floormap"), dict):
        fmap = FloorMap.model_validate(msg["floormap"])
        return plan_from_floormap(fmap)
    raise ValueError('a map message needs "room" (RoomPlan), "geometry" (iOS map) or "floormap"')


# --------------------------------------------------------------------------- poses


def pose_from_world_transform(values: Any) -> Pose:
    """ARKit camera.transform (16 floats, column-major) -> plan pose.

    The camera looks down its own -Z, so the iOS heading is atan2(-c2.x, c2.z).
    """
    m = decode_matrix(values)
    heading = math.atan2(-m[0, 2], m[2, 2])
    return Pose(x=float(m[0, 3]), y=float(-m[2, 3]), heading=heading)


def pose_from_message(msg: dict) -> Pose | None:
    frame = msg.get("frame")
    if frame == "world":
        return pose_from_world_transform(msg.get("transform"))
    if frame == "map":
        return Pose(x=_num(msg.get("x"), "x"), y=-_num(msg.get("z"), "z"), heading=_num(msg.get("heading"), "heading"))
    if frame == "plan":
        return Pose(x=_num(msg.get("x"), "x"), y=_num(msg.get("y"), "y"), heading=_num(msg.get("heading"), "heading"))
    if frame == "none":
        return None
    raise ValueError('pose "frame" must be "world", "map", "plan" or "none"')


# --------------------------------------------------------------------------- walls minus doorways


def _dist_to_seg(p: Pt, s: Seg) -> float:
    (ax, ay), (bx, by) = s
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    return math.hypot(p[0] - ax - t * dx, p[1] - ay - t * dy)


def wall_pieces(wall: Seg, gaps: list[Seg]) -> list[Seg]:
    """The parts of a wall that are not doorways."""
    (ax, ay), (bx, by) = wall
    L = math.hypot(bx - ax, by - ay)
    if L == 0:
        return []
    ux, uy = (bx - ax) / L, (by - ay) / L
    cuts: list[tuple[float, float]] = []
    for g in gaps:
        if all(_line_dist(p, wall) <= GAP_SNAP_M for p in g):
            t0, t1 = sorted(((p[0] - ax) * ux + (p[1] - ay) * uy) for p in g)
            if t1 > 0 and t0 < L:
                cuts.append((max(t0, 0.0), min(t1, L)))
    pieces, t = [], 0.0
    for c0, c1 in sorted(cuts):
        if c0 > t:
            pieces.append((t, c0))
        t = max(t, c1)
    if t < L:
        pieces.append((t, L))
    return [((ax + ux * s, ay + uy * s), (ax + ux * e, ay + uy * e)) for s, e in pieces if e - s > 1e-6]


def _line_dist(p: Pt, s: Seg) -> float:
    """Distance from p to the wall's segment, allowing a little overhang past its ends."""
    (ax, ay), (bx, by) = s
    L = math.hypot(bx - ax, by - ay)
    ux, uy = (bx - ax) / L, (by - ay) / L
    t = (p[0] - ax) * ux + (p[1] - ay) * uy
    if t < -GAP_SNAP_M or t > L + GAP_SNAP_M:
        return math.inf
    return abs((p[0] - ax) * uy - (p[1] - ay) * ux)
