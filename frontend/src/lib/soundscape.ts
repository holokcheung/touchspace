/**
 * The walk-through's sense of space: what's near the walker on the left, ahead and right,
 * computed from the map's walls and furniture, and how that turns into sound. The numbers
 * live in shared/soundscape.json so the iPhone version maps distance to sound the same way.
 */
import type { FloorMap, Point2D } from "../api/types";
import settingsJson from "../../../shared/soundscape.json";
import { dist, gapEnds, planBounds, pointInPolygon, roomAt, wallPieces } from "./geometry";

export type ZoneId = "left" | "ahead" | "right";
export type CueName = "bump" | "doorway" | "no_data";

export interface CueSettings {
  freqs_hz: number[];
  duration_s: number;
  vibrate_ms: number[];
  repeat_s?: number;
}

export interface SoundscapeSettings {
  version: number;
  zones: { id: ZoneId; label: string; from_deg: number; to_deg: number }[];
  sensing: { max_range_m: number; ray_step_deg: number };
  noise: { color: "pink"; level: number; default_volume: number; smoothing_s: number };
  muffle: {
    open_at_m: number;
    muffled_at_m: number;
    curve: number;
    open_cutoff_hz: number;
    muffled_cutoff_hz: number;
    open_gain: number;
    muffled_gain: number;
    filter_q: number;
  };
  ahead_pulse: {
    start_at_m: number;
    fastest_at_m: number;
    slowest_hz: number;
    fastest_hz: number;
    tick_hz: number;
    tick_s: number;
    level: number;
  };
  cues: Record<CueName, CueSettings> & { level: number };
  walk: {
    step_m: number;
    turn_deg: number;
    big_turn_deg: number;
    body_radius_m: number;
    nearby_landmark_m: number;
    hold_repeat_s: number;
  };
}

export const SOUNDSCAPE = settingsJson as unknown as SoundscapeSettings;

/** Where the walker stands. Heading is a compass bearing: 0 = north (up the map), 90 = east. */
export interface Pose {
  position: Point2D;
  heading: number;
}

interface Segment {
  a: Point2D;
  b: Point2D;
  /** Half the wall's thickness: how far the surface sits from the centerline. */
  pad: number;
  label: string;
}

export interface Gap {
  id: string;
  kind: "door" | "opening";
  a: Point2D;
  b: Point2D;
  center: Point2D;
}

export interface Scene {
  map: FloorMap;
  segments: Segment[];
  gaps: Gap[];
}

export interface Reading {
  zone: ZoneId;
  label: string;
  /** Distance to the nearest surface in this zone, or null if nothing is within range. */
  distance: number | null;
  hit: Point2D | null;
  what: string | null;
}

const rad = (deg: number) => (deg * Math.PI) / 180;
const cross = (ax: number, ay: number, bx: number, by: number) => ax * by - ay * bx;
const clamp01 = (v: number) => Math.min(1, Math.max(0, v));

export function normalizeHeading(deg: number): number {
  return ((deg % 360) + 360) % 360;
}

/** Unit vector for a compass bearing (plan y points north). */
export function bearingVector(deg: number): Point2D {
  return { x: Math.sin(rad(deg)), y: Math.cos(rad(deg)) };
}

/** Walls (minus their doorways) and visible furniture, as segments a ray or the walker can hit. */
export function buildScene(map: FloorMap): Scene {
  const passable = [...map.doors, ...map.openings];
  const segments: Segment[] = [];
  for (const wall of map.walls) {
    const own = passable.filter((g) => g.wall_id === wall.id);
    for (const [a, b] of wallPieces(wall, own)) segments.push({ a, b, pad: wall.thickness / 2, label: "wall" });
  }
  for (const o of map.objects) {
    if (o.hidden) continue;
    const c = Math.cos(o.rotation);
    const s = Math.sin(o.rotation);
    const corners = [
      [-o.width / 2, -o.depth / 2],
      [o.width / 2, -o.depth / 2],
      [o.width / 2, o.depth / 2],
      [-o.width / 2, o.depth / 2],
    ].map(([x, y]) => ({ x: o.position.x + x * c - y * s, y: o.position.y + x * s + y * c }));
    const label = (o.label ?? o.category).toLowerCase();
    corners.forEach((p, i) => segments.push({ a: p, b: corners[(i + 1) % 4], pad: 0, label }));
  }
  const walls = new Map(map.walls.map((w) => [w.id, w]));
  const gaps: Gap[] = [];
  for (const g of passable) {
    const wall = g.wall_id ? walls.get(g.wall_id) : undefined;
    if (!wall) continue;
    const [a, b] = gapEnds(wall, g);
    gaps.push({ id: g.id, kind: g.kind, a, b, center: g.position });
  }
  return { map, segments, gaps };
}

