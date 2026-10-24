"""Deterministic X/Z geometry. Heading zero is -Z; positive heading is +X."""
from __future__ import annotations

import heapq
import math
from datetime import datetime, timezone

from shapely.geometry import LineString, Point as ShapePoint, Polygon
from shapely.ops import unary_union

from .models import Geometry, Landmarks, Manifest, Navigation, Point, Pose


class SpatialError(ValueError):
    pass


def distance(a: Point, b: Point) -> float:
    return math.hypot(a.x - b.x, a.z - b.z)


class SpatialEngine:
    def __init__(self, manifest: Manifest, geometry: Geometry, landmarks: Landmarks, navigation: Navigation):
        self.manifest, self.geometry, self.landmarks, self.navigation = manifest, geometry, landmarks, navigation
        self.rooms = {r.id: r for r in geometry.rooms}
        self.nodes = {n.id: n for n in navigation.nodes}
        self.doors = {d.id: d for d in navigation.doors}
        self.polygons = {r.id: Polygon([(p.x, p.z) for p in r.polygon]) for r in geometry.rooms}
        self.walkable = unary_union(list(self.polygons.values()))
        blockers = [LineString([(w.a.x, w.a.z), (w.b.x, w.b.z)]) for w in geometry.walls]
        blockers += [Polygon([(p.x, p.z) for p in o.polygon]) for o in geometry.obstacles]
        self.blockers = unary_union(blockers)
        self.adjacency: dict[str, list[tuple[str, float]]] = {n.id: [] for n in navigation.nodes}
        for e in navigation.edges:
            a, b = self.nodes[e.a], self.nodes[e.b]
            if e.doorId is not None and not self.doors[e.doorId].traversable:
                continue
            cost = distance(a.position, b.position)
            self.adjacency[e.a].append((e.b, cost))
            self.adjacency[e.b].append((e.a, cost))

    def segment_valid(self, a: Point, b: Point) -> bool:
        if distance(a, b) < 1e-8:
            shape = ShapePoint(a.x, a.z)
        else:
            shape = LineString([(a.x, a.z), (b.x, b.z)])
        return self.walkable.covers(shape) and (self.blockers.is_empty or self.blockers.distance(shape) > self.navigation.clearance)

    def room_at(self, p: Point) -> str | None:
        return next((rid for rid, poly in self.polygons.items() if poly.covers(ShapePoint(p.x, p.z))), None)

    def checked_pose(self, pose: Pose | None) -> Pose:
        if pose is None or pose.tracking != "localized" or not pose.frameVerified:
            raise SpatialError("Position is uncertain. Live guidance is paused; map-only questions are available.")
        if not self.manifest.worldMapIncluded or pose.coordinateFrameId != self.manifest.coordinateFrameId:
            raise SpatialError("The saved coordinate frame is not verified.")
        age = (datetime.now(timezone.utc) - pose.timestamp).total_seconds()
        if age > 10 or age < -3:
            raise SpatialError("Position is stale. Refresh live tracking before asking for directions.")
        if self.room_at(pose.position) is None:
            raise SpatialError("Position is outside the scanned area.")
        return pose

    def relative(self, pose: Pose, target: Point) -> dict:
        bearing = math.atan2(target.x - pose.position.x, -(target.z - pose.position.z))
        angle = math.atan2(math.sin(bearing - pose.heading), math.cos(bearing - pose.heading))
        direction = "ahead" if abs(angle) <= math.pi / 4 else "behind" if abs(angle) >= 3 * math.pi / 4 else "right" if angle > 0 else "left"
        return {"distanceMeters": round(distance(pose.position, target), 3), "angleRadians": round(angle, 6), "direction": direction, "reference": "phone-facing"}

    def nearest_node(self, p: Point) -> str:
        # Connect only to a nearby visible node; never snap across walls or unknown space.
        candidates = sorted(self.nodes.values(), key=lambda n: (distance(p, n.position), n.id))
        for n in candidates:
            if n.roomId == self.room_at(p) and distance(p, n.position) <= 1.5 and self.segment_valid(p, n.position):
                return n.id
        raise SpatialError("No safe connection to the route graph at this position.")

    def route(self, start: str, end: str) -> dict:
        if start not in self.nodes or end not in self.nodes:
            raise SpatialError("Unknown route node.")
        costs, previous = {start: 0.0}, {}
        queue = [(distance(self.nodes[start].position, self.nodes[end].position), 0.0, start)]
        while queue:
            _, g, current = heapq.heappop(queue)
            if g > costs[current] + 1e-9:
                continue
            if current == end:
                ids = [end]
                while ids[-1] != start:
                    ids.append(previous[ids[-1]])
                ids.reverse()
                protected = {n for e in self.navigation.edges if e.doorId for n in (e.a, e.b)}
                waypoints = []
                for i, node_id in enumerate(ids):
                    p = self.nodes[node_id].position
                    keep = i == 0 or i == len(ids)-1 or node_id in protected
                    if not keep:
                        a, b = self.nodes[ids[i-1]].position, self.nodes[ids[i+1]].position
                        dx, dz, ex, ez = p.x-a.x, p.z-a.z, b.x-p.x, b.z-p.z
                        keep = abs(dx*ez-dz*ex) > 1e-8 or dx*ex+dz*ez < 0
                    if keep:
                        waypoints.append(p.model_dump())
                return {"nodeIds": ids, "waypoints": waypoints, "distanceMeters": round(g, 3)}
            for neighbor, weight in sorted(self.adjacency[current]):
                cost = g + weight
                if cost < costs.get(neighbor, math.inf):
                    costs[neighbor], previous[neighbor] = cost, current
                    heapq.heappush(queue, (cost + distance(self.nodes[neighbor].position, self.nodes[end].position), cost, neighbor))
        raise SpatialError("This destination is unreachable in the scanned navigation graph.")

    def components(self) -> int:
        unseen, count = set(self.nodes), 0
        while unseen:
            count += 1
            stack = [unseen.pop()]
            while stack:
                for n, _ in self.adjacency[stack.pop()]:
                    if n in unseen:
                        unseen.remove(n)
                        stack.append(n)
        return count
