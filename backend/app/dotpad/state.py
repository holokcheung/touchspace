"""What one Dot Pad should show: map, zoom, viewport center, pose, and display size.

Pure state with no networking, so the rules from docs/DOTPAD_API.md can be tested directly.
The server owns one DisplayState per display and pushes frame_hex() to the bridge.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.dotpad.raster import CELL_COLS, CELL_ROWS, ZOOMS, Pose, render, to_cell_bytes, to_hex
from app.models.map import FloorMap

# Until the bridge reports the real board, assume the common 30 x 10 cell graphic area.
DEFAULT_CELL_COLS = 30
DEFAULT_CELL_ROWS = 10


@dataclass
class DisplayState:
    display_id: str
    cell_cols: int = DEFAULT_CELL_COLS
    cell_rows: int = DEFAULT_CELL_ROWS
    device_state: str = "disconnected"  # disconnected | connecting | connected | error
    map: FloorMap | None = None
    zoom: int = 1
    center: tuple[float, float] | None = None  # viewport center in plan meters
    pose: Pose | None = None  # latest valid pose; None when none, lost or stale
    version: int = field(default=0)  # bumps on every change that alters the frame

    # ---- inputs ----

    def set_board(self, cell_cols: int, cell_rows: int) -> None:
        if cell_cols <= 0 or cell_rows <= 0:
            raise ValueError("board size must be positive")
        self.cell_cols, self.cell_rows = cell_cols, cell_rows
        self.version += 1

    def set_map(self, m: FloorMap) -> None:
        """A new map resets zoom and clears the pose (docs: 'New maps reset zoom to 1')."""
        self.map = m
        self.zoom = 1
        self.center = None
        self.pose = None
        self.version += 1

    def set_pose(self, pose: Pose | None) -> None:
        """Valid pose: show it and follow it. None (lost/stale): hide marker, keep viewport."""
        self.pose = pose
        if pose is not None:
            self.center = (pose.x, pose.y)
        self.version += 1

    def zoom_in(self) -> None:
        self._step_zoom(+1)

    def zoom_out(self) -> None:
        self._step_zoom(-1)

    def _step_zoom(self, step: int) -> None:
        i = min(max(ZOOMS.index(self.zoom) + step, 0), len(ZOOMS) - 1)
        if ZOOMS[i] != self.zoom:
            self.zoom = ZOOMS[i]
            self.version += 1

    # ---- output ----

    @property
    def pin_cols(self) -> int:
        return self.cell_cols * CELL_COLS

    @property
    def pin_rows(self) -> int:
        return self.cell_rows * CELL_ROWS

    def frame_hex(self) -> str:
        """Hex for sdk.displayGraphicData(): one byte per cell, all-flat when no map."""
        if self.map is None:
            return "00" * (self.cell_cols * self.cell_rows)
        grid = render(self.map, self.pin_cols, self.pin_rows, self.zoom, self.center, self.pose)
        return to_hex(to_cell_bytes(grid))
