import { describe, expect, it } from "vitest";
import demo from "../../../sample-data/demo-building.json";
import apartment from "../../standalone/maps/apartment.json";
import type { FloorMap } from "../api/types";
import {
  DOTPAD,
  PIN,
  PIN_SYMBOLS,
  WALKER_SYMBOL,
  framePins,
  describeGrid,
  mapPins,
  pinAt,
  previewBraille,
  statusLine,
  toCellBytes,
  toHex,
  toPin,
} from "../dotpad";

const demoMap = {
  ...(demo as unknown as FloorMap),
  bounds: { min_x: 0, min_y: 0, max_x: 16, max_y: 10 },
};

describe("DotPad pin grid", () => {
  const { grid, layout, placed } = mapPins(demoMap);

  it("keeps the X centered while zooming and moving, including beyond map edges", () => {
    for (const zoom of [2, 4]) {
      for (const position of [{ x: 3.5, y: 2 }, { x: 8, y: 5 }, { x: 30, y: 30 }]) {
        const view = mapPins(demoMap, 60, 40, { zoom, center: position });
        const frame = framePins(view.grid, view.layout, { position, heading: 90 }, view.placed);
        expect(frame.walker).toEqual({ col: 30, row: 20 });
        expect(view.layout.metersPerPin).toBeCloseTo(layout.metersPerPin / zoom);
        expect([...frame.grid.pins].filter((pin) => pin === PIN.walker)).toHaveLength(5);
      }
    }
    // Overview restores the original map framing regardless of user location.
    expect(mapPins(demoMap, 60, 40, { zoom: 1, center: { x: 30, y: 30 } }).grid)
      .toEqual(grid);
  });

  it("pans the map with the user without changing north-up orientation", () => {
    const a = mapPins(demoMap, 60, 40, { zoom: 2, center: { x: 7, y: 5 } });
    const b = mapPins(demoMap, 60, 40, { zoom: 2, center: { x: 8, y: 6 } });
    const fixed = { x: 8, y: 5 };
    expect(toPin(b.layout, fixed).col).toBeLessThan(toPin(a.layout, fixed).col);
    expect(toPin(b.layout, fixed).row).toBeGreaterThan(toPin(a.layout, fixed).row);
    expect(b.grid.pins).not.toEqual(a.grid.pins);
    expect(b.placed.every((p) => p.col >= 1 && p.col <= 58 && p.row >= 1 && p.row <= 38)).toBe(true);
  });

  it("clips crossing walls, preserves door gaps and hides offscreen landmarks", () => {
    const map: FloorMap = {
      ...demoMap,
      walls: [{ ...demoMap.walls[0], id: "wall", start: { x: -1000, y: 5 }, end: { x: 1000, y: 5 } }],
      doors: [], openings: [], landmarks: [],
    };
    const view = mapPins(map, 60, 40, { zoom: 4, center: { x: 8, y: 5 } });
    for (let c = 0; c < 60; c++) expect(pinAt(view.grid, c, 20)).toBe(PIN.wall);
    const doorway = mapPins(demoMap, 60, 40, { zoom: 4, center: { x: 3.5, y: 0 } });
    expect(pinAt(doorway.grid, 30, 20)).toBe(PIN.empty);
    expect(doorway.placed.length).toBeLessThan(placed.length);
    const outside = mapPins(demoMap, 60, 40, { zoom: 4, center: { x: 1000, y: 1000 } });
    expect(outside.placed).toEqual([]);
    expect(outside.grid.pins.every((pin) => pin === PIN.empty)).toBe(true);
  });

  it("fills the 60 × 40 graphic area, north up, with a margin", () => {
    expect(grid.cols).toBe(60);
    expect(grid.rows).toBe(40);
    const nw = toPin(layout, { x: 0, y: 10 });
    const se = toPin(layout, { x: 16, y: 0 });
    expect(nw.col).toBeGreaterThanOrEqual(DOTPAD.marginPins);
    expect(nw.row).toBeGreaterThanOrEqual(DOTPAD.marginPins);
    expect(se.col).toBeLessThanOrEqual(60 - 1 - DOTPAD.marginPins);
    expect(se.row).toBeLessThanOrEqual(40 - 1 - DOTPAD.marginPins);
    expect(se.row).toBeGreaterThan(nw.row); // south is lower on the pad
  });

  it("raises the outside walls", () => {
    const nw = toPin(layout, { x: 0, y: 10 });
    const ne = toPin(layout, { x: 16, y: 10 });
    for (let c = nw.col; c <= ne.col; c++)
      expect(pinAt(grid, c, nw.row)).toBe(PIN.wall);
  });

  it("leaves a finger-wide gap at the main entrance", () => {
    const door = toPin(layout, { x: 3.5, y: 0 });
    expect(pinAt(grid, door.col, door.row)).toBe(PIN.empty);
    const open = [-1, 0, 1].filter(
      (d) => pinAt(grid, door.col + d, door.row) === PIN.empty,
    ).length;
    expect(open).toBeGreaterThanOrEqual(DOTPAD.minGapPins);
  });

  it("places a symbol for each marked landmark, clear of walls and each other", () => {
    const types = new Set(
      demoMap.landmarks
        .filter((l) => PIN_SYMBOLS[l.type] && l.show_on_tactile !== false)
        .map((l) => l.id),
    );
    expect(types.size).toBeGreaterThanOrEqual(6);
    expect(new Set(placed.map((p) => p.landmarkId))).toEqual(types);
    for (const p of placed) {
      for (let dr = -2; dr <= 2; dr++)
        for (let dc = -2; dc <= 2; dc++)
          expect(pinAt(grid, p.col + dc, p.row + dr)).not.toBe(PIN.wall);
    }
    for (const a of placed)
      for (const b of placed)
        if (a !== b)
          expect(
            Math.max(Math.abs(a.col - b.col), Math.abs(a.row - b.row)),
          ).toBeGreaterThanOrEqual(4);
  });

  it("uses a different pattern for every symbol and for the walker", () => {
    const patterns = [
      ...Object.values(PIN_SYMBOLS).map((s) => s!.pattern),
      WALKER_SYMBOL.pattern,
    ].map((p) => JSON.stringify(p));
    expect(new Set(patterns).size).toBe(patterns.length);
  });

  it("draws the walker as an X that moves with them", () => {
    const a = framePins(grid, layout, {
      position: { x: 3.5, y: 2 },
      heading: 0,
    });
    const b = framePins(grid, layout, { position: { x: 8, y: 5 }, heading: 0 });
    expect(a.walker).not.toEqual(b.walker);
    const w = b.walker!;
    expect(pinAt(b.grid, w.col, w.row)).toBe(PIN.walker);
    expect(pinAt(b.grid, w.col - 1, w.row - 1)).toBe(PIN.walker);
    expect(pinAt(b.grid, w.col, w.row - 1)).not.toBe(PIN.walker);
    // The base grid is untouched.
    expect(pinAt(grid, w.col, w.row)).not.toBe(PIN.walker);
  });

  it("drops a whole symbol the X would touch, so the two never merge", () => {
    const info = placed.find((p) => p.name === "Information Desk")!;
    const pos = {
      x: layout.minX + (info.col - layout.originCol) / layout.scale,
      y: layout.maxY - (info.row - layout.originRow) / layout.scale,
    };
    for (const [dx, dy] of [
      [0, 0],
      [0.5, 0],
      [0, -0.75],
      [-0.8, 0.3],
      [2, 0],
    ]) {
      const { grid: g, walker } = framePins(
        grid,
        layout,
        { position: { x: pos.x + dx, y: pos.y + dy }, heading: 0 },
        placed,
      );
      // Either the whole plus is there or none of it: never a broken half-symbol.
      const left = [-1, 0, 1]
        .flatMap((dr) =>
          [-1, 0, 1].map(
            (dc) => pinAt(g, info.col + dc, info.row + dr) === PIN.symbol,
          ),
        )
        .filter(Boolean).length;
      const near =
        Math.max(
          Math.abs(info.col - walker!.col),
          Math.abs(info.row - walker!.row),
        ) <= 3;
      expect(left).toBe(near ? 0 : 5);
      for (let dr = -2; dr <= 2; dr++)
        for (let dc = -2; dc <= 2; dc++)
          expect(pinAt(g, walker!.col + dc, walker!.row + dr)).not.toBe(
            PIN.symbol,
          );
    }
  });

  it("works on the real apartment scan", () => {
    const real = mapPins(apartment as unknown as FloorMap);
    let walls = 0;
    for (const p of real.grid.pins) if (p === PIN.wall) walls++;
    expect(walls).toBeGreaterThan(60);
    expect(real.placed.length).toBe(0); // its landmarks are rooms, which get no symbol
  });
});

