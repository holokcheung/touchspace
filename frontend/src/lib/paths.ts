import type { FloorMap, NavEdge, NavNode, Point2D } from "../api/types";
import { dist, pointInPolygon, regionName, roomAt, wallPieces } from "./geometry";

/** Something a walking path can start or end at: an existing graph node, a landmark, or a doorway. */
export interface PathPoint {
  key: string;
  label: string;
  position: Point2D;
  kind: "node" | "landmark" | "door";
  ref: string;
}

const WALL_CLEARANCE_M = 0.05;

function doorLabel(map: FloorMap, doorId: string): string {
  const door = [...map.doors, ...map.openings].find((d) => d.id === doorId);
  if (!door) return "Doorway";
  const wall = map.walls.find((w) => w.id === door.wall_id);
  const kind = door.kind === "door" ? "Door" : "Opening";
  if (!wall) return kind;
  // What is on each side of the wall: a different room if there is one, otherwise the
  // nearest named place on that side (scans often have one floor outline for many areas).
  const len = dist(wall.start, wall.end) || 1;
  const nx = -(wall.end.y - wall.start.y) / len;
  const ny = (wall.end.x - wall.start.x) / len;
  const probes = [1, -1].map((s) => ({ x: door.position.x + nx * 0.6 * s, y: door.position.y + ny * 0.6 * s }));
  const rooms = probes.map((pt) => roomAt(map, pt)?.name);
  const sides = probes.map((pt, i) => {
    if (rooms[0] !== rooms[1] && rooms[i]) return rooms[i];
    const nearest = map.landmarks
      .filter((l) => (l.position.x - door.position.x) * nx * (i === 0 ? 1 : -1) + (l.position.y - door.position.y) * ny * (i === 0 ? 1 : -1) > 0)
      .map((l) => ({ l, d: dist(l.position, pt) }))
      .filter((x) => x.d < 4 && !crossesWallLine(map, pt, x.l.position))
      .sort((a, b) => a.d - b.d)[0];
    return nearest?.l.name ?? rooms[i];
  });
  if (sides[0] && sides[1] && sides[0] !== sides[1]) return `${kind} between ${sides[0]} and ${sides[1]}`;
  const one = sides[0] ?? sides[1];
  return one ? `${kind} near ${one}` : kind;
}

export function pathPoints(map: FloorMap): PathPoint[] {
  const points: PathPoint[] = [];
  const nodeForLandmark = new Set<string>();
  for (const n of map.navigation.nodes) {
    const lm = map.landmarks.find((l) => l.id === n.landmark_id || l.nav_node_id === n.id);
    if (lm) nodeForLandmark.add(lm.id);
    points.push({ key: `node:${n.id}`, label: lm?.name ?? n.label ?? n.id, position: n.position, kind: "node", ref: n.id });
  }
  for (const lm of map.landmarks) {
    if (nodeForLandmark.has(lm.id)) continue;
    points.push({ key: `landmark:${lm.id}`, label: lm.name, position: lm.position, kind: "landmark", ref: lm.id });
  }
  const doorPoints: PathPoint[] = [];
  for (const d of [...map.doors, ...map.openings]) {
    if (map.navigation.nodes.some((n) => n.kind === "door" && dist(n.position, d.position) < 0.3)) continue;
    doorPoints.push({ key: `door:${d.id}`, label: doorLabel(map, d.id), position: d.position, kind: "door", ref: d.id });
  }
  // Two doors with the same description get told apart by where they are on the map.
  const counts = new Map<string, number>();
  doorPoints.forEach((dp) => counts.set(dp.label, (counts.get(dp.label) ?? 0) + 1));
  for (const dp of doorPoints) {
    if ((counts.get(dp.label) ?? 0) > 1) dp.label = `${dp.label} (${regionName(map, dp.position)})`;
  }
  points.push(...doorPoints);
  return points.sort((a, b) => a.label.localeCompare(b.label));
}

function segmentsCross(p1: Point2D, p2: Point2D, q1: Point2D, q2: Point2D): boolean {
  const o = (a: Point2D, b: Point2D, c: Point2D) => (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x);
  const d1 = o(q1, q2, p1);
  const d2 = o(q1, q2, p2);
  const d3 = o(p1, p2, q1);
  const d4 = o(p1, p2, q2);
  return d1 * d2 < 0 && d3 * d4 < 0;
}

