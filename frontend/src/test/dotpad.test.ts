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
  mapPins,
  pinAt,
  previewBraille,
  statusLine,
  toCellBytes,
  toHex,
  toPin,
} from "../lib/dotpad";

const demoMap = {
  ...(demo as unknown as FloorMap),
  bounds: { min_x: 0, min_y: 0, max_x: 16, max_y: 10 },
};

describe("DotPad pin grid", () => {
  const { grid, layout, placed } = mapPins(demoMap);

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
    for (let c = nw.col; c <= ne.col; c++) expect(pinAt(grid, c, nw.row)).toBe(PIN.wall);
  });

  it("leaves a finger-wide gap at the main entrance", () => {
    const door = toPin(layout, { x: 3.5, y: 0 });
    expect(pinAt(grid, door.col, door.row)).toBe(PIN.empty);
    const open = [-1, 0, 1].filter((d) => pinAt(grid, door.col + d, door.row) === PIN.empty).length;
    expect(open).toBeGreaterThanOrEqual(DOTPAD.minGapPins);
  });

  it("places a symbol for each marked landmark, clear of walls and each other", () => {
    const types = new Set(demoMap.landmarks.filter((l) => PIN_SYMBOLS[l.type] && l.show_on_tactile !== false).map((l) => l.id));
    expect(types.size).toBeGreaterThanOrEqual(6);
    expect(new Set(placed.map((p) => p.landmarkId))).toEqual(types);
    for (const p of placed) {
      for (let dr = -2; dr <= 2; dr++)
        for (let dc = -2; dc <= 2; dc++) expect(pinAt(grid, p.col + dc, p.row + dr)).not.toBe(PIN.wall);
    }
    for (const a of placed)
      for (const b of placed)
        if (a !== b) expect(Math.max(Math.abs(a.col - b.col), Math.abs(a.row - b.row))).toBeGreaterThanOrEqual(4);
  });

  it("uses a different pattern for every symbol and for the walker", () => {
    const patterns = [...Object.values(PIN_SYMBOLS).map((s) => s!.pattern), WALKER_SYMBOL.pattern].map((p) => JSON.stringify(p));
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
      const { grid: g, walker } = framePins(grid, layout, { position: { x: pos.x + dx, y: pos.y + dy }, heading: 0 }, placed);
      // Either the whole plus is there or none of it: never a broken half-symbol.
      const left = [-1, 0, 1]
        .flatMap((dr) => [-1, 0, 1].map((dc) => pinAt(g, info.col + dc, info.row + dr) === PIN.symbol))
        .filter(Boolean).length;
      const near = Math.max(Math.abs(info.col - walker!.col), Math.abs(info.row - walker!.row)) <= 3;
      expect(left).toBe(near ? 0 : 5);
      for (let dr = -2; dr <= 2; dr++)
        for (let dc = -2; dc <= 2; dc++) expect(pinAt(g, walker!.col + dc, walker!.row + dr)).not.toBe(PIN.symbol);
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

describe("sending to the device", () => {
  it("packs pins into one byte per 2 × 4 braille cell, in braille dot order", () => {
    const g = { cols: 60, rows: 40, pins: new Uint8Array(60 * 40) };
    const bytes = toCellBytes(g);
    expect(bytes.length).toBe(30 * 10);
    g.pins[0] = PIN.wall; // dot 1 of cell 0
    g.pins[1] = PIN.wall; // dot 4 of cell 0
    g.pins[3 * 60] = PIN.wall; // dot 7 of cell 0
    g.pins[3 * 60 + 3] = PIN.wall; // dot 8 of cell 1
    const packed = toCellBytes(g);
    expect(packed[0]).toBe(0b0100_1001);
    expect(packed[1]).toBe(0b1000_0000);
    expect(toHex(packed).slice(0, 4)).toBe("4980");
    expect(toHex(packed)).toHaveLength(600);
  });

  it("fits where-you-are on the 20-cell text line", () => {
    expect(statusLine(demoMap, { position: { x: 3.5, y: 2 }, heading: 0 })).toBe("Lobby N");
    expect(statusLine(demoMap, { position: { x: 8, y: 5 }, heading: 135 })).toBe("Central Hallway SE");
    expect(statusLine(demoMap, { position: { x: 3, y: 8 }, heading: 270 }).length).toBeLessThanOrEqual(20);
    expect(statusLine(demoMap, { position: { x: 30, y: 30 }, heading: 0 })).toBe("off map N");
  });

  it("previews braille text", () => {
    expect(previewBraille("ab 1")).toBe("⠁⠃⠀⠁");
  });
});
