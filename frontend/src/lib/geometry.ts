import type { FloorMap, NavNode, Point2D, Room, Wall, WallGap } from "../api/types";

export const dist = (a: Point2D, b: Point2D) => Math.hypot(a.x - b.x, a.y - b.y);

export function pointInPolygon(p: Point2D, poly: Point2D[]): boolean {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const a = poly[i];
    const b = poly[j];
    if (a.y > p.y !== b.y > p.y && p.x < ((b.x - a.x) * (p.y - a.y)) / (b.y - a.y) + a.x) inside = !inside;
  }
  return inside;
}

/** Area-weighted centroid; falls back to the vertex average for degenerate polygons. */
export function polygonCentroid(poly: Point2D[]): Point2D {
  let a = 0;
  let cx = 0;
  let cy = 0;
  for (let i = 0; i < poly.length; i++) {
    const p = poly[i];
    const q = poly[(i + 1) % poly.length];
    const cross = p.x * q.y - q.x * p.y;
    a += cross;
    cx += (p.x + q.x) * cross;
    cy += (p.y + q.y) * cross;
  }
  if (Math.abs(a) < 1e-9) {
    return { x: poly.reduce((s, p) => s + p.x, 0) / poly.length, y: poly.reduce((s, p) => s + p.y, 0) / poly.length };
  }
  return { x: cx / (3 * a), y: cy / (3 * a) };
}

export function roomAt(map: FloorMap, p: Point2D): Room | undefined {
  return map.rooms.find((r) => pointInPolygon(p, r.polygon));
}

export function nearestNode(map: FloorMap, p: Point2D): NavNode | undefined {
  let best: NavNode | undefined;
  let bestD = Infinity;
  for (const n of map.navigation.nodes) {
    const d = dist(n.position, p);
    if (d < bestD) {
      bestD = d;
      best = n;
    }
  }
  return best;
}

export function planBounds(map: FloorMap) {
  if (map.bounds) return map.bounds;
  const xs = map.walls.flatMap((w) => [w.start.x, w.end.x]);
  const ys = map.walls.flatMap((w) => [w.start.y, w.end.y]);
  return { min_x: Math.min(...xs, 0), min_y: Math.min(...ys, 0), max_x: Math.max(...xs, 1), max_y: Math.max(...ys, 1) };
}

/** Pieces of a wall left after removing its door/opening gaps, as [start, end] pairs. */
export function wallPieces(wall: Wall, gaps: WallGap[]): [Point2D, Point2D][] {
  const len = dist(wall.start, wall.end);
  if (len === 0) return [];
  const ux = (wall.end.x - wall.start.x) / len;
  const uy = (wall.end.y - wall.start.y) / len;
  const cuts = gaps
    .map((g) => {
      const t = (g.position.x - wall.start.x) * ux + (g.position.y - wall.start.y) * uy;
      return [Math.max(0, t - g.width / 2), Math.min(len, t + g.width / 2)] as const;
    })
    .sort((a, b) => a[0] - b[0]);
  const at = (t: number): Point2D => ({ x: wall.start.x + ux * t, y: wall.start.y + uy * t });
  const pieces: [Point2D, Point2D][] = [];
  let cursor = 0;
  for (const [a, b] of cuts) {
    if (a > cursor + 1e-6) pieces.push([at(cursor), at(a)]);
    cursor = Math.max(cursor, b);
  }
  if (cursor < len - 1e-6) pieces.push([at(cursor), at(len)]);
  return pieces;
}

export function gapEnds(wall: Wall, gap: WallGap): [Point2D, Point2D] {
  const len = dist(wall.start, wall.end) || 1;
  const ux = (wall.end.x - wall.start.x) / len;
  const uy = (wall.end.y - wall.start.y) / len;
  const h = gap.width / 2;
  return [
    { x: gap.position.x - ux * h, y: gap.position.y - uy * h },
    { x: gap.position.x + ux * h, y: gap.position.y + uy * h },
  ];
}

/** "upper left", "center", ... relative to the plan bounds, for spoken/text descriptions. */
export function regionName(map: FloorMap, p: Point2D): string {
  const b = planBounds(map);
  const fx = (p.x - b.min_x) / Math.max(b.max_x - b.min_x, 1e-9);
  const fy = (p.y - b.min_y) / Math.max(b.max_y - b.min_y, 1e-9);
  const col = fx < 1 / 3 ? "west" : fx > 2 / 3 ? "east" : "";
  const row = fy < 1 / 3 ? "south" : fy > 2 / 3 ? "north" : "";
  if (row && col) return `${row}${col} corner`;
  if (row || col) return `${row || col} side`;
  return "center";
}

export const fmt = (n: number) => (Math.round(n * 10) / 10).toFixed(1);
