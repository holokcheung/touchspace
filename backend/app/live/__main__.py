"""Run the live bridge: iPhone -> this Mac -> DotPad.

  cd backend
  .venv/bin/python -m app.live                       # mock DotPad, see it at http://127.0.0.1:8767
  .venv/bin/python -m app.live --dotpad browser --web-sdk ~/dotpad-vendor/DotPadSDK-3.0.4.js
  .venv/bin/python -m app.live --dotpad browser --web-sdk ... --test-pattern

See docs/live-dotpad.md for the full run-book.
"""

from __future__ import annotations

import argparse
import json
import logging
import secrets
import socket
import sys
from pathlib import Path
from threading import Event

from dotpad_sdk import BrowserBackend, DotPad, DotPadError, MockBackend, ViewerServer

from .output import BIT_ORDERS, DotPadOutput, Scene, pack
from .render import braille_cells
from .scene import plan_from_floormap, plan_from_roomplan
from .server import LiveState, create_app


def test_pattern(cols: int = 60, rows: int = 40) -> list[list[bool]]:
    """Shapes that look wrong if the bit order or orientation is wrong (docs/live-dotpad.md)."""
    pins = [[False] * cols for _ in range(rows)]
    for c in range(cols):
        pins[0][c] = pins[rows - 1][c] = True
    for r in range(rows):
        pins[r][0] = pins[r][cols - 1] = True
    pins[7][4] = True  # probe: the bottom-left pin of the cell at pins (4..5, 4..7)
    for i in range(28):  # diagonal, top-left to bottom-right
        pins[6 + i][10 + i] = True
    for r in range(8, 32):  # a capital F, upright and facing right
        pins[r][46] = True
    for c in range(46, 56):
        pins[8][c] = True
    for c in range(46, 53):
        pins[19][c] = True
    return pins


def lan_addresses() -> list[str]:
    found = set()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # no packet is sent; this just picks the outgoing interface
            found.add(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except OSError:
        pass
    return sorted(a for a in found if not a.startswith("127."))


def load_map(path: Path):
    data = json.loads(path.read_text())
    from app.models.map import FloorMap
    from app.services.roomplan import looks_like_roomplan

    if looks_like_roomplan(data):
        return plan_from_roomplan(data, name=path.stem)
    return plan_from_floormap(FloorMap.model_validate(data))


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m app.live", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dotpad", choices=("mock", "browser"), default="mock",
                   help="mock = on-screen pins only; browser = real DotPad through Chrome and the vendor Web SDK")
    p.add_argument("--web-sdk", help="path to Dot Inc's DotPadSDK-3.0.4.js (browser only; never commit it)")
    p.add_argument("--host", default="0.0.0.0", help="where the phone connects (default: all interfaces)")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--viewer-port", type=int, default=8767)
    p.add_argument("--map", type=Path, help="start with this map (FloorMap or RoomPlan JSON) until the phone sends one")
    p.add_argument("--token", help="phone must send ?token=...; default: a random one, printed below")
    p.add_argument("--no-token", action="store_true", help="accept any phone on the network")
    p.add_argument("--bit-order", choices=BIT_ORDERS, default="graphic",
                   help="pin bit layout inside each 2x4 cell; flip to 'braille' if the test pattern looks scrambled")
    p.add_argument("--min-interval", type=float, default=0.25, help="seconds between DotPad frames")
    p.add_argument("--test-pattern", action="store_true", help="show the orientation/bit-order test pattern and wait")
    args = p.parse_args()
    if args.dotpad == "browser" and not args.web_sdk:
        p.error("--dotpad browser needs --web-sdk /path/to/DotPadSDK-3.0.4.js")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.stdout.reconfigure(line_buffering=True)

    backend = MockBackend() if args.dotpad == "mock" else BrowserBackend(connect_timeout=30)
    pad = DotPad(backend)
    output = DotPadOutput(pad, bit_order=args.bit_order, min_interval=args.min_interval)
    try:
        viewer = ViewerServer(pad, port=args.viewer_port, web_sdk=args.web_sdk).start()
    except (OSError, FileNotFoundError) as exc:
        sys.exit(f"Could not start the DotPad viewer: {exc}")
    print(f"\nDotPad mirror (what the pins show):  {viewer.url}")
    if args.dotpad == "browser":
        print(f"Connect the real DotPad in Chrome:   {viewer.url}/hardware   (keep that tab open)")
    output.start()

    if args.test_pattern:
        def pattern(geometry):
            pins = test_pattern(geometry.pin_width, geometry.pin_height)
            return pack(pins, geometry, args.bit_order), braille_cells("dotpad test", geometry.braille_cells)

        output.show(Scene(None, None, False, override=pattern))
        print(f"\nTest pattern up (bit order: {args.bit_order}). Check it against docs/live-dotpad.md. Ctrl-C to stop.")
        try:
            Event().wait()
        except KeyboardInterrupt:
            pass
        finally:
            output.stop()
            viewer.close()
        return

    plan = None
    if args.map:
        try:
            plan = load_map(args.map)
        except (OSError, ValueError) as exc:
            sys.exit(f"Could not read {args.map}: {exc}")
    state = LiveState(output, plan)
    token = None if args.no_token else (args.token or secrets.token_hex(3))
    app = create_app(state, token)

    query = f"?token={token}" if token else ""
    print("\nPhone URL (type it into the app's DotPad setting):")
    for addr in lan_addresses() or ["<this-mac-ip>"]:
        print(f"  ws://{addr}:{args.port}/phone{query}")
    print("If venue Wi-Fi blocks phone-to-laptop traffic, put the Mac on the iPhone's Personal Hotspot,")
    print(f"or run `ngrok http {args.port}` and use wss://<id>.ngrok-free.app/phone{query}\n")

    import uvicorn

    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning", ws_max_size=8 * 1024 * 1024)
    finally:
        output.stop()
        viewer.close()


if __name__ == "__main__":
    try:
        main()
    except DotPadError as exc:
        sys.exit(str(exc))
