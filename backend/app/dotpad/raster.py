"""FloorMap -> Dot Pad pin grid.

Python port of frontend/src/lib/dotpad.ts (mapPins, framePins, toCellBytes), extended with
the zoom viewport and heading indicator that docs/DOTPAD_API.md asks the proxy to own.
At zoom 1 with no pose the output matches the TypeScript version pin for pin.

Coordinates: plan meters, +x right, +y up. Pins: col right, row down, (0, 0) top-left.
Grid size is a parameter. The proxy must pass the size the SDK reports (BoardInfo);
60 x 40 is only the default for previews and tests.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.models.map import FloorMap, LandmarkType, Point2D, Wall, WallGap

DEFAULT_COLS = 60
DEFAULT_ROWS = 40
CELL_COLS = 2
CELL_ROWS = 4
MARGIN_PINS = 1
MIN_GAP_PINS = 2
ZOOMS = (1, 2, 4, 8)

EMPTY, WALL, SYMBOL, WALKER = 0, 1, 2, 3


def _s3(rows: list[str]) -> list[list[bool]]:
    return [[c == "X" for c in r] for r in rows]


PIN_SYMBOLS: dict[LandmarkType, tuple[str, list[list[bool]]]] = {
    LandmarkType("entrance"): ("triangle", _s3([".X.", "X.X", "XXX"])),
    LandmarkType("exit"): ("solid square", _s3(["XXX", "XXX", "XXX"])),
    LandmarkType("restroom"): ("diamond", _s3([".X.", "X.X", ".X."])),
    LandmarkType("stairs"): ("two bars", _s3(["XXX", "...", "XXX"])),
    LandmarkType("elevator"): ("hollow square", _s3(["XXX", "X.X", "XXX"])),
    LandmarkType("information"): ("plus", _s3([".X.", "XXX", ".X."])),
}
WALKER_PATTERN = _s3(["X.X", ".X.", "X.X"])
HEADING_TAIL = (2, 3)  # pins from the walker center along the heading


def js_round(v: float) -> int:
    """Math.round from JavaScript (halves go up). Python's round() would differ at .5."""
    return math.floor(v + 0.5)


@dataclass
class PinGrid:
    cols: int
    rows: int
    pins: bytearray  # row-major, one PIN kind per pin

    @classmethod
    def empty(cls, cols: int, rows: int) -> PinGrid:
        return cls(cols, rows, bytearray(cols * rows))

    def at(self, col: int, row: int) -> int:
        if col < 0 or row < 0 or col >= self.cols or row >= self.rows:
            return EMPTY
        return self.pins[row * self.cols + col]

    def set(self, col: int, row: int, kind: int) -> None:
        if 0 <= col < self.cols and 0 <= row < self.rows:
            self.pins[row * self.cols + col] = kind

    def copy(self) -> PinGrid:
        return PinGrid(self.cols, self.rows, bytearray(self.pins))


@dataclass
class Layout:
    """Plan meters -> pins: pin = origin + (meters - plan corner) * scale."""

    scale: float  # pins per meter
    origin_col: float
    origin_row: float
    min_x: float  # plan x at origin_col
    max_y: float  # plan y at origin_row


@dataclass
class Placed:
    landmark_id: str
    name: str
    symbol: str
    col: int
    row: int


@dataclass
class Pose:
    x: float
    y: float
    heading_rad: float  # clockwise from map-up


# ---------- geometry (port of frontend/src/lib/geometry.ts) ----------


def plan_bounds(m: FloorMap) -> tuple[float, float, float, float]:
    if m.bounds:
        b = m.bounds
        return b.min_x, b.min_y, b.max_x, b.max_y
    xs = [p.x for w in m.walls for p in (w.start, w.end)]
    ys = [p.y for w in m.walls for p in (w.start, w.end)]
    return min([*xs, 0]), min([*ys, 0]), max([*xs, 1]), max([*ys, 1])


def wall_pieces(wall: Wall, gaps: list[WallGap]) -> list[tuple[Point2D, Point2D]]:
    length = math.dist((wall.start.x, wall.start.y), (wall.end.x, wall.end.y))
    if length == 0:
        return []
    ux = (wall.end.x - wall.start.x) / length
    uy = (wall.end.y - wall.start.y) / length
    cuts = []
    for g in gaps:
        t = (g.position.x - wall.start.x) * ux + (g.position.y - wall.start.y) * uy
        cuts.append((max(0.0, t - g.width / 2), min(length, t + g.width / 2)))
    cuts.sort(key=lambda c: c[0])

    def at(t: float) -> Point2D:
        return Point2D(x=wall.start.x + ux * t, y=wall.start.y + uy * t)

    pieces, cursor = [], 0.0
    for a, b in cuts:
        if a > cursor + 1e-6:
            pieces.append((at(cursor), at(a)))
        cursor = max(cursor, b)
    if cursor < length - 1e-6:
        pieces.append((at(cursor), at(length)))
    return pieces


