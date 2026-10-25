/**
 * The map as a DotPad pin grid: raised walls, gaps at doors, a 3 × 3 pin symbol per landmark,
 * and an X where the walker stands. North is up, like the printed map.
 *
 * Hardware transport lives in device.ts; this file only produces tactile frames.
 */
import { brailleBytes } from "./text";
import type { FloorMap, LandmarkType, Point2D } from "../api/types";
import { gapEnds, planBounds, roomAt, wallPieces } from "../lib/geometry";
import { compassName, type Pose } from "../lib/soundscape";

export const DOTPAD = {
  cols: 60,
  rows: 40,
  cellCols: 2,
  cellRows: 4,
  textCells: 20,
  marginPins: 1,
  minGapPins: 2,
};

export const PIN = { empty: 0, wall: 1, symbol: 2, walker: 3 } as const;
export type PinKind = (typeof PIN)[keyof typeof PIN];

export interface PinGrid {
  cols: number;
  rows: number;
  /** Row-major, one entry per pin: what raised it (0 = flat). */
  pins: Uint8Array;
}

/** Plan meters ↔ pins: same scale on both axes, centered, north up. */
export interface PinLayout {
  scale: number; // pins per meter
  originCol: number;
  originRow: number;
  minX: number;
  maxY: number;
  metersPerPin: number;
}

const s3 = (rows: string[]) => rows.map((r) => [...r].map((c) => c === "X"));

/**
 * 3 × 3 symbols, as close to the printed ones as 9 pins allow. Rooms, hallways and "other"
 * get no symbol: at this size extra marks would only clutter.
 */
export const PIN_SYMBOLS: Partial<
  Record<LandmarkType, { name: string; pattern: boolean[][] }>
> = {
  entrance: { name: "triangle", pattern: s3([".X.", "X.X", "XXX"]) },
  exit: { name: "solid square", pattern: s3(["XXX", "XXX", "XXX"]) },
  restroom: {
    name: "diamond (the printed circle)",
    pattern: s3([".X.", "X.X", ".X."]),
  },
  stairs: { name: "two bars", pattern: s3(["XXX", "...", "XXX"]) },
  elevator: {
    name: "hollow square (the printed ring)",
    pattern: s3(["XXX", "X.X", "XXX"]),
  },
  information: { name: "plus", pattern: s3([".X.", "XXX", ".X."]) },
};

/** "X marks the spot": no landmark symbol uses it. */
export const WALKER_SYMBOL = { name: "X", pattern: s3(["X.X", ".X.", "X.X"]) };

export function layoutFor(
  map: FloorMap,
  cols = DOTPAD.cols,
  rows = DOTPAD.rows,
): PinLayout {
  const b = planBounds(map);
  const w = Math.max(b.max_x - b.min_x, 1e-6);
  const h = Math.max(b.max_y - b.min_y, 1e-6);
  const usableC = cols - 1 - 2 * DOTPAD.marginPins;
  const usableR = rows - 1 - 2 * DOTPAD.marginPins;
  const scale = Math.min(usableC / w, usableR / h);
  return {
    scale,
    originCol: DOTPAD.marginPins + (usableC - w * scale) / 2,
    originRow: DOTPAD.marginPins + (usableR - h * scale) / 2,
    minX: b.min_x,
    maxY: b.max_y,
    metersPerPin: 1 / scale,
  };
}

export function toPin(
  layout: PinLayout,
  p: Point2D,
): { col: number; row: number } {
  return {
    col: Math.round(layout.originCol + (p.x - layout.minX) * layout.scale),
    row: Math.round(layout.originRow + (layout.maxY - p.y) * layout.scale),
  };
}

function emptyGrid(cols: number, rows: number): PinGrid {
  return { cols, rows, pins: new Uint8Array(cols * rows) };
}

function setPin(g: PinGrid, col: number, row: number, kind: PinKind) {
  if (col >= 0 && row >= 0 && col < g.cols && row < g.rows)
    g.pins[row * g.cols + col] = kind;
}

export function pinAt(g: PinGrid, col: number, row: number): PinKind {
  if (col < 0 || row < 0 || col >= g.cols || row >= g.rows) return PIN.empty;
  return g.pins[row * g.cols + col] as PinKind;
}

