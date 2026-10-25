import argparse
from threading import Event

from .browser import BrowserBackend
from .gateway import DotPad
from .mock import MockBackend
from .model import DotPadError
from .viewer import ViewerServer, demo_graphics


def main():
    parser = argparse.ArgumentParser(description="Local DotPad mock viewer or vendor Web SDK bridge")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--backend", choices=("mock", "browser"), default="mock")
    parser.add_argument("--web-sdk", help="Path to vendor DotPadSDK-3.0.4.js (browser backend only)")
    parser.add_argument("--demo", action="store_true", help="Start the mock with a synthetic floor plan")
    args = parser.parse_args()
    if args.backend == "browser" and not args.web_sdk:
        parser.error("--backend browser requires --web-sdk")
    if args.backend == "browser" and args.demo:
        parser.error("--demo is available only for the mock")
    pad = DotPad(MockBackend() if args.backend == "mock" else BrowserBackend())
    try:
        with ViewerServer(pad, port=args.port, web_sdk=args.web_sdk) as viewer:
            print(f"DotPad viewer: {viewer.url}", flush=True)
            if args.backend == "browser":
                print(f"Connect hardware: {viewer.url}/hardware", flush=True)
            with pad:
                if args.backend == "mock":
                    pad.display_graphics(demo_graphics(pad.geometry) if args.demo else bytes(pad.geometry.graphic_cells))
                    pad.display_braille(bytes.fromhex("193515") if args.demo else b"")
                Event().wait()
    except KeyboardInterrupt:
        pass
    except (DotPadError, OSError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