describe("DotPad routes", () => {
  it("draws spaced route pins, preserves map geometry, and removes them when dismissed", () => {
    const base = mapPins(demoMap);
    const route = [{ x: 3.5, y: 2 }, { x: 3.5, y: 5 }, { x: 8, y: 5 }, { x: 8, y: 8 }];
    const frame = framePins(base.grid, base.layout, null, base.placed, route);
    expect(describeGrid(frame.grid).route).toBeGreaterThan(5);
    expect(describeGrid(base.grid).route).toBe(0);
    base.grid.pins.forEach((kind, index) => {
      if (kind !== PIN.empty) expect(frame.grid.pins[index]).toBe(kind);
    });
    frame.grid.pins.forEach((kind, index) => {
      if (kind !== PIN.route) return;
      for (let dr = -1; dr <= 1; dr++) {
        for (let dc = -1; dc <= 1; dc++) {
          const neighbor = pinAt(frame.grid, index % 60 + dc, Math.floor(index / 60) + dr);
          expect(neighbor).not.toBe(PIN.wall);
          expect(neighbor).not.toBe(PIN.symbol);
        }
      }
    });
    expect(toCellBytes(frame.grid)).not.toEqual(toCellBytes(base.grid));
    expect(framePins(base.grid, base.layout, null, base.placed).grid).toEqual(base.grid);
  });

  it("clips zoomed routes and leaves space around the centered X", () => {
    const position = { x: 8, y: 5 };
    const base = mapPins(demoMap, 60, 40, { zoom: 4, center: position });
    const frame = framePins(base.grid, base.layout, { position, heading: 0 }, base.placed,
      [{ x: -1000, y: 5 }, { x: 1000, y: 5 }]);
    expect(describeGrid(frame.grid).route).toBeGreaterThan(0);
    expect(frame.walker).toEqual({ col: 30, row: 20 });
    expect([...frame.grid.pins].filter((pin) => pin === PIN.walker)).toHaveLength(5);
    for (let dr = -2; dr <= 2; dr++)
      for (let dc = -2; dc <= 2; dc++)
        expect(pinAt(frame.grid, 30 + dc, 20 + dr)).not.toBe(PIN.route);
    const offscreen = framePins(base.grid, base.layout, null, [],
      [{ x: 1000, y: 1000 }, { x: 2000, y: 1000 }]);
    expect(offscreen.grid).toEqual(base.grid);
    expect(framePins(base.grid, base.layout, null, [], [position, position]).grid).toEqual(base.grid);
  });
});

