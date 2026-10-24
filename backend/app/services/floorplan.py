"""Floor-plan processing: clean up a normalized map so it can become a tactile model.

The pipeline is deliberately conservative. It tidies geometry (snaps wall
corners, drops slivers, squares the plan to the page, attaches doors to their
walls) but never invents rooms, doors, landmarks or routes.
"""

from __future__ import annotations

import math
from collections import Counter

import numpy as np
from pydantic import BaseModel

from app.models.map import Bounds, FloorMap, Point2D, ValidationIssue, Wall


class ProcessingOptions(BaseModel):
    snap_tolerance_m: float = 0.12
    min_wall_length_m: float = 0.2
    align_to_axes: bool = True
    translate_to_origin: bool = True
    gap_attach_tolerance_m: float = 0.35


class ProcessingResult(BaseModel):
    map: FloorMap
    issues: list[ValidationIssue]
    steps: list[str]


class FloorPlanError(ValueError):
    """Raised when a map cannot be processed at all (for example, it has no walls)."""


# --------------------------------------------------------------------------- geometry helpers


def _project_onto_segment(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, float, float]:
    """Return (closest point, distance, parameter t in [0,1]) of p onto segment ab."""
    ab = b - a
    denom = float(ab @ ab)
    t = 0.0 if denom == 0 else float(np.clip((p - a) @ ab / denom, 0.0, 1.0))
    q = a + t * ab
    return q, float(np.linalg.norm(p - q)), t


def _arr(p: Point2D) -> np.ndarray:
    return np.array([p.x, p.y], dtype=float)


def _pt(a: np.ndarray) -> Point2D:
    return Point2D(x=float(a[0]), y=float(a[1]))


def compute_bounds(fmap: FloorMap) -> Bounds:
    """Bounds of the structural plan: wall centerlines plus room outlines."""
    xs: list[float] = []
    ys: list[float] = []
    for w in fmap.walls:
        xs += [w.start.x, w.end.x]
        ys += [w.start.y, w.end.y]
    for room in fmap.rooms:
        xs += [p.x for p in room.polygon]
        ys += [p.y for p in room.polygon]
    if not xs:
        raise FloorPlanError("Map has no walls or rooms, so it has no extent.")
    return Bounds(min_x=min(xs), min_y=min(ys), max_x=max(xs), max_y=max(ys))


def dominant_angle(walls: list[Wall]) -> float:
    """Length-weighted dominant wall direction, folded into [-45°, 45°).

    Uses the circular mean of 4θ so walls at 0°, 90°, 180° and 270° all vote
    for the same orientation. RoomPlan's world yaw depends on how the phone
    was held when scanning started, so imports are usually rotated.
    """
    if not walls:
        return 0.0
    angles = np.array([w.angle for w in walls])
    weights = np.array([w.length for w in walls])
    s = float(np.sum(weights * np.sin(4 * angles)))
    c = float(np.sum(weights * np.cos(4 * angles)))
    if math.hypot(s, c) < 1e-9:
        return 0.0
    mean = math.atan2(s, c) / 4
    # Refine with a length-weighted median around that mean. Real scans have a few walls a
    # couple of degrees off; the median follows the majority of the wall length instead of
    # being pulled toward the outliers.
    offsets = (angles - mean + math.pi / 4) % (math.pi / 2) - math.pi / 4
    order = np.argsort(offsets)
    cumulative = np.cumsum(weights[order])
    median = float(offsets[order][np.searchsorted(cumulative, cumulative[-1] / 2)])
    return (mean + median + math.pi / 4) % (math.pi / 2) - math.pi / 4


def transform_map(fmap: FloorMap, rotation: float, translation: tuple[float, float] = (0.0, 0.0)) -> FloorMap:
    """Rotate every plan element about the origin by `rotation` radians, then translate."""
    cos_r, sin_r = math.cos(rotation), math.sin(rotation)
    tx, ty = translation

    def tp(p: Point2D) -> Point2D:
        return Point2D(x=cos_r * p.x - sin_r * p.y + tx, y=sin_r * p.x + cos_r * p.y + ty)

    out = fmap.model_copy(deep=True)
    for w in out.walls:
        w.start, w.end = tp(w.start), tp(w.end)
    for gap in [*out.doors, *out.openings, *out.windows]:
        gap.position = tp(gap.position)
    for obj in out.objects:
        obj.position = tp(obj.position)
        obj.rotation = obj.rotation + rotation
    for room in out.rooms:
        room.polygon = [tp(p) for p in room.polygon]
    for lm in out.landmarks:
        lm.position = tp(lm.position)
    for node in out.navigation.nodes:
        node.position = tp(node.position)
    out.bounds = None
    return out


# --------------------------------------------------------------------------- processing steps


def remove_short_walls(fmap: FloorMap, min_length: float) -> list[str]:
    removed = [w.id for w in fmap.walls if w.length < min_length]
    fmap.walls = [w for w in fmap.walls if w.length >= min_length]
    return removed