/** Pins along a segment, in pin coordinates (fractional), sampled finely enough to stay connected. */
function linePins(
  a: { col: number; row: number },
  b: { col: number; row: number },
): [number, number][] {
  const n = Math.max(
    1,
    Math.ceil(Math.hypot(b.col - a.col, b.row - a.row) * 4),
  );
  const out = new Map<string, [number, number]>();
  for (let i = 0; i <= n; i++) {
    const c = Math.round(a.col + ((b.col - a.col) * i) / n);
    const r = Math.round(a.row + ((b.row - a.row) * i) / n);
    out.set(`${c},${r}`, [c, r]);
  }
  return [...out.values()];
}

function exact(layout: PinLayout, p: Point2D) {
  return {
    col: layout.originCol + (p.x - layout.minX) * layout.scale,
    row: layout.originRow + (layout.maxY - p.y) * layout.scale,
  };
}

function stamp(
  g: PinGrid,
  pattern: boolean[][],
  col: number,
  row: number,
  kind: PinKind,
) {
  pattern.forEach((line, dr) =>
    line.forEach((on, dc) => on && setPin(g, col - 1 + dc, row - 1 + dr, kind)),
  );
}

/** Pins that stay the same while walking: walls with door gaps, and landmark symbols. */
export function mapPins(
  map: FloorMap,
  cols = DOTPAD.cols,
  rows = DOTPAD.rows,
): { grid: PinGrid; layout: PinLayout; placed: PlacedSymbol[] } {
  const layout = layoutFor(map, cols, rows);
  const grid = emptyGrid(cols, rows);
  const gaps = [...map.doors, ...map.openings];

  for (const wall of map.walls) {
    const own = gaps.filter((g) => g.wall_id === wall.id);
    for (const [a, b] of wallPieces(wall, own)) {
      for (const [c, r] of linePins(exact(layout, a), exact(layout, b)))
        setPin(grid, c, r, PIN.wall);
    }
  }

  // Rounding can fill a narrow doorway; reopen every gap to at least minGapPins so a finger finds it.
  const walls = new Map(map.walls.map((w) => [w.id, w]));
  for (const g of gaps) {
    const wall = g.wall_id ? walls.get(g.wall_id) : undefined;
    if (!wall) continue;
    const [p, q] = gapEnds(wall, g);
    const a = exact(layout, p);
    const b = exact(layout, q);
    const len = Math.hypot(b.col - a.col, b.row - a.row);
    const need = DOTPAD.minGapPins + 0.6;
    const grow = len < need ? (need - len) / 2 / Math.max(len, 1e-6) : 0;
    const a2 = {
      col: a.col - (b.col - a.col) * grow,
      row: a.row - (b.row - a.row) * grow,
    };
    const b2 = {
      col: b.col + (b.col - a.col) * grow,
      row: b.row + (b.row - a.row) * grow,
    };
    for (const [c, r] of linePins(a2, b2))
      if (pinAt(grid, c, r) === PIN.wall) setPin(grid, c, r, PIN.empty);
  }

  const placed: PlacedSymbol[] = [];
  for (const lm of map.landmarks) {
    const sym = PIN_SYMBOLS[lm.type];
    if (!sym || lm.show_on_tactile === false) continue;
    const at = placeSymbol(grid, toPin(layout, lm.position), placed);
    stamp(grid, sym.pattern, at.col, at.row, PIN.symbol);
    placed.push({ landmarkId: lm.id, name: lm.name, symbol: sym.name, ...at });
  }
  return { grid, layout, placed };
}

export interface PlacedSymbol {
  landmarkId: string;
  name: string;
  symbol: string;
  col: number;
  row: number;
}

/**
 * Nearest spot to the landmark where its 3 × 3 symbol, plus a one-pin border, touches no wall
 * and no other symbol, so symbols never merge with walls or each other.
 */
function placeSymbol(
  grid: PinGrid,
  want: { col: number; row: number },
  placed: PlacedSymbol[],
) {
  const clear = (c: number, r: number) => {
    if (c < 1 || r < 1 || c > grid.cols - 2 || r > grid.rows - 2) return false;
    for (let dr = -2; dr <= 2; dr++)
      for (let dc = -2; dc <= 2; dc++)
        if (pinAt(grid, c + dc, r + dr) !== PIN.empty) return false;
    return placed.every(
      (p) => Math.max(Math.abs(p.col - c), Math.abs(p.row - r)) >= 4,
    );
  };
  for (let radius = 0; radius <= 4; radius++) {
    let best: { col: number; row: number; d: number } | null = null;
    for (let dr = -radius; dr <= radius; dr++) {
      for (let dc = -radius; dc <= radius; dc++) {
        if (Math.max(Math.abs(dr), Math.abs(dc)) !== radius) continue;
        const c = want.col + dc;
        const r = want.row + dr;
        const d = dc * dc + dr * dr;
        if (clear(c, r) && (!best || d < best.d)) best = { col: c, row: r, d };
      }
    }
    if (best) return { col: best.col, row: best.row };
  }
  return want;
}

