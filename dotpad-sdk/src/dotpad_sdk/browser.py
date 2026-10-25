"""Python ↔ browser bridge. Device I/O stays inside the vendor Web SDK."""

from dataclasses import dataclass, field
from threading import Event, RLock
from uuid import uuid4

from .backend import Backend, ButtonHandler
from .model import (
    Button, ButtonAction, ButtonEvent, DotPadError, Geometry, NotConnectedError,
)


@dataclass
class _Command:
    area: str
    cells: bytes
    id: str = field(default_factory=lambda: uuid4().hex)
    done: Event = field(default_factory=Event)
    delivered: bool = False
    error: str | None = None


class BrowserBackend(Backend):
    supports_buttons = True

    def __init__(self, *, connect_timeout: float = 120, command_timeout: float = 10):
        if connect_timeout <= 0 or command_timeout <= 0:
            raise ValueError("Timeouts must be positive")
        self.geometry = Geometry()
        self.connect_timeout = connect_timeout
        self.command_timeout = command_timeout
        self._lock = RLock()
        self._ready = Event()
        self._session: str | None = None
        self._closed = False
        self._on_button: ButtonHandler | None = None
        self._commands: dict[str, _Command] = {}

    @property
    def connected(self):
        with self._lock:
            return self._session is not None and not self._closed

    def open(self, on_button: ButtonHandler):
        with self._lock:
            self._closed = False
            self._on_button = on_button
            if self._session is None:
                self._ready.clear()
        if not self._ready.wait(self.connect_timeout):
            raise DotPadError("Open the viewer's /hardware page and connect a DotPad before the timeout")
        if not self.connected:
            raise NotConnectedError("Browser connection was cancelled")

    def close(self):
        with self._lock:
            self._closed = True
            self._session = None
            self._on_button = None
            self._fail_pending("Browser backend closed")
            self._ready.set()  # Wake a concurrent open() so it can exit.

    def attach(self, session: str, geometry: Geometry):
        """Called by the local server after the vendor SDK reports device readiness."""
        with self._lock:
            if self._closed:
                raise NotConnectedError("Browser backend is closed")
            if not isinstance(session, str) or not 1 <= len(session) <= 128:
                raise ValueError("Invalid browser session")
            if self._session is not None:
                raise DotPadError("A browser already owns this device connection")
            self.geometry = geometry
            self._session = session
            self._ready.set()

    def _check_session(self, session):
        if not self.connected or session != self._session:
            raise NotConnectedError("Browser session is disconnected or expired")

    def detach(self, session: str):
        with self._lock:
            self._check_session(session)
            self._session = None
            self._ready.clear()
            self._fail_pending("DotPad disconnected from the browser")

    def _fail_pending(self, message):
        for command in self._commands.values():
            command.error = message
            command.done.set()
        self._commands.clear()

    def _write(self, area: str, cells: bytes):
        command = _Command(area, cells)
        with self._lock:
            if not self.connected:
                raise NotConnectedError("Connect a device on the /hardware page first")
            self._commands[command.id] = command
        if not command.done.wait(self.command_timeout):
            with self._lock:
                self._session = None
                self._ready.clear()
                self._fail_pending("Browser output timed out")
            raise DotPadError("Browser output timed out; submission status is unknown")
        if command.error:
            raise DotPadError(command.error)

    def write_graphics(self, cells: bytes):
        self._write("graphics", cells)

    def write_braille(self, cells: bytes):
        self._write("braille", cells)

    def take_commands(self, session: str) -> list[dict]:
        with self._lock:
            self._check_session(session)
            commands = []
            for command in self._commands.values():
                if not command.delivered:
                    command.delivered = True
                    commands.append({"id": command.id, "area": command.area, "hex": command.cells.hex()})
            return commands

    def acknowledge(self, session: str, command_id: str, error: str | None = None):
        with self._lock:
            self._check_session(session)
            command = self._commands.pop(command_id, None)
            if command is not None:
                if not command.delivered:
                    self._commands[command_id] = command
                    raise ValueError("Command has not been delivered")
                command.error = error
                command.done.set()

    def emit_button(self, session: str, button: str, action: str):
        event = ButtonEvent(Button(button), ButtonAction(action))
        with self._lock:
            self._check_session(session)
            callback = self._on_button
        if callback:
            callback(event)
