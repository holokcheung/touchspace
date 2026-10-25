"""Synchronous raw output with serialized writes and isolated button callbacks."""

import logging
from collections.abc import Callable
from dataclasses import asdict
from queue import Queue
from threading import Lock, RLock, Thread, current_thread

from .backend import Backend, ButtonHandler
from .model import ButtonEvent, NotConnectedError

log = logging.getLogger(__name__)


class DotPad:
    def __init__(self, backend: Backend):
        self.backend = backend
        self._lock = RLock()
        self._listeners_lock = Lock()
        self._listeners: list[ButtonHandler] = []
        self._opened = False
        self._opening = False
        self._graphics: bytes | None = None
        self._braille: bytes | None = None
        self._revision = 0
        self._events: Queue[ButtonEvent | None] | None = None
        self._worker: Thread | None = None

    @property
    def geometry(self):
        return self.backend.geometry

    @property
    def connected(self) -> bool:
        return self._opened and self.backend.connected

    def open(self) -> "DotPad":
        with self._lock:
            if self._opened:
                self._require_connected()
                return self
            if self._opening:
                raise RuntimeError("Connection already in progress")
            self._opening = True
            events: Queue[ButtonEvent | None] = Queue()
            self._events = events
            self._worker = Thread(target=self._dispatch, args=(events,), name="dotpad-buttons", daemon=True)
            self._worker.start()
        try:
            # Do not hold the display lock while waiting for a browser or native device.
            self.backend.open(events.put)
            with self._lock:
                if not self._opening:
                    raise NotConnectedError("Connection was cancelled")
                if not self.backend.connected:
                    raise NotConnectedError("Backend returned without a ready device")
                self._opened = True
                self._opening = False
                self._graphics = None
                self._braille = None
                self._revision += 1
            return self
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        with self._lock:
            self._opened = False
            self._opening = False
            try:
                self.backend.close()
            finally:
                events, worker = self._events, self._worker
                self._events = None
                self._worker = None
                if events is not None:
                    events.put(None)
        if worker is not None and worker is not current_thread():
            worker.join(timeout=2)

    def __enter__(self):
        return self.open()

    def __exit__(self, *_):
        self.close()

    def on_button(self, callback: ButtonHandler) -> Callable[[], None]:
        """Subscribe to down/up events; returns an unsubscribe function.

        Callbacks run on a gateway thread, never the vendor's callback thread.
        Exceptions are logged and do not prevent delivery to other subscribers.
        """
        if not callable(callback):
            raise TypeError("Button callback must be callable")
        with self._listeners_lock:
            self._listeners.append(callback)

        def unsubscribe():
            with self._listeners_lock:
                if callback in self._listeners:
                    self._listeners.remove(callback)
        return unsubscribe

    def _dispatch(self, events):
        while (event := events.get()) is not None:
            with self._listeners_lock:
                callbacks = tuple(self._listeners)
            for callback in callbacks:
                try:
                    callback(event)
                except Exception:
                    log.exception("DotPad button callback failed")

    def _require_connected(self):
        if not self.connected:
            raise NotConnectedError("Open a DotPad connection before writing")

    @staticmethod
    def _bytes(data) -> bytes:
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("Raw cells must be bytes, bytearray, or memoryview")
        return bytes(data)

    def display_graphics(self, cells: bytes | bytearray | memoryview) -> None:
        data = self._bytes(cells)
        with self._lock:
            self._require_connected()
            if len(data) != self.geometry.graphic_cells:
                raise ValueError(f"Expected exactly {self.geometry.graphic_cells} graphic bytes")
            self.backend.write_graphics(data)
            self._graphics = data
            self._revision += 1

    def display_braille(self, cells: bytes | bytearray | memoryview) -> None:
        data = self._bytes(cells)
        with self._lock:
            self._require_connected()
            if len(data) > self.geometry.braille_cells:
                raise ValueError(f"At most {self.geometry.braille_cells} braille cells fit on this device")
            data = data.ljust(self.geometry.braille_cells, b"\0")
            self.backend.write_braille(data)
            self._braille = data
            self._revision += 1

    def refresh_graphics(self) -> None:
        """Resubmit the last successful graphic frame, including identical bytes."""
        with self._lock:
            self._require_connected()
            if self._graphics is None:
                raise ValueError("Display a graphic frame before refreshing it")
            self.display_graphics(self._graphics)

    def refresh_braille(self) -> None:
        with self._lock:
            self._require_connected()
            if self._braille is None:
                raise ValueError("Display braille cells before refreshing them")
            self.display_braille(self._braille)

    def snapshot(self) -> dict:
        """JSON-compatible last submitted state; not physical readback."""
        with self._lock:
            return {
                "protocol": 1,
                "backend": type(self.backend).__name__,
                "connected": self.connected,
                "supports_buttons": self.backend.supports_buttons,
                "geometry": asdict(self.geometry),
                "graphics_hex": (self._graphics or bytes(self.geometry.graphic_cells)).hex(),
                "braille_hex": (self._braille or bytes(self.geometry.braille_cells)).hex(),
                "graphics_submitted": self._graphics is not None,
                "braille_submitted": self._braille is not None,
                "revision": self._revision,
            }
