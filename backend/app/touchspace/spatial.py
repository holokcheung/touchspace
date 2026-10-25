"""Deterministic occupancy-grid A*. The Swift implementation uses the same predicates.

Unknown cells are blocked. Clearance is sampled at 16 points around the body and
walls/objects receive an analytic clearance test. Every 5cm of an edge is checked.
No LLM output can create a path or change this geometry.
"""
from __future__ import annotations

import heapq
import math

from .models import MapPackage, Point


def distance(a: Point, b: Point) -> float:
    return math.hypot(a.x - b.x, a.z - b.z)


def segment_distance(p: Point, a: Point, b: Point) -> float:
    dx, dz = b.x - a.x, b.z - a.z
    t = max(0, min(1, ((p.x-a.x)*dx + (p.z-a.z)*dz) / (dx*dx+dz*dz or 1)))
    return math.hypot(p.x-a.x-t*dx, p.z-a.z-t*dz)


def inside(p: Point, poly: list[Point]) -> bool:
    result = False
    for a, b in zip(poly, poly[1:] + poly[:1]):
        if segment_distance(p, a, b) < 1e-7:
            return True
        if (a.z > p.z) != (b.z > p.z) and p.x < (b.x-a.x)*(p.z-a.z)/(b.z-a.z)+a.x:
            result = not result
    return result


class SpatialError(ValueError):
    pass


