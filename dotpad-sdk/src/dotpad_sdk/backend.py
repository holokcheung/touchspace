"""The narrow interface a future Swift/JNI/IPC adapter must implement."""

from abc import ABC, abstractmethod
from collections.abc import Callable

from .model import ButtonEvent, Geometry

ButtonHandler = Callable[[ButtonEvent], None]


class Backend(ABC):
    geometry: Geometry
    supports_buttons: bool = False

    @property
    @abstractmethod
    def connected(self) -> bool: ...

    @abstractmethod
    def open(self, on_button: ButtonHandler) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def write_graphics(self, cells: bytes) -> None:
        """Submit a complete frame; return after submission, raise on failure."""

    @abstractmethod
    def write_braille(self, cells: bytes) -> None:
        """Submit a complete text line in braille dot-bit encoding."""
