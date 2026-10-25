"""Keeps the DotPad showing the latest frame, through James's dotpad_sdk gateway.

One worker thread owns the pad. Phone messages only replace the "latest scene"; the worker
renders it at the pad's real size, skips frames identical to what is already up, and never
sends faster than `min_interval` (the pins are mechanical and the SDK diffs line by line).
If the pad drops (Chrome tab closed, Bluetooth lost) it reopens and resends.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from threading import Condition, Thread

from dotpad_sdk import DotPad, DotPadError, Geometry, pack_graphics
from dotpad_sdk.encoding import BRAILLE_BITS

from .render import Grid, braille_cells, render, status_text
from .scene import Plan, Pose

log = logging.getLogger(__name__)

BIT_ORDERS = ("graphic", "braille")


def pack(pins: list[list[bool]], geometry: Geometry, bit_order: str = "graphic") -> bytes:
    """Pin grid -> graphic bytes. "graphic" = dotpad_sdk's column-major cell bits (the vendor
    guide's layout); "braille" = 8-dot braille numbering, in case the device proves to use that."""
    if bit_order == "graphic":
        return pack_graphics(pins, geometry)
    if bit_order != "braille":
        raise ValueError(f"bit order must be one of {BIT_ORDERS}")
    cells = bytearray(geometry.graphic_cells)
    for y, row in enumerate(pins):
        for x, raised in enumerate(row):
            if raised:
                cells[(y // 4) * geometry.graphic_columns + x // 2] |= BRAILLE_BITS[y % 4][x % 2]
    return bytes(cells)


@dataclass(frozen=True)
class Scene:
    plan: Plan | None
    pose: Pose | None
    live: bool  # still scanning: say "scanning" rather than "off map"
    # Raw (graphics, braille) for the pad's geometry instead of a map, e.g. the test pattern.
    override: Callable[[Geometry], tuple[bytes, bytes]] | None = None


class DotPadOutput:
    def __init__(self, pad: DotPad, *, bit_order: str = "graphic", min_interval: float = 0.25,
                 on_frame: Callable[[Grid, str], None] | None = None):
        if bit_order not in BIT_ORDERS:
            raise ValueError(f"bit order must be one of {BIT_ORDERS}")
        self.pad = pad
        self.bit_order = bit_order
        self.min_interval = min_interval
        self.on_frame = on_frame
        self.frames_sent = 0
        self.last_error: str | None = None
        self._cv = Condition()
        self._scene: Scene | None = None
        self._version = 0
        self._stopped = False
        self._thread: Thread | None = None

    @property
    def connected(self) -> bool:
        return self.pad.connected

    def show(self, scene: Scene) -> None:
        with self._cv:
            self._scene = scene
            self._version += 1
            self._cv.notify()

    def start(self) -> "DotPadOutput":
        self._thread = Thread(target=self._run, name="dotpad-output", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        with self._cv:
            self._stopped = True
            self._cv.notify()
        self.pad.close()  # also wakes an open() that is waiting for the browser
        if self._thread:
            self._thread.join(timeout=3)

    def frame_bytes(self, scene: Scene, geometry: Geometry) -> tuple[bytes, bytes, Grid | None, str]:
        if scene.override:
            g, b = scene.override(geometry)
            return g, b, None, ""
        grid = render(scene.plan, scene.pose, geometry.pin_width, geometry.pin_height)
        text = status_text(scene.plan, scene.pose, scene.live, geometry.braille_cells)
        return pack(grid.raised(), geometry, self.bit_order), braille_cells(text, geometry.braille_cells), grid, text

    def _run(self) -> None:
        sent: tuple[bytes, bytes] | None = None
        seen_version = -1
        last_send = 0.0
        while True:
            with self._cv:
                if self._stopped:
                    return
            if not self.pad.connected:
                sent, seen_version = None, -1  # resend the current scene once reconnected
                try:
                    self.pad.close()
                    self.pad.open()  # waits for Chrome's /hardware page when using the browser backend
                    self.last_error = None
                    log.info("DotPad connected: %s", self.pad.geometry)
                except DotPadError as exc:
                    self.last_error = str(exc)
                    with self._cv:
                        self._cv.wait(1.0)
                    continue
            with self._cv:
                if self._version == seen_version and not self._stopped:
                    self._cv.wait(1.0)
                if self._stopped:
                    return
                scene, version = self._scene, self._version
            if scene is None or version == seen_version:
                continue
            wait = self.min_interval - (time.monotonic() - last_send)
            if wait > 0:
                time.sleep(wait)
                continue  # pick up anything newer that arrived meanwhile
            seen_version = version
            try:
                graphics, braille, grid, text = self.frame_bytes(scene, self.pad.geometry)
                if (graphics, braille) == sent:
                    continue
                self.pad.display_graphics(graphics)
                self.pad.display_braille(braille)
                sent, last_send = (graphics, braille), time.monotonic()
                self.frames_sent += 1
                if self.on_frame and grid is not None:
                    self.on_frame(grid, text)
            except DotPadError as exc:
                seen_version = -1  # try this scene again
                self.last_error = str(exc)
                log.warning("DotPad write failed: %s", exc)
            except ValueError as exc:
                self.last_error = str(exc)
                log.warning("Could not draw this scene: %s", exc)
