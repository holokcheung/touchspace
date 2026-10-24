import { describe, expect, it } from "vitest";
import demo from "../../../sample-data/demo-building.json";
import type { FloorMap } from "../api/types";
import {
  SOUNDSCAPE,
  buildScene,
  compassName,
  describeSurroundings,
  hasMapData,
  move,
  muffleFor,
  pulseRateFor,
  raycast,
  readZones,
  relativeDirection,
  turn,
} from "../lib/soundscape";

const demoMap = demo as unknown as FloorMap;

/** Two 4 × 4 m rooms side by side, joined by a 1 m door in the shared wall at x = 4. */
function twoRooms(): FloorMap {
  const w = (id: string, ax: number, ay: number, bx: number, by: number) => ({
    id,
    start: { x: ax, y: ay },
    end: { x: bx, y: by },
    thickness: 0.1,
  });
  return {
    ...demoMap,
    id: "two-rooms",
    bounds: { min_x: 0, min_y: 0, max_x: 8, max_y: 4 },
    walls: [w("s", 0, 0, 8, 0), w("n", 0, 4, 8, 4), w("w", 0, 0, 0, 4), w("e", 8, 0, 8, 4), w("mid", 4, 0, 4, 4)],
    doors: [{ id: "d1", kind: "door", position: { x: 4, y: 2 }, width: 1, wall_id: "mid" }],
    openings: [],
    windows: [],
    objects: [],
    rooms: [
      { id: "a", name: "Room A", description: "", polygon: [{ x: 0, y: 0 }, { x: 4, y: 0 }, { x: 4, y: 4 }, { x: 0, y: 4 }] },
      { id: "b", name: "Room B", description: "", polygon: [{ x: 4, y: 0 }, { x: 8, y: 0 }, { x: 8, y: 4 }, { x: 4, y: 4 }] },
    ],
    landmarks: [],
  };
}

describe("shared soundscape settings", () => {
  it("are internally consistent", () => {
    const s = SOUNDSCAPE;
    expect(s.version).toBe(1);
    expect(s.zones.map((z) => z.id)).toEqual(["left", "ahead", "right"]);
    for (const z of s.zones) expect(z.from_deg).toBeLessThan(z.to_deg);
    expect(s.muffle.muffled_at_m).toBeLessThan(s.muffle.open_at_m);
    expect(s.muffle.muffled_cutoff_hz).toBeLessThan(s.muffle.open_cutoff_hz);
    expect(s.ahead_pulse.fastest_at_m).toBeLessThan(s.ahead_pulse.start_at_m);
    expect(s.cues.no_data.repeat_s).toBeGreaterThan(0);
  });
});

describe("sensing the map", () => {
  const scene = buildScene(twoRooms());

  it("measures to the wall surface, not its centerline", () => {
    const r = raycast(scene, { x: 1, y: 2 }, 270, 5); // due west, wall at x = 0
    expect(r?.distance).toBeCloseTo(0.95, 5);
    expect(r?.what).toBe("wall");
  });

  it("sees through a doorway", () => {
    const r = raycast(scene, { x: 2, y: 2 }, 90, 10); // due east through the door
    expect(r?.distance).toBeCloseTo(8 - 2 - 0.05, 5);
  });

  it("puts a wall on the right in the right zone only", () => {
    // Facing north at x = 3.4: the shared wall is 0.55 m to the right; everything on the left is far.
    const readings = Object.fromEntries(readZones(scene, { position: { x: 3.4, y: 1 }, heading: 0 }).map((r) => [r.zone, r]));
    expect(readings.right.distance).toBeCloseTo(0.55, 2);
    expect(readings.left.distance).toBeGreaterThan(SOUNDSCAPE.muffle.open_at_m);
    expect(muffleFor(readings.right.distance).amount).toBeGreaterThan(0.8);
    expect(muffleFor(readings.left.distance).amount).toBe(0);
  });

  it("reports nothing in range as null", () => {
    const readings = readZones(scene, { position: { x: 2, y: 2 }, heading: 90 }, { ...SOUNDSCAPE, sensing: { max_range_m: 1, ray_step_deg: 5 } });
    expect(readings.find((r) => r.zone === "ahead")?.distance).toBeNull();
  });

  it("knows where the map has information", () => {
    expect(hasMapData(scene, { x: 2, y: 2 })).toBe(true);
    expect(hasMapData(scene, { x: 9, y: 2 })).toBe(false);
  });
});