/** The full frame: the map plus an X at the walker's position (drawn on top). */
export function framePins(
  base: PinGrid,
  layout: PinLayout,
  pose: Pose | null,
  placed: PlacedSymbol[] = [],
): { grid: PinGrid; walker: { col: number; row: number } | null } {
  const grid = { ...base, pins: base.pins.slice() };
  if (!pose) return { grid, walker: null };
  const at = toPin(layout, pose.position);
  const col = Math.min(grid.cols - 2, Math.max(1, at.col));
  const row = Math.min(grid.rows - 2, Math.max(1, at.row));
  // A symbol touching the X would merge into one shape under a finger; while you're on top of
  // a place, its symbol drops and the text line and voice say where you are.
  // Whole symbols only, never half of one: two 3 × 3 shapes need centers 4 pins apart to keep
  // a flat pin between them.
  for (const p of placed) {
    if (Math.max(Math.abs(p.col - col), Math.abs(p.row - row)) > 3) continue;
    for (let dr = -1; dr <= 1; dr++) {
      for (let dc = -1; dc <= 1; dc++)
        if (pinAt(grid, p.col + dc, p.row + dr) === PIN.symbol)
          setPin(grid, p.col + dc, p.row + dr, PIN.empty);
    }
  }
  stamp(grid, WALKER_SYMBOL.pattern, col, row, PIN.walker);
  return { grid, walker: { col, row } };
}

/**
 * One byte per 2 × 4 braille cell, cells row by row. Bits follow standard 8-dot braille
 * numbering: dots 1–3 down the left column, 4–6 down the right, 7 and 8 on the bottom row.
 * Check this against the Dot Pad SDK before trusting it.
 */
export function toCellBytes(g: PinGrid): Uint8Array {
  const cc = Math.ceil(g.cols / DOTPAD.cellCols);
  const cr = Math.ceil(g.rows / DOTPAD.cellRows);
  const bytes = new Uint8Array(cc * cr);
  // [column within cell, row within cell] for dots 1..8
  const dots: [number, number][] = [
    [0, 0],
    [0, 1],
    [0, 2],
    [1, 0],
    [1, 1],
    [1, 2],
    [0, 3],
    [1, 3],
  ];
  for (let r = 0; r < cr; r++) {
    for (let c = 0; c < cc; c++) {
      let byte = 0;
      dots.forEach(([dc, dr], bit) => {
        if (pinAt(g, c * 2 + dc, r * 4 + dr) !== PIN.empty) byte |= 1 << bit;
      });
      bytes[r * cc + c] = byte;
    }
  }
  return bytes;
}

export function toHex(bytes: Uint8Array): string {
  return [...bytes]
    .map((b) => b.toString(16).padStart(2, "0").toUpperCase())
    .join("");
}

/** Short text for the 20-cell braille line: where you are and which way you face. */
export function statusLine(
  map: FloorMap,
  pose: Pose | null,
  cells = DOTPAD.textCells,
): string {
  if (!pose) return "";
  const room = roomAt(map, pose.position)?.name ?? "off map";
  const dir = compassName(pose.heading)
    .replace("north", "N")
    .replace("south", "S")
    .replace("east", "E")
    .replace("west", "W");
  const roomText = room.replace(/\s*\(unconfirmed\)/i, "");
  const tail = ` ${dir}`;
  return (
    (roomText.length + tail.length > cells
      ? roomText.slice(0, cells - tail.length)
      : roomText) + tail
  );
}

/** Unicode preview of the same uncontracted English cells sent to the device. */
export function previewBraille(text: string): string {
  return brailleBytes(text)
    .map((cell) => String.fromCodePoint(0x2800 + cell))
    .join("");
}

/** Counts for a short text description of a frame. */
export function describeGrid(g: PinGrid): {
  raised: number;
  walls: number;
  symbols: number;
} {
  let walls = 0;
  let symbols = 0;
  let raised = 0;
  for (const p of g.pins) {
    if (p !== PIN.empty) raised++;
    if (p === PIN.wall) walls++;
    if (p === PIN.symbol) symbols++;
  }
  return { raised, walls, symbols };
}