describe("sending to the device", () => {
  it("packs pins into one byte per 2 × 4 graphic cell, in SDK column order", () => {
    const g = { cols: 60, rows: 40, pins: new Uint8Array(60 * 40) };
    const bytes = toCellBytes(g);
    expect(bytes.length).toBe(30 * 10);
    g.pins[0] = PIN.wall; // dot 1 of cell 0
    g.pins[1] = PIN.wall; // dot 4 of cell 0
    g.pins[3 * 60] = PIN.wall; // dot 7 of cell 0
    g.pins[3 * 60 + 3] = PIN.wall; // dot 8 of cell 1
    const packed = toCellBytes(g);
    expect(packed[0]).toBe(0b0001_1001);
    expect(packed[1]).toBe(0b1000_0000);
    expect(toHex(packed).slice(0, 4)).toBe("1980");
    expect(toHex(packed)).toHaveLength(600);
  });

  it("matches the vendor's braille-to-graphic conversion for every individual dot", () => {
    // SDK 3.0.4 brailleToGraphic maps dots 1,2,3,7 to bits 0–3 and 4,5,6,8 to bits 4–7.
    const expected = [[0x01, 0x10], [0x02, 0x20], [0x04, 0x40], [0x08, 0x80]];
    for (let row = 0; row < 4; row++) {
      for (let col = 0; col < 2; col++) {
        const g = { cols: 60, rows: 40, pins: new Uint8Array(2400) };
        g.pins[row * 60 + col] = PIN.wall;
        expect(toCellBytes(g)[0]).toBe(expected[row][col]);
      }
    }
  });

  it("fits where-you-are on the 20-cell text line", () => {
    expect(
      statusLine(demoMap, { position: { x: 3.5, y: 2 }, heading: 0 }),
    ).toBe("Lobby N");
    expect(
      statusLine(demoMap, { position: { x: 8, y: 5 }, heading: 135 }),
    ).toBe("Central Hallway SE");
    expect(
      statusLine(demoMap, { position: { x: 3, y: 8 }, heading: 270 }).length,
    ).toBeLessThanOrEqual(20);
    expect(
      statusLine(demoMap, { position: { x: 30, y: 30 }, heading: 0 }),
    ).toBe("off map N");
  });

  it("previews braille text", () => {
    expect(previewBraille("ab 1")).toBe("⠁⠃⠀⠼⠁");
  });
});
