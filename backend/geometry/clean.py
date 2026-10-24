"""Step 1.5: tidy up a real scan before drawing it.

RoomPlan walls come out slightly rotated, a degree or two off square, and with small
gaps at corners. A tactile map needs straight, closed walls, so we fix that here.
All work is in metres on the map plane.
"""
import math
import numpy as np
import config


def _angle(v):
    return math.atan2(v[1], v[0])


def _unit(a):
    return np.array([math.cos(a), math.sin(a)])


def _rotate(v, a):
    c, s = math.cos(a), math.sin(a)
    return np.array([c * v[0] - s * v[1], s * v[0] + c * v[1]])


def dominant_angle(walls):
    """Main wall direction, modulo 90 degrees. Long walls count more.
    Averaging 4*angle treats 0, 90, 180, 270 degrees as the same direction.
    Second pass ignores walls far from the first estimate (diagonal or genuinely
    angled walls), so they cannot tilt the whole map."""
    def mean(ws):
        sx = sum(w.width * math.sin(4 * _angle(w.axis)) for w in ws)
        cx = sum(w.width * math.cos(4 * _angle(w.axis)) for w in ws)
        return math.atan2(sx, cx) / 4

    est = mean(walls)
    tol = math.radians(config.ORTHO_TOL_DEG)
    def off(w):
        d = (_angle(w.axis) - est) % (math.pi / 2)
        return min(d, math.pi / 2 - d)
    close = [w for w in walls if off(w) < tol]
    return mean(close) if close else est


def align(room):
    """Rotate everything so the dominant wall direction lies on the x axis."""
    a = -dominant_angle(room.walls)
    for s in room.walls + room.doors + room.windows + room.objects:
        s.center = _rotate(s.center, a)
        s.axis = _rotate(s.axis, a)
    for sec in room.sections:
        sec.center = _rotate(sec.center, a)


def orthogonalize(surfaces):
    """Snap directions that are nearly 0/90/180/270 degrees to exactly that."""
    tol = math.radians(config.ORTHO_TOL_DEG)
    for s in surfaces:
        a = _angle(s.axis)
        snapped = round(a / (math.pi / 2)) * (math.pi / 2)
        if abs(a - snapped) < tol:
            s.axis = _unit(snapped)


