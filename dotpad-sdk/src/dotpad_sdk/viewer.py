"""A loopback-only HTTP viewer, also hosting the optional vendor Web SDK bridge."""

import json
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from threading import Lock, Thread
from urllib.parse import parse_qs, urlsplit

from .browser import BrowserBackend
from .encoding import pack_graphics
from .gateway import DotPad
from .mock import MockBackend
from .model import Button, ButtonAction, DotPadError, Geometry, UnsupportedError


def demo_graphics(geometry: Geometry) -> bytes:
    """An explicitly synthetic floor-plan pattern for inspecting the pin grid."""
    width, height = geometry.pin_width, geometry.pin_height
    pins = [[False] * width for _ in range(height)]
    for y in range(height):
        for x in range(width):
            border = x in (2, width - 3) and 2 <= y <= height - 3 or y in (2, height - 3) and 2 <= x <= width - 3
            wall = x == width // 2 and 2 <= y <= height - 3 and abs(y - height // 2) > 3
            partition = y == height // 3 and width // 2 <= x <= width - 3
            path = y == height // 2 and x % 3 == 0 and 5 < x < width - 5
            pins[y][x] = border or wall or partition or path
    return pack_graphics(pins, geometry)


class ViewerServer:
    def __init__(self, pad: DotPad, *, host: str = "127.0.0.1", port: int = 8767,
                 web_sdk: str | Path | None = None):
        if host not in ("127.0.0.1", "localhost"):
            raise ValueError("The viewer binds to localhost only")
        self.pad = pad
        self.web_sdk = Path(web_sdk).expanduser().resolve() if web_sdk is not None else None
        if self.web_sdk is not None and not self.web_sdk.is_file():
            raise FileNotFoundError(self.web_sdk)
        self._history = deque(maxlen=12)
        self._history_lock = Lock()
        self._unsubscribe = None
        self._thread = None
        self._server = None
        self.host, self.port = host, port

    @property
    def url(self):
        if self._server is None:
            raise RuntimeError("Start the viewer first")
        return f"http://{self.host}:{self._server.server_port}"

    def start(self):
        if self._server is not None:
            return self
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def reply(self, status, data, content_type="application/json"):
                payload = json.dumps(data).encode() if content_type == "application/json" else data
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(payload)

            def valid_request(self):
                allowed_hosts = {f"127.0.0.1:{owner._server.server_port}", f"localhost:{owner._server.server_port}"}
                host = self.headers.get("Host")
                origin = self.headers.get("Origin")
                if host not in allowed_hosts or origin is not None and origin != f"http://{host}":
                    self.reply(403, {"error": "Only same-origin localhost requests are accepted"})
                    return False
                return True

            def do_GET(self):
                if not self.valid_request():
                    return
                parsed = urlsplit(self.path)
                assets = {"/": ("index.html", "text/html; charset=utf-8"),
                          "/hardware": ("hardware.html", "text/html; charset=utf-8"),
                          "/viewer.css": ("viewer.css", "text/css; charset=utf-8"),
                          "/viewer.js": ("viewer.js", "text/javascript; charset=utf-8"),
                          "/pins.js": ("pins.js", "text/javascript; charset=utf-8"),
                          "/hardware.js": ("hardware.js", "text/javascript; charset=utf-8")}
                try:
                    if parsed.path in assets:
                        name, mime = assets[parsed.path]
                        self.reply(200, files("dotpad_sdk").joinpath("web", name).read_bytes(), mime)
                    elif parsed.path == "/vendor-sdk.js" and owner.web_sdk is not None:
                        self.reply(200, owner.web_sdk.read_bytes(), "text/javascript; charset=utf-8")
                    elif parsed.path == "/api/config":
                        self.reply(200, {"mock": isinstance(owner.pad.backend, MockBackend),
                                         "browser": isinstance(owner.pad.backend, BrowserBackend),
                                         "web_sdk_available": owner.web_sdk is not None})
                    elif parsed.path == "/api/state":
                        state = owner.pad.snapshot()
                        with owner._history_lock:
                            state["events"] = list(owner._history)
                        state["pressed"] = [key.value for key in owner.pad.backend.pressed] if isinstance(owner.pad.backend, MockBackend) else []
                        self.reply(200, state)
                    elif parsed.path == "/api/bridge/commands":
                        backend = owner._browser()
                        session = parse_qs(parsed.query).get("session", [""])[0]
                        self.reply(200, {"commands": backend.take_commands(session)})
                    else:
                        self.reply(404, {"error": "Not found"})
                except (ValueError, DotPadError) as exc:
                    self.reply(409, {"error": str(exc)})

            def do_POST(self):
                if not self.valid_request():
                    return
                try:
                    if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                        self.reply(415, {"error": "Use application/json"})
                        return
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 262144:
                        self.reply(413, {"error": "Invalid request size"})
                        return
                    body = json.loads(self.rfile.read(length))
                    if not isinstance(body, dict):
                        raise ValueError("Expected a JSON object")
                    path = urlsplit(self.path).path
                    if path == "/api/buttons":
                        owner._mock().emit_button(Button(body["button"]), ButtonAction(body["action"]))
                    elif path == "/api/mock/frame":
                        owner._mock()
                        # Validate both areas before changing either one.
                        graphics = bytes.fromhex(body["graphics_hex"]) if "graphics_hex" in body else None
                        braille = bytes.fromhex(body["braille_hex"]) if "braille_hex" in body else None
                        if graphics is None and braille is None:
                            raise ValueError("Supply graphics_hex and/or braille_hex")
                        if graphics is not None and len(graphics) != owner.pad.geometry.graphic_cells:
                            raise ValueError("Wrong graphic frame size")
                        if braille is not None and len(braille) > owner.pad.geometry.braille_cells:
                            raise ValueError("Too many braille cells")
                        if graphics is not None:
                            owner.pad.display_graphics(graphics)
                        if braille is not None:
                            owner.pad.display_braille(braille)
                    elif path == "/api/mock/demo":
                        owner._mock()
                        owner.pad.display_graphics(demo_graphics(owner.pad.geometry))
                        owner.pad.display_braille(bytes.fromhex("193515"))  # Raw sample cells; no translation.
                    elif path == "/api/mock/clear":
                        owner._mock()
                        owner.pad.display_graphics(bytes(owner.pad.geometry.graphic_cells))
                        owner.pad.display_braille(b"")
                    elif path == "/api/mock/refresh":
                        owner._mock()
                        owner.pad.refresh_graphics()
                        owner.pad.refresh_braille()
                    elif path == "/api/bridge/connect":
                        owner._browser().attach(body["session"], Geometry(**body["geometry"]))
                    elif path == "/api/bridge/disconnect":
                        owner._browser().detach(body["session"])
                    elif path == "/api/bridge/ack":
                        error = body.get("error")
                        if error is not None and not isinstance(error, str):
                            raise ValueError("error must be a string or null")
                        owner._browser().acknowledge(body["session"], body["id"], error)
                    elif path == "/api/bridge/button":
                        owner._browser().emit_button(body["session"], body["button"], body["action"])
                    else:
                        self.reply(404, {"error": "Not found"})
                        return
                    self.reply(200, {"ok": True})
                except (ValueError, KeyError, TypeError) as exc:
                    self.reply(400, {"error": str(exc)})
                except DotPadError as exc:
                    self.reply(409, {"error": str(exc)})

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self._server.daemon_threads = True

        def record(event):
            with self._history_lock:
                self._history.append({"button": event.button.value, "action": event.action.value})

        self._unsubscribe = self.pad.on_button(record)
        self._thread = Thread(target=self._server.serve_forever, name="dotpad-viewer", daemon=True)
        self._thread.start()
        return self

    def _mock(self) -> MockBackend:
        if not isinstance(self.pad.backend, MockBackend):
            raise UnsupportedError("Mock controls are available only with MockBackend")
        return self.pad.backend

    def _browser(self) -> BrowserBackend:
        if not isinstance(self.pad.backend, BrowserBackend):
            raise UnsupportedError("This server is not using BrowserBackend")
        return self.pad.backend

    def close(self):
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._thread.join(timeout=2)
            self._server = None
            self._thread = None
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *_):
        self.close()
