"""Graphic bytes are column-major pin bits; braille bytes use dot 1..8 bits."""

from collections.abc import Sequence

from .model import Geometry

# Rows from top to bottom, columns from left to right inside one 2×4 cell.
GRAPHIC_BITS = ((0x01, 0x10), (0x02, 0x20), (0x04, 0x40), (0x08, 0x80))
BRAILLE_BITS = ((0x01, 0x08), (0x02, 0x10), (0x04, 0x20), (0x40, 0x80))


def cell_pins(value: int, *, braille: bool = False) -> tuple[tuple[bool, bool], ...]:
    if type(value) is not int or not 0 <= value <= 255:
        raise ValueError("A cell must be a byte (0..255)")
    bits = BRAILLE_BITS if braille else GRAPHIC_BITS
    return tuple(tuple(bool(value & bit) for bit in row) for row in bits)


def pack_graphics(pins: Sequence[Sequence[bool | int]], geometry: Geometry = Geometry()) -> bytes:
    """Pack a row-major pin grid, origin at top left, into native graphic cells."""
    if len(pins) != geometry.pin_height or any(len(row) != geometry.pin_width for row in pins):
        raise ValueError(f"Expected a {geometry.pin_height}×{geometry.pin_width} pin grid")
    cells = bytearray(geometry.graphic_cells)
    for y, row in enumerate(pins):
        for x, raised in enumerate(row):
            if type(raised) not in (bool, int) or raised not in (0, 1):
                raise ValueError("Pins must be bool or 0/1")
            if raised:
                cells[(y // 4) * geometry.graphic_columns + x // 2] |= GRAPHIC_BITS[y % 4][x % 2]
    return bytes(cells)


def unpack_graphics(cells: bytes, geometry: Geometry = Geometry()) -> list[list[bool]]:
    if len(cells) != geometry.graphic_cells:
        raise ValueError(f"Expected {geometry.graphic_cells} graphic bytes")
    return [
        [bool(cells[(y // 4) * geometry.graphic_columns + x // 2] & GRAPHIC_BITS[y % 4][x % 2])
         for x in range(geometry.pin_width)]
        for y in range(geometry.pin_height)
    ]
