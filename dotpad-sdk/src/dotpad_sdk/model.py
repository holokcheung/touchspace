"""Portable values: no native handles, UI objects, or translation engines."""

from dataclasses import dataclass, field
from enum import Enum
from time import monotonic


class DotPadError(RuntimeError):
    """A connection or output operation failed."""


class NotConnectedError(DotPadError):
    pass


class UnsupportedError(DotPadError):
    pass


@dataclass(frozen=True)
class Geometry:
    graphic_columns: int = 30
    graphic_rows: int = 10
    braille_cells: int = 20

    def __post_init__(self):
        for value in (self.graphic_columns, self.graphic_rows, self.braille_cells):
            if type(value) is not int or not 1 <= value <= 256:
                raise ValueError("Geometry dimensions must be integers between 1 and 256")

    @property
    def graphic_cells(self) -> int:
        return self.graphic_columns * self.graphic_rows

    @property
    def pin_width(self) -> int:
        return self.graphic_columns * 2

    @property
    def pin_height(self) -> int:
        return self.graphic_rows * 4


class Button(str, Enum):
    FUNCTION_1 = "function1"
    FUNCTION_2 = "function2"
    FUNCTION_3 = "function3"
    FUNCTION_4 = "function4"
    PANNING_LEFT = "panning_left"
    PANNING_RIGHT = "panning_right"


class ButtonAction(str, Enum):
    DOWN = "down"
    UP = "up"


@dataclass(frozen=True)
class ButtonEvent:
    button: Button
    action: ButtonAction
    timestamp: float = field(default_factory=monotonic)
