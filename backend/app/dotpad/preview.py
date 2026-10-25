"""Print a Dot Pad frame in the terminal.

    python -m app.dotpad.preview ../sample-data/demo-building.json
    python -m app.dotpad.preview ../sample-data/demo-building.json --zoom 2 --x 4 --y 3 --heading 90
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from app.dotpad.raster import DEFAULT_COLS, DEFAULT_ROWS, Pose, render, to_ascii
from app.models.map import FloorMap


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("map", type=Path)
    ap.add_argument("--zoom", type=int, default=1, choices=[1, 2, 4, 8])
    ap.add_argument("--x", type=float)
    ap.add_argument("--y", type=float)
    ap.add_argument("--heading", type=float, default=0.0, help="degrees clockwise from map-up")
    ap.add_argument("--cols", type=int, default=DEFAULT_COLS)
    ap.add_argument("--rows", type=int, default=DEFAULT_ROWS)
    a = ap.parse_args()

    m = FloorMap.model_validate(json.loads(a.map.read_text(encoding="utf-8")))
    pose = Pose(a.x, a.y, math.radians(a.heading)) if a.x is not None and a.y is not None else None
    center = (pose.x, pose.y) if pose else None
    print(to_ascii(render(m, a.cols, a.rows, a.zoom, center, pose)))


if __name__ == "__main__":
    main()
