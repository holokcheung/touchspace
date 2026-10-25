"""Plan + pose -> one DotPad frame: a pin grid and a braille status line.

Python twin of frontend/src/lib/dotpad.ts, so the live DotPad and the web preview draw the same
picture: north (plan up) at the top, walls as pin lines, doorways at least 2 pins wide, 3 × 3
landmark symbols, and an X where the person is.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .scene import Plan, Pose, Pt, wall_pieces

MARGIN_PINS = 1
MIN_GAP_PINS = 2
# A first wall alone would otherwise fill the whole display.
MIN_EXTENT_M = 3.0

_S = lambda rows: tuple(tuple(c == "X" for c in r) for r in rows)  # noqa: E731
SYMBOLS = {
    "entrance": _S([".X.", "X.X", "XXX"]),
    "exit": _S(["XXX", "XXX", "XXX"]),
    "restroom": _S([".X.", "X.X", ".X."]),
    "stairs": _S(["XXX", "...", "XXX"]),
    "elevator": _S(["XXX", "X.X", "XXX"]),
    "information": _S([".X.", "XXX", ".X."]),
}
WALKER = _S(["X.X", ".X.", "X.X"])

EMPTY, WALL, SYMBOL, WALKER_PIN = 0, 1, 2, 3


@dataclass
class Layout:
    scale: float  # pins per meter
    origin_col: float
    origin_row: float
    min_x: float
    max_y: float

    def exact(self, p: Pt) -> tuple[float, float]:
        return self.origin_col + (p[0] - self.min_x) * self.scale, self.origin_row + (self.max_y - p[1]) * self.scale

    def pin(self, p: Pt) -> tuple[int, int]:
        c, r = self.exact(p)
        return round(c), round(r)


def layout_for(bounds: tuple[float, float, float, float], cols: int, rows: int) -> Layout:
    min_x, min_y, max_x, max_y = bounds
    # Grow small plans around their center so one wall isn't drawn edge to edge.
    if max_x - min_x < MIN_EXTENT_M:
        cx = (min_x + max_x) / 2
        min_x, max_x = cx - MIN_EXTENT_M / 2, cx + MIN_EXTENT_M / 2
    if max_y - min_y < MIN_EXTENT_M:
        cy = (min_y + max_y) / 2
        min_y, max_y = cy - MIN_EXTENT_M / 2, cy + MIN_EXTENT_M / 2
    w, h = max_x - min_x, max_y - min_y
    usable_c, usable_r = cols - 1 - 2 * MARGIN_PINS, rows - 1 - 2 * MARGIN_PINS
    scale = min(usable_c / w, usable_r / h)
    return Layout(
        scale=scale,
        origin_col=MARGIN_PINS + (usable_c - w * scale) / 2,
        origin_row=MARGIN_PINS + (usable_r - h * scale) / 2,
        min_x=min_x,
        max_y=max_y,
    )


class Grid:
    def __init__(self, cols: int, rows: int):
        self.cols, self.rows = cols, rows
        self.pins = [[EMPTY] * cols for _ in range(rows)]

    def get(self, c: int, r: int) -> int:
        return self.pins[r][c] if 0 <= c < self.cols and 0 <= r < self.rows else EMPTY

    def set(self, c: int, r: int, kind: int) -> None:
        if 0 <= c < self.cols and 0 <= r < self.rows:
            self.pins[r][c] = kind

    def stamp(self, pattern, c: int, r: int, kind: int) -> None:
        for dr, line in enumerate(pattern):
            for dc, on in enumerate(line):
                if on:
                    self.set(c - 1 + dc, r - 1 + dr, kind)

    def raised(self) -> list[list[bool]]:
        return [[p != EMPTY for p in row] for row in self.pins]


def line_pins(a: tuple[float, float], b: tuple[float, float]) -> list[tuple[int, int]]:
    n = max(1, math.ceil(math.hypot(b[0] - a[0], b[1] - a[1]) * 4))
    out: dict[tuple[int, int], None] = {}
    for i in range(n + 1):
        out[(round(a[0] + (b[0] - a[0]) * i / n), round(a[1] + (b[1] - a[1]) * i / n))] = None
    return list(out)


def _place_symbol(grid: Grid, want: tuple[int, int], placed: list[tuple[int, int]]) -> tuple[int, int]:
    """Nearest spot where a 3 × 3 symbol plus a one-pin border touches no wall or other symbol."""
    def clear(c: int, r: int) -> bool:
        if c < 1 or r < 1 or c > grid.cols - 2 or r > grid.rows - 2:
            return False
        if any(grid.get(c + dc, r + dr) != EMPTY for dr in range(-2, 3) for dc in range(-2, 3)):
            return False
        return all(max(abs(pc - c), abs(pr - r)) >= 4 for pc, pr in placed)

    for radius in range(5):
        best = None
        for dr in range(-radius, radius + 1):
            for dc in range(-radius, radius + 1):
                if max(abs(dr), abs(dc)) != radius:
                    continue
                c, r = want[0] + dc, want[1] + dr
                d = dc * dc + dr * dr
                if clear(c, r) and (best is None or d < best[2]):
                    best = (c, r, d)
        if best:
            return best[0], best[1]
    return want


def render(plan: Plan | None, pose: Pose | None, cols: int = 60, rows: int = 40) -> Grid:
    grid = Grid(cols, rows)
    bounds = plan.bounds() if plan else None
    if pose is not None:
        # Keep the person on the display when they step past what has been scanned. Grow in whole
        # meters so walking outside doesn't rescale (and fully redraw) the pins on every step.
        x0, y0, x1, y1 = bounds if bounds is not None else (pose.x, pose.y, pose.x, pose.y)
        if pose.x < x0:
            x0 = math.floor(pose.x - 0.5)
        if pose.x > x1:
            x1 = math.ceil(pose.x + 0.5)
        if pose.y < y0:
            y0 = math.floor(pose.y - 0.5)
        if pose.y > y1:
            y1 = math.ceil(pose.y + 0.5)
        bounds = (x0, y0, x1, y1)
    if bounds is None:
        return grid
    layout = layout_for(bounds, cols, rows)
    placed: list[tuple[int, int]] = []

    if plan:
        for wall in plan.walls:
            for a, b in wall_pieces(wall, plan.gaps):
                for c, r in line_pins(layout.exact(a), layout.exact(b)):
                    grid.set(c, r, WALL)
        # Rounding can fill a narrow doorway; reopen each one to at least MIN_GAP_PINS.
        for p, q in plan.gaps:
            a, b = layout.exact(p), layout.exact(q)
            length = math.hypot(b[0] - a[0], b[1] - a[1])
            need = MIN_GAP_PINS + 0.6
            grow = (need - length) / 2 / max(length, 1e-6) if length < need else 0.0
            a2 = (a[0] - (b[0] - a[0]) * grow, a[1] - (b[1] - a[1]) * grow)
            b2 = (b[0] + (b[0] - a[0]) * grow, b[1] + (b[1] - a[1]) * grow)
            for c, r in line_pins(a2, b2):
                if grid.get(c, r) == WALL:
                    grid.set(c, r, EMPTY)
        for kind, pos in plan.symbols:
            if kind in SYMBOLS:
                at = _place_symbol(grid, layout.pin(pos), placed)
                grid.stamp(SYMBOLS[kind], *at, SYMBOL)
                placed.append(at)

    if pose is not None:
        c, r = layout.pin((pose.x, pose.y))
        c, r = min(cols - 2, max(1, c)), min(rows - 2, max(1, r))
        # A symbol touching the X would feel like one shape; drop the whole symbol while standing
        # on it (the braille line says where you are). Centers 4 apart keep a flat pin between.
        for pc, pr in placed:
            if max(abs(pc - c), abs(pr - r)) <= 3:
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        if grid.get(pc + dc, pr + dr) == SYMBOL:
                            grid.set(pc + dc, pr + dr, EMPTY)
        grid.stamp(WALKER, c, r, WALKER_PIN)
    return grid


# --------------------------------------------------------------------------- braille status line

COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
_LETTERS = {
    "a": (1,), "b": (1, 2), "c": (1, 4), "d": (1, 4, 5), "e": (1, 5), "f": (1, 2, 4), "g": (1, 2, 4, 5),
    "h": (1, 2, 5), "i": (2, 4), "j": (2, 4, 5), "k": (1, 3), "l": (1, 2, 3), "m": (1, 3, 4),
    "n": (1, 3, 4, 5), "o": (1, 3, 5), "p": (1, 2, 3, 4), "q": (1, 2, 3, 4, 5), "r": (1, 2, 3, 5),
    "s": (2, 3, 4), "t": (2, 3, 4, 5), "u": (1, 3, 6), "v": (1, 2, 3, 6), "w": (2, 4, 5, 6),
    "x": (1, 3, 4, 6), "y": (1, 3, 4, 5, 6), "z": (1, 3, 5, 6),
}
_NUMBER_SIGN = (3, 4, 5, 6)


def compass_name(heading: float) -> str:
    deg = math.degrees(heading) % 360
    return COMPASS[round(deg / 45) % 8]


def status_text(plan: Plan | None, pose: Pose | None, live: bool, cells: int = 20) -> str:
    """Where you are and which way you face, cut to fit the braille line ("Kitchen NE")."""
    if pose is None:
        return "scanning" if live else "no position"
    room = plan.room_at((pose.x, pose.y)) if plan else None
    room = (room or ("scanning" if live and plan and not plan.rooms else "off map")).replace(" (unconfirmed)", "")
    tail = " " + compass_name(pose.heading)
    while room and len(encode_braille(room + tail)) > cells:
        room = room[:-1].rstrip()
    return room + tail


def encode_braille(text: str) -> bytes:
    """Uncontracted English braille, dot n -> bit n-1, with number signs. Capitals are not marked."""
    out: list[int] = []
    in_number = False
    for ch in text.lower():
        if ch.isdigit():
            if not in_number:
                out.append(_mask(_NUMBER_SIGN))
                in_number = True
            out.append(_mask(_LETTERS["jabcdefghi"[int(ch)]]))
            continue
        in_number = False
        out.append(_mask(_LETTERS[ch]) if ch in _LETTERS else 0)
    return bytes(out)


def braille_cells(text: str, cells: int = 20) -> bytes:
    return encode_braille(text)[:cells].ljust(cells, b"\0")


def _mask(dots: tuple[int, ...]) -> int:
    return sum(1 << (d - 1) for d in dots)
