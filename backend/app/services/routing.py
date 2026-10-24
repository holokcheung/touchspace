"""Route planning on a map's navigation graph, and spoken directions derived from the path.

Ground rules:
* Only edges in the map's navigation graph are walkable. Nothing is inferred from walls or
  open space, so a missing connection means "no route", never a guess.
* We don't know which way the person is facing (no live tracking), so the first instruction
  uses map directions ("toward the top of the map"), the same frame as the tactile print.
  Later turns are relative to the previous leg of the route.
* Directions never claim a path is clear or safe; callers add a safety note.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

from pydantic import BaseModel, computed_field

from app.models.map import FloorMap, Landmark, LandmarkType, NavNode, Point2D

STRAIGHT_DEG = 25.0
SLIGHT_DEG = 60.0
TURN_DEG = 135.0
PASS_LIMIT = 3
SAFETY_NOTE = ("These directions follow the paths recorded on this map. They can't detect obstacles, "
               "so keep using your cane, guide dog, or usual travel skills.")


class RouteStep(BaseModel):
    kind: str  # start | walk | arrive
    instruction: str
    distance_m: float = 0.0
    node_ids: list[str] = []


class RouteResult(BaseModel):
    found: bool
    origin_node: str
    destination_node: str
    origin_name: str
    destination_name: str
    node_ids: list[str] = []
    points: list[Point2D] = []
    distance_m: float = 0.0
    steps: list[RouteStep] = []
    avoided_stairs: bool = False
    reason: str | None = None

    @computed_field
    @property
    def spoken(self) -> str:
        if not self.found:
            return self.reason or "I couldn't find a route."
        return " ".join(s.instruction for s in self.steps)


class RoutingError(ValueError):
    """Raised for bad input (unknown node/landmark). The message is safe to show."""


@dataclass
class _Edge:
    to: str
    weight: float
    has_steps: bool


# --------------------------------------------------------------------------- graph


def _node_landmark(fmap: FloorMap, node: NavNode) -> Landmark | None:
    if node.landmark_id:
        lm = fmap.landmark_by_id(node.landmark_id)
        if lm:
            return lm
    return next((lm for lm in fmap.landmarks if lm.nav_node_id == node.id), None)


def _is_stairs(fmap: FloorMap, node: NavNode) -> bool:
    lm = _node_landmark(fmap, node)
    return lm is not None and lm.type == LandmarkType.stairs


def build_graph(fmap: FloorMap, *, avoid_stairs: bool = False, keep: set[str] = frozenset()) -> dict[str, list[_Edge]]:
    nodes = {n.id: n for n in fmap.navigation.nodes}
    blocked = {n.id for n in nodes.values() if avoid_stairs and _is_stairs(fmap, n) and n.id not in keep}
    graph: dict[str, list[_Edge]] = {nid: [] for nid in nodes}
    for e in fmap.navigation.edges:
        if not e.traversable or e.a not in nodes or e.b not in nodes or e.a == e.b:
            continue
        has_steps = e.accessibility == "has_steps"
        if avoid_stairs and (has_steps or e.a in blocked or e.b in blocked):
            continue
        w = math.dist(nodes[e.a].position.as_tuple(), nodes[e.b].position.as_tuple())
        graph[e.a].append(_Edge(e.b, w, has_steps))
        graph[e.b].append(_Edge(e.a, w, has_steps))
    return graph


def shortest_path(graph: dict[str, list[_Edge]], start: str, goal: str) -> tuple[list[str], float] | None:
    """Dijkstra. Returns (node ids, length in meters) or None when unreachable."""
    if start not in graph or goal not in graph:
        return None
    dist = {start: 0.0}
    prev: dict[str, str] = {}
    heap = [(0.0, start)]
    while heap:
        d, u = heapq.heappop(heap)
        if u == goal:
            path = [u]
            while path[-1] != start:
                path.append(prev[path[-1]])
            return path[::-1], d
        if d > dist.get(u, math.inf):
            continue
        for e in graph[u]:
            nd = d + e.weight
            if nd < dist.get(e.to, math.inf):
                dist[e.to] = nd
                prev[e.to] = u
                heapq.heappush(heap, (nd, e.to))
    return None


# --------------------------------------------------------------------------- wording


def _heading(a: Point2D, b: Point2D) -> float:
    """Degrees CCW from east (plan +x)."""
    return math.degrees(math.atan2(b.y - a.y, b.x - a.x))


def _delta(h1: float, h2: float) -> float:
    """Signed turn from h1 to h2 in (-180, 180]; positive is a left turn."""
    d = (h2 - h1 + 180) % 360 - 180
    return 180.0 if d == -180 else d


COMPASS = ["east", "northeast", "north", "northwest", "west", "southwest", "south", "southeast"]
MAP_WORDS = {
    "north": "toward the top of the map", "south": "toward the bottom of the map",
    "east": "toward the right side of the map", "west": "toward the left side of the map",
    "northeast": "toward the top right of the map", "northwest": "toward the top left of the map",
    "southeast": "toward the bottom right of the map", "southwest": "toward the bottom left of the map",
}


def compass(heading_deg: float) -> str:
    return COMPASS[int(((heading_deg % 360) + 22.5) // 45) % 8]


def meters(d: float) -> str:
    if d < 1.0:
        return "less than a meter"
    v = round(d * 2) / 2 if d < 10 else round(d)
    text = f"{v:g}"
    return f"about {text} meter{'s' if v != 1 else ''}"


def turn_phrase(delta: float) -> str | None:
    a = abs(delta)
    side = "left" if delta > 0 else "right"
    if a < STRAIGHT_DEG:
        return None
    if a < SLIGHT_DEG:
        return f"bear {side}"
    if a < TURN_DEG:
        return f"turn {side}"
    return "turn around"


def side_of(a: Point2D, b: Point2D, p: Point2D, min_offset: float = 0.3) -> str | None:
    """'left'/'right' of the walk from a to b, or None when p is roughly in line with it."""
    length = math.dist(a.as_tuple(), b.as_tuple()) or 1.0
    cross = ((b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x)) / length
    if abs(cross) < min_offset:
        return None
    return "left" if cross > 0 else "right"


def _node_name(fmap: FloorMap, node: NavNode) -> str:
    lm = _node_landmark(fmap, node)
    if lm:
        return lm.name
    return node.label or node.id


# --------------------------------------------------------------------------- route + instructions


def resolve_node(fmap: FloorMap, ref: str) -> NavNode:
    """Accepts a landmark id or a navigation node id."""
    nodes = {n.id: n for n in fmap.navigation.nodes}
    if ref in nodes:
        return nodes[ref]
    lm = fmap.landmark_by_id(ref)
    if lm is None:
        raise RoutingError(f"'{ref}' is not a known place on this map.")
    if lm.nav_node_id and lm.nav_node_id in nodes:
        return nodes[lm.nav_node_id]
    linked = next((n for n in nodes.values() if n.landmark_id == lm.id), None)
    if linked:
        return linked
    raise RoutingError(f"{lm.name} isn't linked to a walkable location yet, so I can't plan a route to or from it. "
                       "Link it in the floor-plan editor.")


def plan_route(fmap: FloorMap, origin: str, destination: str, *, avoid_stairs: bool = False) -> RouteResult:
    start = resolve_node(fmap, origin)
    goal = resolve_node(fmap, destination)
    origin_name = fmap.landmark_by_id(origin).name if fmap.landmark_by_id(origin) else _node_name(fmap, start)
    dest_lm = fmap.landmark_by_id(destination)
    dest_name = dest_lm.name if dest_lm else _node_name(fmap, goal)
    base = dict(origin_node=start.id, destination_node=goal.id, origin_name=origin_name,
                destination_name=dest_name, avoided_stairs=avoid_stairs)

    if start.id == goal.id:
        step = RouteStep(kind="arrive", instruction=f"You're already at {dest_name}.", node_ids=[start.id])
        return RouteResult(found=True, node_ids=[start.id], points=[start.position], steps=[step], **base)

    found = shortest_path(build_graph(fmap, avoid_stairs=avoid_stairs, keep={start.id, goal.id}), start.id, goal.id)
    if found is None:
        if avoid_stairs and shortest_path(build_graph(fmap), start.id, goal.id) is not None:
            reason = (f"Every recorded path from {origin_name} to {dest_name} uses stairs. "
                      "Turn off 'avoid stairs' to hear that route.")
        else:
            reason = (f"There's no recorded walkable path between {origin_name} and {dest_name} on this map, "
                      "so I can't give directions. Paths can be added in the floor-plan editor.")
        return RouteResult(found=False, reason=reason, **base)

    path, length = found
    nodes = {n.id: n for n in fmap.navigation.nodes}
    pts = [nodes[i].position for i in path]
    steps = _instructions(fmap, path, nodes, origin_name, dest_name, dest_lm)
    return RouteResult(found=True, node_ids=path, points=pts, distance_m=round(length, 2), steps=steps, **base)


def _instructions(fmap: FloorMap, path: list[str], nodes: dict[str, NavNode], origin_name: str,
                  dest_name: str, dest_lm: Landmark | None) -> list[RouteStep]:
    pts = [nodes[i].position for i in path]
    graph = build_graph(fmap)

    # Group segments into legs: a new leg starts at a real turn or at a door.
    legs: list[list[int]] = [[0]]
    for i in range(1, len(path) - 1):
        turn = abs(_delta(_heading(pts[i - 1], pts[i]), _heading(pts[i], pts[i + 1])))
        if turn >= STRAIGHT_DEG or nodes[path[i]].kind == "door":
            legs[-1].append(i)
            legs.append([i])
    legs[-1].append(len(path) - 1)

    steps = [RouteStep(kind="start", instruction=f"Start at {origin_name}.", node_ids=[path[0]])]
    on_path = set(path)
    mentioned: set[str] = set()
    prev_heading: float | None = None
    for leg in legs:
        a_i, b_i = leg[0], leg[-1]
        a, b = pts[a_i], pts[b_i]
        length = sum(math.dist(pts[k].as_tuple(), pts[k + 1].as_tuple()) for k in range(a_i, b_i))
        heading = _heading(pts[a_i], pts[a_i + 1])
        if prev_heading is None:
            direction = compass(heading)
            text = f"Head {direction}, {MAP_WORDS[direction]}, for {meters(length)}"
        else:
            phrase = turn_phrase(_delta(prev_heading, heading))
            text = f"{(phrase or 'continue straight').capitalize()} and go {meters(length)}"
        end_node = nodes[path[b_i]]
        if end_node.kind == "door" and b_i != len(path) - 1:
            text += f" to the {end_node.label or 'door'}, then go through it"

        # Doorways next to this leg (one graph hop off the path) help confirm progress.
        passes = []
        for k in range(a_i + 1, b_i + 1):
            for e in graph.get(path[k], []):
                n = nodes[e.to]
                if n.kind != "door" or n.id in on_path or n.id in mentioned or not n.label:
                    continue
                side = side_of(a, b, n.position)
                if side is None:
                    continue
                mentioned.add(n.id)
                passes.append(f"the {n.label} on your {side}")
        if passes:
            text += ", passing " + _join(passes[:PASS_LIMIT])
        steps.append(RouteStep(kind="walk", instruction=text + ".", distance_m=round(length, 2), node_ids=path[a_i:b_i + 1]))
        prev_heading = _heading(pts[b_i - 1], pts[b_i])

    arrive = f"You'll reach {dest_name}"
    if dest_lm is not None and prev_heading is not None and len(pts) >= 2:
        target = dest_lm.position
        if math.dist(target.as_tuple(), pts[-1].as_tuple()) > 0.75:
            rel = _delta(prev_heading, _heading(pts[-1], target))
            where = "ahead" if abs(rel) < 45 else ("on your left" if rel > 0 else "on your right") if abs(rel) < 135 else "behind you"
            arrive += f", {where}"
    steps.append(RouteStep(kind="arrive", instruction=arrive + ".", node_ids=[path[-1]]))
    return steps


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]