def gap_ends(wall: Wall, gap: WallGap) -> tuple[Point2D, Point2D]:
    length = math.dist((wall.start.x, wall.start.y), (wall.end.x, wall.end.y)) or 1.0
    ux = (wall.end.x - wall.start.x) / length
    uy = (wall.end.y - wall.start.y) / length
    h = gap.width / 2
    return (
        Point2D(x=gap.position.x - ux * h, y=gap.position.y - uy * h),
        Point2D(x=gap.position.x + ux * h, y=gap.position.y + uy * h),
    )


# ---------- layout and viewport ----------


def fit_layout(m: FloorMap, cols: int, rows: int) -> Layout:
    """Zoom 1: the whole plan, centered, same scale on both axes (TypeScript layoutFor)."""
    min_x, min_y, max_x, max_y = plan_bounds(m)
    w = max(max_x - min_x, 1e-6)
    h = max(max_y - min_y, 1e-6)
    usable_c = cols - 1 - 2 * MARGIN_PINS
    usable_r = rows - 1 - 2 * MARGIN_PINS
    scale = min(usable_c / w, usable_r / h)
    return Layout(
        scale=scale,
        origin_col=MARGIN_PINS + (usable_c - w * scale) / 2,
        origin_row=MARGIN_PINS + (usable_r - h * scale) / 2,
        min_x=min_x,
        max_y=max_y,
    )


def zoom_layout(m: FloorMap, cols: int, rows: int, zoom: int, center: tuple[float, float] | None) -> Layout:
    """Zoom > 1: scale times zoom, centered on `center` (meters), clamped to the plan bounds.

    `center` is the latest valid position, or the previous viewport center when the pose is
    missing or lost. The proxy keeps that state; this function only draws what it is given.
    """
    if zoom not in ZOOMS:
        raise ValueError(f"zoom must be one of {ZOOMS}")
    base = fit_layout(m, cols, rows)
    if zoom == 1:
        return base
    min_x, min_y, max_x, max_y = plan_bounds(m)
    scale = base.scale * zoom
    half_w = (cols - 1) / scale / 2
    half_h = (rows - 1) / scale / 2
    cx, cy = center if center else ((min_x + max_x) / 2, (min_y + max_y) / 2)

    def clamp(v: float, lo: float, hi: float, half: float) -> float:
        if hi - lo <= 2 * half:  # plan narrower than the view on this axis: center it
            return (lo + hi) / 2
        return min(max(v, lo + half), hi - half)

    cx = clamp(cx, min_x, max_x, half_w)
    cy = clamp(cy, min_y, max_y, half_h)
    return Layout(scale=scale, origin_col=0.0, origin_row=0.0, min_x=cx - half_w, max_y=cy + half_h)


def _exact(layout: Layout, p: Point2D) -> tuple[float, float]:
    return (
        layout.origin_col + (p.x - layout.min_x) * layout.scale,
        layout.origin_row + (layout.max_y - p.y) * layout.scale,
    )


def to_pin(layout: Layout, x: float, y: float) -> tuple[int, int]:
    c, r = _exact(layout, Point2D(x=x, y=y))
    return js_round(c), js_round(r)


def _line_pins(a: tuple[float, float], b: tuple[float, float]) -> list[tuple[int, int]]:
    n = max(1, math.ceil(math.hypot(b[0] - a[0], b[1] - a[1]) * 4))
    seen: dict[tuple[int, int], None] = {}
    for i in range(n + 1):
        seen[(js_round(a[0] + (b[0] - a[0]) * i / n), js_round(a[1] + (b[1] - a[1]) * i / n))] = None
    return list(seen)


def _stamp(g: PinGrid, pattern: list[list[bool]], col: int, row: int, kind: int) -> None:
    for dr, line in enumerate(pattern):
        for dc, on in enumerate(line):
            if on:
                g.set(col - 1 + dc, row - 1 + dr, kind)


# ---------- drawing ----------


def map_pins(m: FloorMap, layout: Layout, cols: int, rows: int) -> tuple[PinGrid, list[Placed]]:
    """Pins that stay put while walking: walls with door gaps, and landmark symbols."""
    grid = PinGrid.empty(cols, rows)
    gaps = [*m.doors, *m.openings]

    for wall in m.walls:
        own = [g for g in gaps if g.wall_id == wall.id]
        for a, b in wall_pieces(wall, own):
            for c, r in _line_pins(_exact(layout, a), _exact(layout, b)):
                grid.set(c, r, WALL)

    # Rounding can close a narrow doorway. Reopen every gap to at least MIN_GAP_PINS.
    walls = {w.id: w for w in m.walls}
    for g in gaps:
        wall = walls.get(g.wall_id) if g.wall_id else None
        if not wall:
            continue
        p, q = gap_ends(wall, g)
        a, b = _exact(layout, p), _exact(layout, q)
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        need = MIN_GAP_PINS + 0.6
        grow = (need - length) / 2 / max(length, 1e-6) if length < need else 0.0
        a2 = (a[0] - (b[0] - a[0]) * grow, a[1] - (b[1] - a[1]) * grow)
        b2 = (b[0] + (b[0] - a[0]) * grow, b[1] + (b[1] - a[1]) * grow)
        for c, r in _line_pins(a2, b2):
            if grid.at(c, r) == WALL:
                grid.set(c, r, EMPTY)

    placed: list[Placed] = []
    for lm in m.landmarks:
        sym = PIN_SYMBOLS.get(lm.type)
        if not sym or lm.show_on_tactile is False:
            continue
        col, row = _place_symbol(grid, to_pin(layout, lm.position.x, lm.position.y), placed)
        _stamp(grid, sym[1], col, row, SYMBOL)
        placed.append(Placed(lm.id, lm.name, sym[0], col, row))
    return grid, placed


