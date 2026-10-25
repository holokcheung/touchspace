"""Headless, thread-safe mock device. The viewer is an optional consumer."""

from threading import RLock

from .backend import Backend, ButtonHandler
from .model import Button, ButtonAction, ButtonEvent, Geometry, NotConnectedError


class MockBackend(Backend):
    supports_buttons = True

    def __init__(self, geometry: Geometry = Geometry()):
        self.geometry = geometry
        self._lock = RLock()
        self._connected = False
        self._on_button: ButtonHandler | None = None
        self._pressed: set[Button] = set()
        self.graphics = bytes(geometry.graphic_cells)
        self.braille = bytes(geometry.braille_cells)
        self.graphics_writes = 0
        self.braille_writes = 0

    @property
    def connected(self):
        with self._lock:
            return self._connected

    @property
    def pressed(self) -> tuple[Button, ...]:
        with self._lock:
            return tuple(sorted(self._pressed, key=lambda button: button.value))

    def open(self, on_button: ButtonHandler):
        with self._lock:
            self._on_button = on_button
            self._connected = True
            self._pressed.clear()
            self.graphics = bytes(self.geometry.graphic_cells)
            self.braille = bytes(self.geometry.braille_cells)

    def close(self):
        with self._lock:
            self._connected = False
            self._pressed.clear()
            self._on_button = None

    def _require_connected(self):
        if not self._connected:
            raise NotConnectedError("Mock device is disconnected")

    def write_graphics(self, cells: bytes):
        with self._lock:
            self._require_connected()
            self.graphics = bytes(cells)
            self.graphics_writes += 1

    def write_braille(self, cells: bytes):
        with self._lock:
            self._require_connected()
            self.braille = bytes(cells)
            self.braille_writes += 1

    def emit_button(self, button: Button | str, action: ButtonAction | str):
        button, action = Button(button), ButtonAction(action)
        with self._lock:
            self._require_connected()
            already_down = button in self._pressed
            if already_down == (action is ButtonAction.DOWN):
                return
            if action is ButtonAction.DOWN:
                self._pressed.add(button)
            else:
                self._pressed.remove(button)
            callback = self._on_button
        if callback:
            callback(ButtonEvent(button, action))