/** Whether a to b crosses any wall's full line, doorways included: "is b in the same space as a?" */
function crossesWallLine(map: FloorMap, a: Point2D, b: Point2D): boolean {
  return map.walls.some((w) => segmentsCross(a, b, w.start, w.end));
}

/** Whether walking straight from a to b would go through a wall (door and opening gaps are allowed). */
export function crossesWall(map: FloorMap, a: Point2D, b: Point2D): boolean {
  const gaps = [...map.doors, ...map.openings];
  for (const wall of map.walls) {
    const own = gaps.filter((g) => g.wall_id === wall.id);
    for (const [p, q] of wallPieces(wall, own)) {
      // Endpoints that sit right on a wall (a doorway's own wall) don't count as crossing it.
      const touchesEnd = [a, b].some((e) => distanceToSegment(e, p, q) < WALL_CLEARANCE_M + wall.thickness / 2);
      if (!touchesEnd && segmentsCross(a, b, p, q)) return true;
    }
  }
  return false;
}

function distanceToSegment(p: Point2D, a: Point2D, b: Point2D): number {
  const abx = b.x - a.x;
  const aby = b.y - a.y;
  const t = Math.max(0, Math.min(1, ((p.x - a.x) * abx + (p.y - a.y) * aby) / (abx * abx + aby * aby || 1)));
  return dist(p, { x: a.x + abx * t, y: a.y + aby * t });
}

function uid(prefix: string): string {
  return `${prefix}_${Math.random().toString(36).slice(2, 8)}`;
}

/** Returns the node id for a point, creating a node (and linking a landmark) when needed. */
function ensureNode(map: FloorMap, point: PathPoint): [FloorMap, string] {
  if (point.kind === "node") return [map, point.ref];
  const room = map.rooms.find((r) => pointInPolygon(point.position, r.polygon));
  if (point.kind === "landmark") {
    const node: NavNode = {
      id: uid("n"), position: point.position, label: point.label, kind: "place", landmark_id: point.ref, room_id: room?.id ?? null,
    };
    return [
      {
        ...map,
        landmarks: map.landmarks.map((l) => (l.id === point.ref ? { ...l, nav_node_id: node.id } : l)),
        navigation: { ...map.navigation, nodes: [...map.navigation.nodes, node] },
      },
      node.id,
    ];
  }
  const node: NavNode = { id: uid("n_door"), position: point.position, label: point.label, kind: "door", landmark_id: null, room_id: null };
  return [{ ...map, navigation: { ...map.navigation, nodes: [...map.navigation.nodes, node] } }, node.id];
}

export type AddPathResult = { ok: true; map: FloorMap; edge: NavEdge } | { ok: false; error: string };

export function addPath(map: FloorMap, from: PathPoint, to: PathPoint, hasSteps: boolean): AddPathResult {
  if (from.key === to.key) return { ok: false, error: "Choose two different places." };
  if (crossesWall(map, from.position, to.position)) {
    return {
      ok: false,
      error: `A straight line from ${from.label} to ${to.label} passes through a wall. Connect each side to the doorway between them instead.`,
    };
  }
  let next = map;
  let a: string;
  let b: string;
  [next, a] = ensureNode(next, from);
  [next, b] = ensureNode(next, to);
  if (next.navigation.edges.some((e) => (e.a === a && e.b === b) || (e.a === b && e.b === a))) {
    return { ok: false, error: `${from.label} and ${to.label} are already connected.` };
  }
  const edge: NavEdge = {
    id: uid("e"), a, b, traversable: true, accessibility: hasSteps ? "has_steps" : "unknown", source: "manual", notes: "",
  };
  return { ok: true, map: { ...next, navigation: { ...next.navigation, edges: [...next.navigation.edges, edge] } }, edge };
}

export function removePath(map: FloorMap, edgeId: string): FloorMap {
  return { ...map, navigation: { ...map.navigation, edges: map.navigation.edges.filter((e) => e.id !== edgeId) } };
}

export function describeEdge(map: FloorMap, edge: NavEdge): { label: string; length: number } {
  const name = (id: string) => {
    const n = map.navigation.nodes.find((x) => x.id === id);
    const lm = map.landmarks.find((l) => l.id === n?.landmark_id || l.nav_node_id === id);
    return lm?.name ?? n?.label ?? id;
  };
  const na = map.navigation.nodes.find((n) => n.id === edge.a);
  const nb = map.navigation.nodes.find((n) => n.id === edge.b);
  return { label: `${name(edge.a)} ↔ ${name(edge.b)}`, length: na && nb ? dist(na.position, nb.position) : 0 };
}