def merge_collinear(walls):
    """Line up walls that are parallel, almost on the same line, and end near each other.
    RoomPlan often splits one straight wall into pieces that are a few cm out of line.
    Without this, the pieces leave a small step and a gap where they should join.
    Works on walls that are already square (run after orthogonalize)."""
    tol_off = config.COLLINEAR_TOL_M
    tol_gap = config.SNAP_TOL_M
    horiz = [w for w in walls if abs(w.axis[0]) > 0.999]
    vert = [w for w in walls if abs(w.axis[1]) > 0.999]
    for group, along, across in ((horiz, 0, 1), (vert, 1, 0)):
        parent = list(range(len(group)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        def span(w):
            c, h = w.center[along], w.width / 2
            return c - h, c + h

        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                if abs(a.center[across] - b.center[across]) > tol_off:
                    continue
                (a0, a1), (b0, b1) = span(a), span(b)
                gap = max(b0 - a1, a0 - b1, 0.0)
                if gap < tol_gap:
                    parent[find(i)] = find(j)
        clusters = {}
        for i in range(len(group)):
            clusters.setdefault(find(i), []).append(group[i])
        for members in clusters.values():
            if len(members) < 2:
                continue
            total = sum(w.width for w in members)
            mean = sum(w.center[across] * w.width for w in members) / total
            for w in members:
                w.center = w.center.copy()
                w.center[across] = mean


def wall_segments(walls):
    """Walls -> list of [p0, p1] endpoint pairs (metres)."""
    return [[w.center - w.axis * w.width / 2, w.center + w.axis * w.width / 2] for w in walls]


def _line_intersection(p, d, q, e):
    """Intersection of lines p + t*d and q + u*e. Returns (point, t, u) or None if parallel."""
    den = d[0] * e[1] - d[1] * e[0]
    if abs(den) < 1e-9:
        return None
    w = q - p
    t = (w[0] * e[1] - w[1] * e[0]) / den
    u = (w[0] * d[1] - w[1] * d[0]) / den
    return p + t * d, t, u


def snap_ends(segs):
    """Extend or trim each wall end along its own direction to meet a nearby wall.
    Moving only along the wall's own axis keeps right angles intact.
    Real openings are wider than SNAP_TOL_M, so they are not closed by mistake."""
    tol = config.SNAP_TOL_M
    for i, (a0, a1) in enumerate(segs):
        d = a1 - a0
        L = np.linalg.norm(d)
        if L < 1e-6:
            continue
        d = d / L
        for end in (0, 1):
            p = segs[i][end]
            best = None
            for j, (b0, b1) in enumerate(segs):
                if i == j:
                    continue
                e = b1 - b0
                M = np.linalg.norm(e)
                if M < 1e-6:
                    continue
                hit = _line_intersection(a0, d, b0, e / M)
                if hit is None:
                    continue
                point, t, u = hit
                move = np.linalg.norm(point - p)
                on_other = -tol <= u <= M + tol
                # Never let a snap shrink a wall to (almost) nothing or flip its direction.
                # A short real wall whose both ends are near another wall would otherwise collapse.
                other_end = segs[i][1 - end]
                keeps_shape = (np.dot(point - other_end, p - other_end) > 0 and
                               np.linalg.norm(point - other_end) >= max(
                                   getattr(config, "MIN_WALL_M", 0.10), 0.5 * L))
                if move < tol and on_other and keeps_shape and (best is None or move < best[0]):
                    best = (move, point)
            if best is not None:
                segs[i][end] = best[1]
    return segs


def bridge_collinear(segs):
    """Join wall pieces that lie on the same line with a small gap between them.
    snap_ends cannot do this, because two parallel lines never intersect.
    A gap narrower than SNAP_TOL_M is too small to walk through, so it is a scan error."""
    tol = config.SNAP_TOL_M
    for i in range(len(segs)):
        for j in range(len(segs)):
            if i == j:
                continue
            a0, a1 = segs[i]
            b0, b1 = segs[j]
            d = a1 - a0
            L = np.linalg.norm(d)
            if L < 1e-6:
                continue
            d = d / L
            e = b1 - b0
            M = np.linalg.norm(e)
            if M < 1e-6 or abs(d[0] * e[1] - d[1] * e[0]) / M > 1e-3:
                continue                                  # not parallel
            n = np.array([-d[1], d[0]])
            if abs(np.dot(b0 - a0, n)) > 0.01:
                continue                                  # parallel but not on the same line
            for ea in (0, 1):
                for eb in (0, 1):
                    pa, pb = segs[i][ea], segs[j][eb]
                    gap = np.linalg.norm(pa - pb)
                    # only bridge ends that face each other (the gap lies outside both pieces)
                    outward = (pa - segs[i][1 - ea]) @ (pb - pa) > 0
                    if 1e-6 < gap < tol and outward:
                        mid = (pa + pb) / 2
                        segs[i][ea] = mid
                        segs[j][eb] = mid.copy()
    return segs


def drop_tiny(room):
    """Remove wall fragments too short to be real walls (scan noise)."""
    min_len = getattr(config, "MIN_WALL_M", 0.10)
    before = len(room.walls)
    room.walls = [w for w in room.walls if w.width >= min_len]
    if len(room.walls) < before:
        print(f"  removed {before - len(room.walls)} wall fragment(s) shorter than {min_len} m")


def snap_doors(room):
    """Move each door sideways onto the nearest parallel wall.
    RoomPlan sometimes places a door a few cm in front of its wall; then the cut misses."""
    tol = getattr(config, "DOOR_SNAP_M", 0.30)
    for d in room.doors:
        best = None
        for w in room.walls:
            if abs(abs(float(np.dot(d.axis, w.axis))) - 1) > 1e-3:
                continue                                   # not parallel
            rel = d.center - w.center
            along = float(np.dot(rel, w.axis))
            if abs(along) > w.width / 2 + tol:
                continue                                   # beside the wall, not on it
            n = np.array([-w.axis[1], w.axis[0]])
            off = float(np.dot(rel, n))
            if abs(off) < tol and (best is None or abs(off) < abs(best[0])):
                best = (off, n)
        if best is not None:
            d.center = d.center - best[0] * best[1]


def drop_outside_objects(room, segs):
    """Drop furniture whose centre lies outside the scanned walls (seen through a window)."""
    from shapely.geometry import MultiLineString, Point
    if not room.objects or not segs:
        return
    hull = MultiLineString([[tuple(a), tuple(b)] for a, b in segs]).convex_hull.buffer(0.2)
    before = len(room.objects)
    room.objects = [o for o in room.objects if hull.contains(Point(o.center))]
    if len(room.objects) < before:
        print(f"  dropped {before - len(room.objects)} object(s) outside the walls")


def scan_quality(segs):
    """Print a warning when the walls do not look like a building at all.
    Nothing is changed. The map is still made, so a person can look and decide."""
    from shapely.geometry import LineString, Point
    from shapely.ops import unary_union
    if len(segs) < 3:
        print("  warning: fewer than 3 walls; this is probably not a complete room")
        return
    lines = [LineString([tuple(a), tuple(b)]) for a, b in segs]
    loose = sum(1 for i, (a, b) in enumerate(segs) for p in (a, b)
                if min(lines[j].distance(Point(p)) for j in range(len(lines)) if j != i) > 0.05)
    shape = unary_union(lines).buffer(0.02)
    closed = sum(len(p.interiors) for p in getattr(shape, "geoms", [shape]))   # enclosed rooms
    if closed == 0:
        print("  warning: the walls do not enclose any room; the scan may be incomplete or broken")
    elif loose > len(segs):
        print(f"  warning: {loose} wall ends connect to nothing; parts of the scan may be missing")


def clean(room):
    """Run all cleanup steps. Returns wall segments in metres."""
    if not room.walls:
        raise ValueError("No walls found in the scan. Please rescan the room.")
    drop_tiny(room)
    if not room.walls:
        raise ValueError("No walls found in the scan (only tiny fragments). Please rescan.")
    if config.ALIGN_TO_AXES:
        align(room)
    orthogonalize(room.walls + room.doors + room.windows + room.objects)
    merge_collinear(room.walls)
    snap_doors(room)
    segs = bridge_collinear(snap_ends(wall_segments(room.walls)))
    drop_outside_objects(room, segs)
    scan_quality(segs)
    return segs