describe("turning distance into sound", () => {
  it("muffles more as a surface gets closer", () => {
    const far = muffleFor(3);
    const mid = muffleFor(1.2);
    const near = muffleFor(0.2);
    expect(far).toMatchObject({ amount: 0, cutoffHz: SOUNDSCAPE.muffle.open_cutoff_hz, gain: SOUNDSCAPE.muffle.open_gain });
    expect(mid.amount).toBeGreaterThan(0);
    expect(mid.amount).toBeLessThan(1);
    expect(near.amount).toBe(1);
    expect(near.cutoffHz).toBeCloseTo(SOUNDSCAPE.muffle.muffled_cutoff_hz, 5);
    expect(mid.cutoffHz).toBeLessThan(far.cutoffHz);
    expect(mid.cutoffHz).toBeGreaterThan(near.cutoffHz);
    expect(muffleFor(null).amount).toBe(0);
  });

  it("ticks faster as something ahead gets closer", () => {
    expect(pulseRateFor(null)).toBeNull();
    expect(pulseRateFor(3)).toBeNull();
    const slow = pulseRateFor(1.9)!;
    const fast = pulseRateFor(0.5)!;
    expect(fast).toBeGreaterThan(slow);
    expect(pulseRateFor(0.1)).toBe(SOUNDSCAPE.ahead_pulse.fastest_hz);
  });
});

describe("walking", () => {
  const scene = buildScene(twoRooms());

  it("stops at walls", () => {
    let pose = { position: { x: 1, y: 2 }, heading: 270 };
    let result = move(scene, pose, 0.25);
    while (!result.blocked) {
      pose = result.pose;
      result = move(scene, pose, 0.25);
    }
    expect(result.blockedBy).toBe("wall");
    expect(pose.position.x).toBeGreaterThanOrEqual(0.05 + SOUNDSCAPE.walk.body_radius_m - 1e-9);
  });

  it("walks through a doorway and reports it", () => {
    let pose = { position: { x: 3, y: 2 }, heading: 90 };
    const crossed: string[] = [];
    for (let i = 0; i < 8; i++) {
      const r = move(scene, pose, 0.25);
      expect(r.blocked).toBe(false);
      crossed.push(...r.crossed.map((g) => g.id));
      pose = r.pose;
    }
    expect(crossed).toEqual(["d1"]);
    expect(pose.position.x).toBeCloseTo(5, 5);
  });

  it("can't squeeze through a wall beside the door", () => {
    const r = move(scene, { position: { x: 3.8, y: 0.8 }, heading: 90 }, 0.5);
    expect(r.blocked).toBe(true);
  });

  it("lets someone step away from a wall they start against", () => {
    const r = move(scene, { position: { x: 0.1, y: 2 }, heading: 90 }, 0.25);
    expect(r.blocked).toBe(false);
  });

  it("turns and names directions", () => {
    expect(turn({ position: { x: 0, y: 0 }, heading: 350 }, 15).heading).toBe(5);
    expect(compassName(0)).toBe("north");
    expect(compassName(100)).toBe("east");
    expect(compassName(225)).toBe("southwest");
    expect(relativeDirection(0)).toBe("ahead");
    expect(relativeDirection(-90)).toBe("on your left");
    expect(relativeDirection(45)).toBe("ahead on your right");
    expect(relativeDirection(180)).toBe("behind you");
  });
});

describe("describing the surroundings", () => {
  it("speaks from the map, including doors", () => {
    const text = describeSurroundings(buildScene(twoRooms()), { position: { x: 3.45, y: 1 }, heading: 0 });
    expect(text).toContain("In Room A, facing north.");
    expect(text).toContain("Wall 0.5 meters on your right.");
    expect(text).toContain("A door 1 meter ahead on your right.");
  });

  it("says plainly when there's no map information", () => {
    const text = describeSurroundings(buildScene(twoRooms()), { position: { x: 9, y: 2 }, heading: 90 });
    expect(text).toContain("outside the mapped area");
  });

  it("works on the demo building", () => {
    const scene = buildScene(demoMap);
    const start = demoMap.landmarks.find((l) => l.id === demoMap.start_landmark_id)!;
    expect(hasMapData(scene, start.position)).toBe(true);
    expect(describeSurroundings(scene, { position: start.position, heading: 0 })).toMatch(/facing north/);
  });
});
