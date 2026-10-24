import { describe, expect, it } from "vitest";
import type { FloorMap } from "../api/types";
import { addPath, crossesWall, pathPoints, removePath } from "../lib/paths";

const p = (x: number, y: number) => ({ x, y });

/** Two 4 x 4 m rooms side by side, joined by a 1 m door in the shared wall at (4, 2). No paths yet. */
function twoRooms(): FloorMap {
  const wall = (id: string, a: [number, number], b: [number, number]) => ({ id, start: p(...a), end: p(...b), thickness: 0.15 });
  return {
    schema_version: "1.0", id: "t", name: "Two rooms", units: "meters",
    source: { kind: "roomplan", description: "" }, floor_level: 0, bounds: { min_x: 0, min_y: 0, max_x: 8, max_y: 4 },
    walls: [
      wall("w_s", [0, 0], [8, 0]), wall("w_e", [8, 0], [8, 4]), wall("w_n", [8, 4], [0, 4]),
      wall("w_w", [0, 4], [0, 0]), wall("w_mid", [4, 0], [4, 4]),
    ],
    doors: [{ id: "d1", kind: "door", position: p(4, 2), width: 1, wall_id: "w_mid" }],
    openings: [], windows: [], objects: [],
    rooms: [
      { id: "r1", name: "Bedroom", polygon: [p(0, 0), p(4, 0), p(4, 4), p(0, 4)], description: "" },
      { id: "r2", name: "Hallway", polygon: [p(4, 0), p(8, 0), p(8, 4), p(4, 4)], description: "" },
    ],
    landmarks: [
      { id: "lm_a", name: "Bed", type: "other", position: p(2, 0.6), description: "", show_on_tactile: true, nav_node_id: null, source: "manual" },
      { id: "lm_b", name: "Front Door", type: "entrance", position: p(6, 0.6), description: "", show_on_tactile: true, nav_node_id: null, source: "manual" },
    ],
    navigation: { nodes: [], edges: [] },
    start_landmark_id: null,
    tactile: {} as FloorMap["tactile"],
    created_at: null, updated_at: null,
  };
}

const point = (map: FloorMap, label: string) => pathPoints(map).find((x) => x.label === label)!;

describe("walkable path editing", () => {
  it("offers landmarks and doorways, naming doors by the rooms they join", () => {
    expect(pathPoints(twoRooms()).map((x) => x.label)).toEqual(["Bed", "Door between Bedroom and Hallway", "Front Door"]);
  });

  it("detects lines through walls but allows lines through a doorway", () => {
    const map = twoRooms();
    expect(crossesWall(map, p(2, 0.6), p(6, 0.6))).toBe(true); // through the solid shared wall
    expect(crossesWall(map, p(2, 2), p(6, 2))).toBe(false); // straight through the door gap
    expect(crossesWall(map, p(2, 0.6), p(4, 2))).toBe(false); // ends at the doorway itself
  });

  it("refuses a path through a wall with an explanation", () => {
    const map = twoRooms();
    const r = addPath(map, point(map, "Bed"), point(map, "Front Door"), false);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toMatch(/passes through a wall.*doorway/);
  });

  it("connects places through the doorway, creating linked nodes", () => {
    let map = twoRooms();
    const first = addPath(map, point(map, "Bed"), point(map, "Door between Bedroom and Hallway"), false);
    expect(first.ok).toBe(true);
    if (!first.ok) return;
    map = first.map;
    const second = addPath(map, point(map, "Door between Bedroom and Hallway"), point(map, "Front Door"), true);
    expect(second.ok).toBe(true);
    if (!second.ok) return;
    map = second.map;

    expect(map.navigation.edges).toHaveLength(2);
    expect(map.navigation.edges[1].accessibility).toBe("has_steps");
    expect(map.navigation.nodes.filter((n) => n.kind === "door")).toHaveLength(1); // the doorway node is reused
    const bed = map.landmarks.find((l) => l.id === "lm_a")!;
    const bedNode = map.navigation.nodes.find((n) => n.id === bed.nav_node_id)!;
    expect(bedNode.landmark_id).toBe("lm_a");
    expect(bedNode.room_id).toBe("r1");
    // The doorway is now a graph node, so it isn't offered twice.
    expect(pathPoints(map).filter((x) => x.label.startsWith("Door between"))).toHaveLength(1);
  });

  it("rejects duplicates and self-loops, and removes paths", () => {
    let map = twoRooms();
    const door = point(map, "Door between Bedroom and Hallway");
    const r = addPath(map, point(map, "Bed"), door, false);
    if (!r.ok) throw new Error(r.error);
    map = r.map;
    const again = addPath(map, point(map, "Bed"), point(map, "Door between Bedroom and Hallway"), false);
    expect(again.ok).toBe(false);
    const self = addPath(map, point(map, "Bed"), point(map, "Bed"), false);
    expect(self.ok).toBe(false);
    expect(removePath(map, r.edge.id).navigation.edges).toHaveLength(0);
  });
});