/** Nearest surface along one bearing, within maxRange. */
export function raycast(scene: Scene, origin: Point2D, bearingDeg: number, maxRange: number) {
  const d = bearingVector(bearingDeg);
  let best: { distance: number; hit: Point2D; what: string } | null = null;
  for (const seg of scene.segments) {
    const sx = seg.b.x - seg.a.x;
    const sy = seg.b.y - seg.a.y;
    const denom = cross(d.x, d.y, sx, sy);
    if (Math.abs(denom) < 1e-12) continue;
    const ox = seg.a.x - origin.x;
    const oy = seg.a.y - origin.y;
    const t = cross(ox, oy, sx, sy) / denom;
    const u = cross(ox, oy, d.x, d.y) / denom;
    if (t < 0 || u < 0 || u > 1) continue;
    const distance = Math.max(0, t - seg.pad);
    if (distance <= maxRange && (!best || distance < best.distance)) {
      best = { distance, hit: { x: origin.x + d.x * t, y: origin.y + d.y * t }, what: seg.label };
    }
  }
  return best;
}

/** The nearest surface in each zone around the walker. */
export function readZones(scene: Scene, pose: Pose, s: SoundscapeSettings = SOUNDSCAPE): Reading[] {
  return s.zones.map((zone) => {
    let best: ReturnType<typeof raycast> = null;
    // Evenly spaced rays from edge to edge, so a zone is never lopsided.
    const span = zone.to_deg - zone.from_deg;
    const n = Math.max(1, Math.ceil(span / s.sensing.ray_step_deg));
    for (let i = 0; i <= n; i++) {
      const r = raycast(scene, pose.position, pose.heading + zone.from_deg + (span * i) / n, s.sensing.max_range_m);
      if (r && (!best || r.distance < best.distance)) best = r;
    }
    return { zone: zone.id, label: zone.label, distance: best?.distance ?? null, hit: best?.hit ?? null, what: best?.what ?? null };
  });
}

/** How muffled one ear's noise is for the nearest surface on that side: 0 = open, 1 = fully muffled. */
export function muffleFor(distance: number | null, s: SoundscapeSettings = SOUNDSCAPE) {
  const m = s.muffle;
  const t = distance === null ? 0 : clamp01((m.open_at_m - distance) / (m.open_at_m - m.muffled_at_m));
  const amount = t === 0 ? 0 : Math.pow(t, m.curve);
  return {
    amount,
    // Cutoff moves on a log scale, which is how pitch is heard.
    cutoffHz: m.open_cutoff_hz * Math.pow(m.muffled_cutoff_hz / m.open_cutoff_hz, amount),
    gain: m.open_gain + (m.muffled_gain - m.open_gain) * amount,
  };
}

/** Ticks per second for something straight ahead, or null for no ticks. */
export function pulseRateFor(distance: number | null, s: SoundscapeSettings = SOUNDSCAPE): number | null {
  const p = s.ahead_pulse;
  if (distance === null || distance > p.start_at_m) return null;
  const t = clamp01((p.start_at_m - distance) / (p.start_at_m - p.fastest_at_m));
  return p.slowest_hz + (p.fastest_hz - p.slowest_hz) * t;
}

function segmentsCross(p1: Point2D, p2: Point2D, q1: Point2D, q2: Point2D): boolean {
  const o = (a: Point2D, b: Point2D, c: Point2D) => (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x);
  return o(q1, q2, p1) * o(q1, q2, p2) < 0 && o(p1, p2, q1) * o(p1, p2, q2) < 0;
}

/** Whether a step from p1 to p2 passes the line q1–q2. Landing exactly on it counts once, not twice. */
function stepCrosses(p1: Point2D, p2: Point2D, q1: Point2D, q2: Point2D): boolean {
  const o = (a: Point2D, b: Point2D, c: Point2D) => (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x);
  const s1 = o(q1, q2, p1);
  const s2 = o(q1, q2, p2);
  return (s1 < 0) !== (s2 < 0) && o(p1, p2, q1) * o(p1, p2, q2) <= 0;
}

function pointSegmentDistance(p: Point2D, a: Point2D, b: Point2D): number {
  const vx = b.x - a.x;
  const vy = b.y - a.y;
  const len2 = vx * vx + vy * vy;
  const t = len2 === 0 ? 0 : clamp01(((p.x - a.x) * vx + (p.y - a.y) * vy) / len2);
  return Math.hypot(p.x - (a.x + vx * t), p.y - (a.y + vy * t));
}

/** Room between the walker's center and the nearest surface, and what that surface is. */
function clearance(scene: Scene, p: Point2D): { distance: number; what: string | null } {
  let best = { distance: Infinity, what: null as string | null };
  for (const seg of scene.segments) {
    const d = pointSegmentDistance(p, seg.a, seg.b) - seg.pad;
    if (d < best.distance) best = { distance: d, what: seg.label };
  }
  return best;
}

export function turn(pose: Pose, deg: number): Pose {
  return { ...pose, heading: normalizeHeading(pose.heading + deg) };
}