def snap_wall_endpoints(fmap: FloorMap, tolerance: float) -> int:
    """Close small gaps where walls should meet.

    1. Endpoints within `tolerance` of each other are merged to their mean
       (closes L-corners that the scanner left slightly open).
    2. A remaining free endpoint within `tolerance` of another wall's
       interior is moved onto that wall (closes T-junctions).

    Returns the number of endpoints moved.
    """
    ends: list[tuple[int, str]] = [(i, side) for i in range(len(fmap.walls)) for side in ("start", "end")]
    coords = np.array([_arr(getattr(fmap.walls[i], side)) for i, side in ends])
    if len(coords) == 0:
        return 0

    # Union-find clustering of nearby endpoints.
    parent = list(range(len(ends)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(ends)):
        for j in range(i + 1, len(ends)):
            if ends[i][0] != ends[j][0] and np.linalg.norm(coords[i] - coords[j]) <= tolerance:
                parent[find(i)] = find(j)

    clusters: dict[int, list[int]] = {}
    for i in range(len(ends)):
        clusters.setdefault(find(i), []).append(i)

    moved = 0
    new_coords = coords.copy()
    for members in clusters.values():
        if len(members) > 1:
            mean = coords[members].mean(axis=0)
            for m in members:
                if np.linalg.norm(coords[m] - mean) > 1e-9:
                    moved += 1
                new_coords[m] = mean

    # T-junctions: free endpoints that sit just short of (or past) another wall.
    free = {members[0] for members in clusters.values() if len(members) == 1}
    for k in free:
        wall_idx = ends[k][0]
        p = new_coords[k]
        best: tuple[float, np.ndarray] | None = None
        for j, other in enumerate(fmap.walls):
            if j == wall_idx:
                continue
            a_idx, b_idx = ends.index((j, "start")), ends.index((j, "end"))
            q, dist, t = _project_onto_segment(p, new_coords[a_idx], new_coords[b_idx])
            if 0.0 < t < 1.0 and dist <= tolerance and (best is None or dist < best[0]):
                best = (dist, q)
        if best is not None and best[0] > 1e-9:
            new_coords[k] = best[1]
            moved += 1

    for k, (i, side) in enumerate(ends):
        setattr(fmap.walls[i], side, _pt(new_coords[k]))
    return moved


def attach_gaps_to_walls(fmap: FloorMap, tolerance: float) -> list[ValidationIssue]:
    """Make sure every door/opening/window sits on a wall centerline.

    Gaps that already name a wall are projected onto it. Gaps without a wall
    (or naming a missing one) are attached to the nearest wall within
    `tolerance`; otherwise they are left unattached and reported.
    """
    issues: list[ValidationIssue] = []
    walls = {w.id: w for w in fmap.walls}
    for gap in [*fmap.doors, *fmap.openings, *fmap.windows]:
        p = _arr(gap.position)
        candidates = [walls[gap.wall_id]] if gap.wall_id in walls else list(walls.values())
        best: tuple[float, Wall, np.ndarray] | None = None
        for w in candidates:
            q, dist, _ = _project_onto_segment(p, _arr(w.start), _arr(w.end))
            if best is None or dist < best[0]:
                best = (dist, w, q)
        limit = max(tolerance, best[1].thickness) if best else tolerance
        if best is None or best[0] > limit:
            issues.append(ValidationIssue(
                severity="warning", code="gap_not_on_wall", element_id=gap.id,
                message=f"{gap.kind.capitalize()} '{gap.id}' is not close to any wall, so it will not cut an opening.",
            ))
            gap.wall_id = None
            continue
        gap.wall_id = best[1].id
        gap.position = _pt(best[2])
    return issues


def process_map(fmap: FloorMap, options: ProcessingOptions | None = None) -> ProcessingResult:
    """Run the full clean-up pipeline and return a new map plus what changed."""
    opts = options or ProcessingOptions()
    if not fmap.walls:
        raise FloorPlanError("Map has no walls. A tactile map needs at least one wall segment.")

    steps: list[str] = []
    issues: list[ValidationIssue] = []
    out = fmap.model_copy(deep=True)

    removed = remove_short_walls(out, opts.min_wall_length_m)
    if removed:
        steps.append(f"Removed {len(removed)} wall fragment(s) shorter than {opts.min_wall_length_m} m.")
        issues += [ValidationIssue(severity="info", code="short_wall_removed", element_id=wid,
                                   message=f"Wall '{wid}' was shorter than {opts.min_wall_length_m} m and was removed.")
                   for wid in removed]
    if not out.walls:
        raise FloorPlanError("Every wall was shorter than the minimum length; nothing is left to map.")

    moved = snap_wall_endpoints(out, opts.snap_tolerance_m)
    if moved:
        steps.append(f"Snapped {moved} wall endpoint(s) to close corners and junctions.")

    if opts.align_to_axes:
        angle = dominant_angle(out.walls)
        if abs(angle) > math.radians(0.05):
            out = transform_map(out, -angle)
            steps.append(f"Rotated the plan by {math.degrees(-angle):.1f}° so the main walls run along the page edges.")

    issues += attach_gaps_to_walls(out, opts.gap_attach_tolerance_m)

    if opts.translate_to_origin:
        b = compute_bounds(out)
        if abs(b.min_x) > 1e-9 or abs(b.min_y) > 1e-9:
            out = transform_map(out, 0.0, (-b.min_x, -b.min_y))
            steps.append("Moved the plan so its lower-left corner is at the origin.")

    out.bounds = compute_bounds(out)
    issues += validate_map(out)
    return ProcessingResult(map=out, issues=issues, steps=steps)


# --------------------------------------------------------------------------- validation


def _point_in_polygon(p: Point2D, poly: list[Point2D]) -> bool:
    inside = False
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        if (a.y > p.y) != (b.y > p.y):
            x_cross = a.x + (p.y - a.y) * (b.x - a.x) / (b.y - a.y)
            if p.x < x_cross:
                inside = not inside
    return inside


def validate_map(fmap: FloorMap) -> list[ValidationIssue]:
    """Check a map for problems. Errors block STL generation; warnings do not."""
    issues: list[ValidationIssue] = []

    def err(code: str, message: str, element_id: str | None = None) -> None:
        issues.append(ValidationIssue(severity="error", code=code, message=message, element_id=element_id))

    def warn(code: str, message: str, element_id: str | None = None) -> None:
        issues.append(ValidationIssue(severity="warning", code=code, message=message, element_id=element_id))

    if not fmap.walls:
        err("no_walls", "The map has no walls.")

    collections = {
        "wall": fmap.walls, "door": fmap.doors, "opening": fmap.openings, "window": fmap.windows,
        "object": fmap.objects, "room": fmap.rooms, "landmark": fmap.landmarks,
        "node": fmap.navigation.nodes, "edge": fmap.navigation.edges,
    }
    for kind, items in collections.items():
        for item_id, count in Counter(i.id for i in items).items():
            if count > 1:
                err("duplicate_id", f"{count} {kind}s share the id '{item_id}'.", item_id)

    for w in fmap.walls:
        if w.length < 1e-6:
            err("zero_length_wall", f"Wall '{w.id}' has zero length.", w.id)

    wall_ids = {w.id for w in fmap.walls}
    for gap in fmap.gaps:
        if gap.wall_id is not None and gap.wall_id not in wall_ids:
            err("missing_wall", f"{gap.kind.capitalize()} '{gap.id}' refers to missing wall '{gap.wall_id}'.", gap.id)
        elif gap.wall_id is not None:
            wall = fmap.wall_by_id(gap.wall_id)
            assert wall is not None
            if gap.width > wall.length:
                warn("gap_wider_than_wall", f"{gap.kind.capitalize()} '{gap.id}' is wider than its wall.", gap.id)

    node_ids = {n.id for n in fmap.navigation.nodes}
    landmark_ids = {lm.id for lm in fmap.landmarks}
    room_ids = {r.id for r in fmap.rooms}
    for e in fmap.navigation.edges:
        for end in (e.a, e.b):
            if end not in node_ids:
                err("missing_node", f"Path '{e.id}' refers to missing location '{end}'.", e.id)
        if e.a == e.b:
            err("self_loop", f"Path '{e.id}' starts and ends at the same location.", e.id)
    for n in fmap.navigation.nodes:
        if n.landmark_id is not None and n.landmark_id not in landmark_ids:
            warn("missing_landmark", f"Location '{n.id}' refers to missing landmark '{n.landmark_id}'.", n.id)
        if n.room_id is not None and n.room_id not in room_ids:
            warn("missing_room", f"Location '{n.id}' refers to missing room '{n.room_id}'.", n.id)
    for lm in fmap.landmarks:
        if lm.nav_node_id is not None and lm.nav_node_id not in node_ids:
            err("missing_node", f"Landmark '{lm.name}' refers to missing location '{lm.nav_node_id}'.", lm.id)
    if fmap.start_landmark_id is not None and fmap.start_landmark_id not in landmark_ids:
        err("missing_start", f"Starting landmark '{fmap.start_landmark_id}' does not exist.")

    if fmap.walls:
        b = compute_bounds(fmap)
        pad = 0.5
        for lm in fmap.landmarks:
            if not (b.min_x - pad <= lm.position.x <= b.max_x + pad and b.min_y - pad <= lm.position.y <= b.max_y + pad):
                warn("landmark_outside", f"Landmark '{lm.name}' is outside the scanned area.", lm.id)

    if fmap.rooms:
        for lm in fmap.landmarks:
            if not any(_point_in_polygon(lm.position, r.polygon) for r in fmap.rooms):
                warn("landmark_not_in_room", f"Landmark '{lm.name}' is not inside any named room.", lm.id)

    if not any(lm.type.value == "entrance" for lm in fmap.landmarks):
        warn("no_entrance", "No entrance is marked. Mark one so routes and the map have a starting point.")

    return issues
