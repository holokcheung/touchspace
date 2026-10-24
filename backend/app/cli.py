"""Command-line access to the tactile pipeline, handy for print testing.

    python -m app.cli generate ../sample-data/demo-building.json -o demo.stl
    python -m app.cli generate map.json --set wall_height_mm=3 --set include_paths=true
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.models import FloorMap
from app.services.floorplan import process_map
from app.services.tactile import TactileGenerationError, export_stl, generate_tactile_model, stl_filename


def _parse_overrides(pairs: list[str]) -> dict:
    out: dict = {}
    for pair in pairs:
        key, _, raw = pair.partition("=")
        if raw.lower() in ("true", "false"):
            out[key] = raw.lower() == "true"
        else:
            try:
                out[key] = float(raw)
            except ValueError:
                sys.exit(f"Cannot parse setting '{pair}'")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(prog="touchspace")
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate", help="Generate a tactile STL from a normalized map JSON")
    gen.add_argument("map", type=Path)
    gen.add_argument("-o", "--output", type=Path)
    gen.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="Override a tactile setting")
    args = parser.parse_args()

    fmap = FloorMap.model_validate(json.loads(args.map.read_text()))
    result = process_map(fmap)
    for issue in result.issues:
        print(f"[{issue.severity}] {issue.message}")
    settings = result.map.tactile.model_copy(update=_parse_overrides(args.set))
    try:
        mesh, report = generate_tactile_model(result.map, type(settings).model_validate(settings.model_dump()))
    except TactileGenerationError as exc:
        sys.exit(f"Generation failed: {exc}")
    out = args.output or Path(stl_filename(result.map))
    out.write_bytes(export_stl(mesh))
    print(f"Wrote {out} ({report.width_mm} x {report.depth_mm} x {report.height_mm} mm, {report.triangle_count} triangles)")
    for w in report.warnings:
        print(f"[warning] {w}")
    print("\n".join(report.summary))


if __name__ == "__main__":
    main()