export interface MoveResult {
  pose: Pose;
  blocked: boolean;
  blockedBy: string | null;
  crossed: Gap[];
}

/** Step forward (positive) or back (negative) without walking through walls or furniture. */
export function move(scene: Scene, pose: Pose, meters: number, s: SoundscapeSettings = SOUNDSCAPE): MoveResult {
  const d = bearingVector(pose.heading);
  const target = { x: pose.position.x + d.x * meters, y: pose.position.y + d.y * meters };
  const through = scene.segments.find((seg) => segmentsCross(pose.position, target, seg.a, seg.b));
  const now = clearance(scene, pose.position);
  const then = clearance(scene, target);
  // Someone placed hard against a wall can still step away from it.
  const tooClose = then.distance < s.walk.body_radius_m && then.distance < now.distance - 1e-6;
  if (through || tooClose) {
    return { pose, blocked: true, blockedBy: through?.label ?? then.what, crossed: [] };
  }
  const crossed = scene.gaps.filter((g) => stepCrosses(pose.position, target, g.a, g.b));
  return { pose: { ...pose, position: target }, blocked: false, blockedBy: null, crossed };
}

/**
 * Whether the map says anything about this spot. Outside it the soundscape must not sound
 * like open space, so the page plays the "no data" cue instead.
 */
export function hasMapData(scene: Scene, p: Point2D): boolean {
  const { map } = scene;
  if (map.rooms.length > 0) {
    return map.rooms.some((r) => pointInPolygon(p, r.polygon)) || scene.gaps.some((g) => dist(g.center, p) < 0.6);
  }
  const b = planBounds(map);
  return p.x >= b.min_x && p.x <= b.max_x && p.y >= b.min_y && p.y <= b.max_y;
}

const COMPASS = ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"];

export function compassName(heading: number): string {
  return COMPASS[Math.round(normalizeHeading(heading) / 45) % 8];
}

/** "ahead", "on your left", "behind you on the right", ... for an angle relative to the heading. */
export function relativeDirection(offsetDeg: number): string {
  const off = ((offsetDeg + 540) % 360) - 180;
  const side = off < 0 ? "left" : "right";
  const a = Math.abs(off);
  if (a <= 20) return "ahead";
  if (a <= 60) return `ahead on your ${side}`;
  if (a <= 120) return `on your ${side}`;
  if (a <= 160) return `behind you on the ${side}`;
  return "behind you";
}

export function directionTo(pose: Pose, p: Point2D): string {
  const bearing = (Math.atan2(p.x - pose.position.x, p.y - pose.position.y) * 180) / Math.PI;
  return relativeDirection(bearing - pose.heading);
}

export function meters(d: number): string {
  if (d < 0.95) return `${(Math.round(d * 10) / 10).toFixed(1)} meters`;
  const r = Math.round(d * 2) / 2;
  return `${r % 1 === 0 ? r.toFixed(0) : r.toFixed(1)} ${r === 1 ? "meter" : "meters"}`;
}

export function readingPhrase(r: Reading, maxRange = SOUNDSCAPE.sensing.max_range_m): string {
  const where = r.zone === "ahead" ? "ahead" : `on your ${r.zone}`;
  if (r.distance === null) return `Nothing within ${meters(maxRange)} ${where}.`;
  const what = r.what ? r.what[0].toUpperCase() + r.what.slice(1) : "Something";
  return `${what} ${meters(r.distance)} ${where}.`;
}

export function gapName(g: Gap): string {
  return g.kind === "door" ? "door" : "opening";
}

/** Spoken answer to "what's around me?", built only from the map. */
export function describeSurroundings(scene: Scene, pose: Pose, s: SoundscapeSettings = SOUNDSCAPE): string {
  if (!hasMapData(scene, pose.position)) {
    return `You're outside the mapped area, facing ${compassName(pose.heading)}. There's no map information here. Turn around to go back.`;
  }
  const room = roomAt(scene.map, pose.position);
  const parts = [`${room ? `In ${room.name}` : "On the map"}, facing ${compassName(pose.heading)}.`];
  for (const r of readZones(scene, pose, s)) parts.push(readingPhrase(r, s.sensing.max_range_m));
  const doors = scene.gaps
    .map((g) => ({ g, d: dist(g.center, pose.position) }))
    .filter((x) => x.d <= 3)
    .sort((a, b) => a.d - b.d)
    .slice(0, 2);
  for (const { g, d } of doors) parts.push(`A ${gapName(g)} ${meters(d)} ${directionTo(pose, g.center)}.`);
  const places = scene.map.landmarks
    .map((l) => ({ l, d: dist(l.position, pose.position) }))
    .filter((x) => x.d <= 4)
    .sort((a, b) => a.d - b.d)
    .slice(0, 2);
  for (const { l, d } of places) parts.push(`${l.name}, ${meters(d)} ${directionTo(pose, l.position)}.`);
  return parts.join(" ");
}
