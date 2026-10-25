"""Dot Pad rasterizer: parity with the TypeScript preview, zoom viewport, heading tail."""

import hashlib
import json
import math
from pathlib import Path

import pytest

from app.dotpad.raster import (
    EMPTY,
    WALL,
    PinGrid,
    WALKER,
    Pose,
    fit_layout,
    frame_pins,
    map_pins,
    render,
    to_cell_bytes,
    zoom_layout,
)
from app.models.map import FloorMap

ROOT = Path(__file__).resolve().parents[2]

# sha256 of frontend/src/lib/dotpad.ts mapPins() output (60 x 40), taken with tsx.
# If dotpad.ts changes on purpose, regenerate these instead of loosening the test.
TS_PARITY = {
    "sample-data/demo-building.json": "dcc5ba5562618b5b28d5eb6af83610cc63f675f323d4966bd33b6e364b4706c5",
    "frontend/standalone/maps/apartment.json": "72a4bee17f718ede6a34b761548d720e4327910ea91e6e29c9352a2fb13ee668",
}


def load(rel: str) -> FloorMap:
    return FloorMap.model_validate(json.loads((ROOT / rel).read_text(encoding="utf-8")))


@pytest.mark.parametrize("rel,digest", TS_PARITY.items())
def test_zoom1_matches_typescript(rel, digest):
    m = load(rel)
    grid, _ = map_pins(m, fit_layout(m, 60, 40), 60, 40)
    assert hashlib.sha256(grid.pins).hexdigest() == digest


def test_cell_bytes_cover_300_cells():
    m = load("sample-data/demo-building.json")
    assert len(to_cell_bytes(render(m))) == 30 * 10


def test_heading_tail_points_the_right_way():
    m = load("sample-data/demo-building.json")
    layout = zoom_layout(m, 60, 40, 4, (8, 8))
    base, placed = map_pins(m, layout, 60, 40)
    for deg, (dc, dr) in {0: (0, -1), 90: (1, 0), 180: (0, 1), 270: (-1, 0)}.items():
        g, (col, row) = frame_pins(base, layout, Pose(8, 8, math.radians(deg)), placed)
        assert g.at(col + 2 * dc, row + 2 * dr) == WALKER, deg
        assert g.at(col + 3 * dc, row + 3 * dr) == WALKER, deg
        assert g.at(col - 3 * dc, row - 3 * dr) != WALKER, deg


def test_zoom_viewport_stays_inside_plan():
    m = load("sample-data/demo-building.json")
    corner = zoom_layout(m, 60, 40, 8, center=(-100.0, -100.0))
    assert corner.min_x == pytest.approx(0.0)  # clamped to the plan's left edge
    with pytest.raises(ValueError):
        zoom_layout(m, 60, 40, 3, None)


def test_grid_size_comes_from_caller():
    m = load("sample-data/demo-building.json")
    g = render(m, cols=40, rows=24)
    assert (g.cols, g.rows, len(g.pins)) == (40, 24, 960)
    assert any(p != EMPTY for p in g.pins)


def test_cell_bit_order_matches_sdk_graphic_mode():
    """The SDK's own example: pins 1, 3, 5, 6 raised -> hex 35 (images/graphic-mode.png)."""
    g = PinGrid.empty(2, 4)
    for col, row in [(0, 0), (0, 2), (1, 0), (1, 1)]:  # pin1, pin3, pin5, pin6
        g.set(col, row, WALL)
    assert to_cell_bytes(g) == bytes([0x35])


def test_each_pin_lands_on_its_own_bit():
    for bit, (col, row) in enumerate([(0, 0), (0, 1), (0, 2), (0, 3), (1, 0), (1, 1), (1, 2), (1, 3)]):
        g = PinGrid.empty(2, 4)
        g.set(col, row, WALL)
        assert to_cell_bytes(g) == bytes([1 << bit])
