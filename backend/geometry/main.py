"""Run the whole pipeline:  python main.py samples/test-roomplan.json -o map.stl

All results are written into the output/ folder."""
import argparse
import json
import config
from parse import load_room
from plan import build_plan
from model import build_mesh, export_stl


def preview_png(plan, path):
    """Top-down picture of the 2D plan, for a quick sanity check before printing."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    def draw(ax, geom, color, hole_color="#eeeeee"):
        for p in getattr(geom, "geoms", [geom]):
            if p.is_empty or p.geom_type != "Polygon":
                continue
            ax.fill(*p.exterior.xy, color=color)
            for ring in p.interiors:            # a closed room is a hole inside the wall shape
                ax.fill(*ring.xy, color=hole_color)

    fig, ax = plt.subplots(figsize=(6, 6))
    draw(ax, plan.base, "#eeeeee")
    draw(ax, plan.walls, "#333333")
    if plan.objects is not None:
        draw(ax, plan.objects, "#4a90d9")
    for lab in plan.labels:
        ax.text(lab["x_mm"], lab["y_mm"], lab["label"], ha="center", fontsize=8, color="#c0392b")
    ax.set_aspect("equal")
    ax.set_title(f"Tactile plan 1:{config.SCALE} (mm), top view")
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)          # free the memory; matters once a web server calls this many times
    print(f"Saved {path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("json_path")
    ap.add_argument("-o", "--out", default="map.stl", help="file name; saved inside output/")
    ap.add_argument("--scale", type=float, help="override config.SCALE, e.g. 100 for 1:100")
    ap.add_argument("--parts", action="store_true",
                    help="also save base / walls / objects as separate STLs and a coloured GLB")
    args = ap.parse_args()
    if args.scale is not None:
        if args.scale <= 0:
            print("ERROR: --scale must be a positive number, e.g. --scale 100 for 1:100")
            raise SystemExit(1)
        config.SCALE = args.scale
    if not args.out.lower().endswith(".stl"):     # "-o mymap" -> "mymap.stl"
        args.out += ".stl"

    import sys
    try:
        room = load_room(args.json_path)
        if not room.walls:
            raise ValueError("No walls found in the scan. Please rescan the room.")
    except (ValueError, OSError, json.JSONDecodeError) as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    print(f"Loaded {len(room.walls)} walls, {len(room.doors)} doors/openings, "
          f"{len(room.objects)} objects, {len(room.sections)} labelled sections")
    from collections import Counter
    found = Counter(o.kind for o in room.objects)
    for kind, n in sorted(found.items()):
        status = "dropped" if kind in config.EXCLUDED_OBJECTS else "kept"
        print(f"  object {kind:<14} x{n}  {status}")
    try:
        plan = build_plan(room)
    except ValueError as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    import os
    if not os.path.dirname(args.out):           # plain name -> put it in output/
        # output/ always sits next to main.py, no matter which folder the command is run from.
        # (Relative to the current folder, a run from elsewhere would scatter output folders.)
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
        os.makedirs(out_dir, exist_ok=True)
        args.out = os.path.join(out_dir, args.out)
    base = args.out.rsplit(".", 1)[0]
    preview_png(plan, base + "_preview.png")
    with open(base + "_labels.json", "w", encoding="utf-8") as f:
        json.dump(plan.labels, f, indent=2)
    print(f"Saved {base}_labels.json")
    export_stl(build_mesh(plan), args.out)
    if args.parts:
        from model import export_parts
        export_parts(plan, base)