def _place_symbol(grid: PinGrid, want: tuple[int, int], placed: list[Placed]) -> tuple[int, int]:
    """Nearest spot where the 3x3 symbol plus a one-pin border touches no wall or symbol."""

    def clear(c: int, r: int) -> bool:
        if c < 1 or r < 1 or c > grid.cols - 2 or r > grid.rows - 2:
            return False
        for dr in range(-2, 3):
            for dc in range(-2, 3):
                if grid.at(c + dc, r + dr) != EMPTY:
                    return False
        return all(max(abs(p.col - c), abs(p.row - r)) >= 4 for p in placed)

    wc, wr = want
    for radius in range(5):
        best = None
        for dr in range(-radius, radius + 1):
            for dc in range(-radius, radius + 1):
                if max(abs(dr), abs(dc)) != radius:
                    continue
                c, r = wc + dc, wr + dr
                d = dc * dc + dr * dr
                if clear(c, r) and (best is None or d < best[2]):
                    best = (c, r, d)
        if best:
            return best[0], best[1]
    return want


def frame_pins(
    base: PinGrid, layout: Layout, pose: Pose | None, placed: list[Placed]
) -> tuple[PinGrid, tuple[int, int] | None]:
    """The full frame: the map plus the walker X and a heading tail, drawn on top."""
    grid = base.copy()
    if pose is None:
        return grid, None
    c0, r0 = to_pin(layout, pose.x, pose.y)
    col = min(grid.cols - 2, max(1, c0))
    row = min(grid.rows - 2, max(1, r0))
    # Drop whole symbols that would touch the X or its tail, so the shapes never merge.
    reach = 1 + max(HEADING_TAIL) + 1
    for p in placed:
        if max(abs(p.col - col), abs(p.row - row)) > reach:
            continue
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if grid.at(p.col + dc, p.row + dr) == SYMBOL:
                    grid.set(p.col + dc, p.row + dr, EMPTY)
    _stamp(grid, WALKER_PATTERN, col, row, WALKER)
    dx, dy = math.sin(pose.heading_rad), -math.cos(pose.heading_rad)  # clockwise from up; rows grow down
    for d in HEADING_TAIL:
        grid.set(js_round(col + dx * d), js_round(row + dy * d), WALKER)
    return grid, (col, row)


def render(
    m: FloorMap,
    cols: int = DEFAULT_COLS,
    rows: int = DEFAULT_ROWS,
    zoom: int = 1,
    center: tuple[float, float] | None = None,
    pose: Pose | None = None,
) -> PinGrid:
    """One complete frame for the display."""
    layout = zoom_layout(m, cols, rows, zoom, center)
    base, placed = map_pins(m, layout, cols, rows)
    grid, _ = frame_pins(base, layout, pose, placed)
    return grid


# ---------- output helpers ----------


def to_cell_bytes(g: PinGrid) -> bytes:
    """One byte per 2x4 cell, cells left to right, lines top to bottom.

    Bit order follows the Dot Pad GRAPHIC mode pin map (dotpad-sdk-guide, images/graphic-mode.png
    and Android/2.0.0/images/graphicData.png): pins 1-4 run down the LEFT column, pins 5-8 down
    the RIGHT column, and bit n is pin n+1. This is not braille dot numbering. Braille puts dots
    7 and 8 on the bottom row, which is what the TEXT area uses and what frontend toCellBytes
    copied, so that version scrambles pins inside every cell.
    """
    cc = math.ceil(g.cols / CELL_COLS)
    cr = math.ceil(g.rows / CELL_ROWS)
    dots = [(0, 0), (0, 1), (0, 2), (0, 3), (1, 0), (1, 1), (1, 2), (1, 3)]  # (col, row) for bit 0..7
    out = bytearray(cc * cr)
    for r in range(cr):
        for c in range(cc):
            byte = 0
            for bit, (dc, dr) in enumerate(dots):
                if g.at(c * 2 + dc, r * 4 + dr) != EMPTY:
                    byte |= 1 << bit
            out[r * cc + c] = byte
    return bytes(out)


def to_hex(b: bytes) -> str:
    return b.hex().upper()


def to_ascii(g: PinGrid) -> str:
    """Terminal preview: '#' wall, 'o' symbol, '@' walker, '.' flat."""
    chars = {EMPTY: ".", WALL: "#", SYMBOL: "o", WALKER: "@"}
    return "\n".join(
        "".join(chars[g.pins[r * g.cols + c]] for c in range(g.cols)) for r in range(g.rows)
    )
