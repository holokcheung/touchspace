import random
import json
from importlib.resources import files

import pytest

from dotpad_sdk import Geometry, cell_pins, pack_graphics, unpack_graphics


@pytest.mark.parametrize("y,x,graphic,braille", [
    (0, 0, 1, 1), (1, 0, 2, 2), (2, 0, 4, 4), (3, 0, 8, 64),
    (0, 1, 16, 8), (1, 1, 32, 16), (2, 1, 64, 32), (3, 1, 128, 128),
])
def test_all_eight_pin_positions(y, x, graphic, braille):
    g = Geometry(1, 1, 1)
    pins = [[False] * 2 for _ in range(4)]
    pins[y][x] = True
    assert pack_graphics(pins, g) == bytes([graphic])
    assert unpack_graphics(bytes([graphic]), g) == pins
    assert cell_pins(braille, braille=True) == tuple(tuple(row) for row in pins)


def test_frame_cell_order_and_random_roundtrip():
    rng = random.Random(42)
    g = Geometry()
    frame = bytes(rng.randrange(256) for _ in range(g.graphic_cells))
    assert pack_graphics(unpack_graphics(frame, g), g) == frame
    frame = bytearray(300)
    frame[31] = 0x01
    pins = unpack_graphics(frame)
    assert pins[4][2]
    assert sum(sum(row) for row in pins) == 1


def test_invalid_pin_grid():
    with pytest.raises(ValueError):
        pack_graphics([[False]])
    pins = [[False] * 2 for _ in range(4)]
    pins[0][0] = "yes"
    with pytest.raises(ValueError):
        pack_graphics(pins, Geometry(1, 1, 1))


@pytest.mark.parametrize("value", [-1, 256, True, "01"])
def test_invalid_cell(value):
    with pytest.raises(ValueError):
        cell_pins(value)


def test_language_neutral_contract_matches_python_and_viewer_masks():
    from dotpad_sdk.encoding import GRAPHIC_BITS, BRAILLE_BITS
    contract = json.loads(files("dotpad_sdk").joinpath("contract.json").read_text())
    assert contract["graphics"]["pin_masks_by_row"] == [list(row) for row in GRAPHIC_BITS]
    assert contract["braille"]["pin_masks_by_row"] == [list(row) for row in BRAILLE_BITS]