class SpatialEngine:
    def __init__(self, package: MapPackage):
        self.package = package
        self.geo, self.nav = package.geometry, package.navigation
        points = [p for r in self.geo.rooms for p in r.polygon]
        self.min_x = math.floor(min(p.x for p in points) / self.nav.resolution)
        self.max_x = math.ceil(max(p.x for p in points) / self.nav.resolution)
        self.min_z = math.floor(min(p.z for p in points) / self.nav.resolution)
        self.max_z = math.ceil(max(p.z for p in points) / self.nav.resolution)
        if (self.max_x-self.min_x+1)*(self.max_z-self.min_z+1) > 300_000:
            raise SpatialError("Scanned zone is too large for the MVP grid")
        self._cache: dict[tuple[int, int], bool] = {}
        # Split walls at confirmed passages; unknown and blocked doors stay solid.
        self.passages = []
        rooms = {r.id:r for r in self.geo.rooms}
        walls = {w.id:w for w in self.geo.walls}
        for door in self.nav.doors:
            if door.traversability != "confirmed" or len(door.room_ids) != 2:
                continue
            length = distance(door.start,door.end)
            if length < 1e-6:
                continue
            reach = walls[door.wall_id].thickness/2+0.2
            nx = -(door.end.z-door.start.z)/length*reach
            nz = (door.end.x-door.start.x)/length*reach
            mid = Point(x=(door.start.x+door.end.x)/2,z=(door.start.z+door.end.z)/2)
            plus,minus = Point(x=mid.x+nx,z=mid.z+nz),Point(x=mid.x-nx,z=mid.z-nz)
            a,b = [rooms[r] for r in door.room_ids]
            if not ((inside(plus,a.polygon) and inside(minus,b.polygon)) or
                    (inside(minus,a.polygon) and inside(plus,b.polygon))):
                continue
            polygon = [Point(x=door.start.x+nx,z=door.start.z+nz),Point(x=door.end.x+nx,z=door.end.z+nz),
                       Point(x=door.end.x-nx,z=door.end.z-nz),Point(x=door.start.x-nx,z=door.start.z-nz)]
            self.passages.append((door,polygon,reach))
        self.wall_segments = []
        for wall in self.geo.walls:
            length = distance(wall.start, wall.end)
            if length < 1e-6:
                raise SpatialError("Zero-length wall")
            cuts = [(0., 1.)]
            dx, dz = wall.end.x-wall.start.x, wall.end.z-wall.start.z
            for door in self.nav.doors:
                if door.wall_id != wall.id or door.traversability != "confirmed":
                    continue
                ts = sorted(((p.x-wall.start.x)*dx+(p.z-wall.start.z)*dz)/(length*length)
                            for p in [door.start, door.end])
                lo, hi = max(0., ts[0]), min(1., ts[1])
                cuts = [(u, v) for a, b in cuts for u, v in [(a, min(b, lo)), (max(a, hi), b)] if v-u > 1e-6]
            for a, b in cuts:
                self.wall_segments.append((Point(x=wall.start.x+a*dx, z=wall.start.z+a*dz),
                                           Point(x=wall.start.x+b*dx, z=wall.start.z+b*dz), wall.thickness))
        nodes = {n.id: n for n in self.nav.nodes}
        for edge in self.nav.edges:
            if edge.confirmed and (edge.clearance < self.nav.clearance or
                    not self.clear_segment(nodes[edge.source].position, nodes[edge.target].position)):
                raise SpatialError("Confirmed graph edge crosses blocked or unknown space")

    def covered(self, p: Point) -> bool:
        return self.room_at(p) is not None

    def walkable(self, p: Point) -> bool:
        c = self.nav.clearance
        if not self.covered(p):
            return False
        for i in range(16):
            a = i*math.pi/8
            if not self.covered(Point(x=p.x+c*math.cos(a), z=p.z+c*math.sin(a))):
                return False
        if any(segment_distance(p, a, b) < c+t/2-1e-7 for a, b, t in self.wall_segments):
            return False
        for obstacle in self.geo.obstacles:
            poly = obstacle.polygon
            if inside(p, poly) or any(segment_distance(p, a, b) < c-1e-7 for a, b in zip(poly, poly[1:]+poly[:1])):
                return False
        return True

    def clear_segment(self, a: Point, b: Point) -> bool:
        count = max(1, math.ceil(distance(a, b)/0.05))
        previous_room = None
        for i in range(count+1):
            p = Point(x=a.x+(b.x-a.x)*i/count, z=a.z+(b.z-a.z)*i/count)
            if not self.walkable(p):
                return False
            room = self.room_at(p)
            if previous_room is not None and room.id != previous_room.id:
                if not any(d.traversability == "confirmed" and room.id in d.room_ids and previous_room.id in d.room_ids
                           and segment_distance(p,d.start,d.end) <= next(w.thickness/2+0.25 for w in self.geo.walls if w.id == d.wall_id) for d in self.nav.doors):
                    return False
            previous_room = room
        return True

    def room_at(self, p: Point):
        room = next((r for r in self.geo.rooms if inside(p, r.polygon)), None)
        if room is not None:
            return room
        for door,polygon,_ in self.passages:
            if inside(p,polygon):
                return next(r for r in self.geo.rooms if r.id == door.room_ids[0])
        return None

    def point(self, cell: tuple[int, int]) -> Point:
        return Point(x=cell[0]*self.nav.resolution, z=cell[1]*self.nav.resolution)

    def cell_ok(self, cell):
        if cell not in self._cache:
            self._cache[cell] = (self.min_x <= cell[0] <= self.max_x and self.min_z <= cell[1] <= self.max_z
                                 and self.walkable(self.point(cell)))
        return self._cache[cell]

    def nearest_cell(self, p: Point):
        # Half-away-from-zero rounding matches Swift (Python round uses bankers rounding).
        def rounded(v):
            return math.floor(v+0.5) if v >= 0 else math.ceil(v-0.5)
        x, z = rounded(p.x/self.nav.resolution), rounded(p.z/self.nav.resolution)
        candidates = [(x+dx, z+dz) for dx in range(-2, 3) for dz in range(-2, 3)]
        candidates.sort(key=lambda c: (distance(p, self.point(c)), c))
        return next((c for c in candidates if self.cell_ok(c) and self.clear_segment(p, self.point(c))), None)

    def route(self, start: Point, destination_id: str) -> dict:
        target = next((l for l in self.package.landmarks.landmarks if l.id == destination_id), None)
        if target is None:
            raise SpatialError("Unknown destination ID")
        source, goal = self.nearest_cell(start), self.nearest_cell(target.position)
        if source is None or goal is None:
            raise SpatialError("Start or destination lacks scanned clearance")
        queue = [(distance(self.point(source), self.point(goal)), source)]
        scores, parents = {source: 0.}, {}
        closed = set()
        while queue:
            _, cell = heapq.heappop(queue)
            if cell in closed:
                continue
            if cell == goal:
                cells = [cell]
                while cell in parents:
                    cell = parents[cell]
                    cells.append(cell)
                points = [start] + [self.point(c) for c in reversed(cells)] + [target.position]
                # Collinear simplification only; retain doorway samples and check each replacement.
                simplified = [points[0]]
                for index in range(1, len(points)-1):
                    a, b, c = simplified[-1], points[index], points[index+1]
                    cross = abs((b.x-a.x)*(c.z-b.z)-(b.z-a.z)*(c.x-b.x))
                    at_door = any(segment_distance(b, d.start, d.end) < 0.2 for d in self.nav.doors)
                    if at_door or cross > 1e-7 or not self.clear_segment(a, c):
                        if distance(simplified[-1], b) > 1e-7:
                            simplified.append(b)
                if distance(simplified[-1], points[-1]) > 1e-7:
                    simplified.append(points[-1])
                return {"destinationId": target.id, "waypoints": [p.model_dump() for p in simplified],
                        "distance": sum(distance(a,b) for a,b in zip(simplified, simplified[1:]))}
            closed.add(cell)
            if len(closed) > 150_000:
                break
            for dx, dz in [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]:
                nxt = (cell[0]+dx, cell[1]+dz)
                if not self.cell_ok(nxt):
                    continue
                if dx and dz and (not self.cell_ok((cell[0]+dx,cell[1])) or not self.cell_ok((cell[0],cell[1]+dz))):
                    continue
                if not self.clear_segment(self.point(cell), self.point(nxt)):
                    continue
                cost = scores[cell] + math.hypot(dx, dz)*self.nav.resolution
                if cost + 1e-8 < scores.get(nxt, math.inf):
                    scores[nxt], parents[nxt] = cost, cell
                    heapq.heappush(queue, (cost+distance(self.point(nxt), self.point(goal)), nxt))
        raise SpatialError("No validated route through this scanned zone")

    def bearing(self, origin: Point, heading: float, destination: Point) -> dict:
        angle = (math.atan2(destination.x-origin.x, -(destination.z-origin.z))-heading+math.pi)%(2*math.pi)-math.pi
        degrees = math.degrees(angle)
        direction = "ahead" if abs(degrees) <= 30 else "behind" if abs(degrees) >= 150 else "right" if degrees > 0 else "left"
        return {"distance": round(distance(origin, destination), 2), "relativeDegrees": round(degrees, 1), "direction": direction}
