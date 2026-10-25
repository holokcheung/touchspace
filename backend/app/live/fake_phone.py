"""Pretend to be the iPhone, to test the bridge and the DotPad without the app.

  .venv/bin/python -m app.live.fake_phone ws://127.0.0.1:8765/phone?token=abc123 \
      --scan ../sample-data/synthetic-roomplan-capturedroom.json
  .venv/bin/python -m app.live.fake_phone ws://... --map ../sample-data/demo-building.json

--scan sends a RoomPlan room that grows one wall at a time plus ARKit camera transforms, like
the app's live scan. --map sends a saved map in the iOS MapGeometry format plus map-frame poses,
like the app's AR navigation. Both walk a loop through the rooms.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import time
from pathlib import Path

from websockets.sync.client import connect

from app.models.map import FloorMap

from .scene import Plan, plan_from_floormap, plan_from_roomplan

SPEED_M_S = 0.8
RATE_HZ = 10


def world_transform(x: float, y: float, heading: float, eye: float = 1.4) -> list[float]:
    """Plan pose -> ARKit camera.transform, 16 floats column-major. Inverse of pose_from_world_transform."""
    s, c = math.sin(heading), math.cos(heading)
    return [c, 0, s, 0,   0, 1, 0, 0,   -s, 0, c, 0,   x, eye, -y, 1]


def ios_geometry(fmap: FloorMap) -> tuple[dict, list[dict]]:
    """FloorMap -> the iOS app's MapGeometry and MapNavigation.doors (MapPoint z = -plan y)."""
    mp = lambda p: {"x": p[0], "z": -p[1]}  # noqa: E731
    plan = plan_from_floormap(fmap)
    geometry = {
        "rooms": [{"id": f"r{i}", "name": name, "polygon": [mp(p) for p in poly]} for i, (name, poly) in enumerate(plan.rooms)],
        "walls": [{"id": f"w{i}", "start": mp(a), "end": mp(b), "thickness": 0.15} for i, (a, b) in enumerate(plan.walls)],
        "obstacles": [],
        "floorY": 0,
    }
    doors = [{"id": f"d{i}", "wallId": "", "roomIds": [], "start": mp(a), "end": mp(b)} for i, (a, b) in enumerate(plan.gaps)]
    return geometry, doors


def loop_path(plan: Plan) -> list[tuple[float, float]]:
    if len(plan.rooms) >= 2:
        pts = [(sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly)) for _, poly in plan.rooms]
    else:
        x0, y0, x1, y1 = plan.bounds() or (0, 0, 4, 4)
        mx, my = (x1 - x0) * 0.25, (y1 - y0) * 0.25
        pts = [(x0 + mx, y0 + my), (x1 - mx, y0 + my), (x1 - mx, y1 - my), (x0 + mx, y1 - my)]
    return pts + pts[:1]


def walk(path: list[tuple[float, float]]):
    """Endless (x, y, heading) samples along the loop."""
    while True:
        for (ax, ay), (bx, by) in zip(path, path[1:]):
            length = math.hypot(bx - ax, by - ay)
            heading = math.atan2(bx - ax, by - ay)  # compass: 0 = plan up
            steps = max(1, int(length / SPEED_M_S * RATE_HZ))
            for i in range(steps):
                t = i / steps
                yield ax + (bx - ax) * t, ay + (by - ay) * t, heading


def growing_rooms(room: dict):
    """The scan's room with 1, 2, ... walls, doors only once their wall is in."""
    walls = room.get("walls") or []
    for k in range(1, len(walls) + 1):
        partial = copy.deepcopy(room)
        partial["walls"] = walls[:k]
        ids = {w.get("identifier") for w in partial["walls"]}
        for key in ("doors", "windows", "openings"):
            partial[key] = [d for d in room.get(key) or [] if d.get("parentIdentifier") in ids]
        partial["floors"] = room.get("floors", []) if k == len(walls) else []
        yield partial


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("url", help="ws://<mac>:8765/phone?token=...")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--scan", type=Path, help="RoomPlan CapturedRoom JSON to 'scan' live")
    src.add_argument("--map", type=Path, help="FloorMap JSON to send as a saved iOS map")
    p.add_argument("--seconds", type=float, default=0, help="stop after this long (default: run until Ctrl-C)")
    args = p.parse_args()

    with connect(args.url, max_size=8 * 1024 * 1024) as ws:
        ws.send(json.dumps({"type": "hello", "client": "fake_phone"}))
        if args.scan:
            room = json.loads(args.scan.read_text())
            plan = plan_from_roomplan(room)
            stages = list(growing_rooms(room))
        else:
            fmap = FloorMap.model_validate(json.loads(args.map.read_text()))
            plan = plan_from_floormap(fmap)
            geometry, doors = ios_geometry(fmap)
            ws.send(json.dumps({"type": "map", "geometry": geometry, "doors": doors, "name": fmap.name}))
            stages = []

        started = time.monotonic()
        next_stage = started
        last_status = 0.0
        for n, (x, y, heading) in enumerate(walk(loop_path(plan))):
            now = time.monotonic()
            if args.seconds and now - started > args.seconds:
                break
            if stages and now >= next_stage:
                ws.send(json.dumps({"type": "map", "room": stages.pop(0), "live": True, "name": "Live scan"}))
                next_stage = now + 1.0
            if args.scan:
                ws.send(json.dumps({"type": "pose", "frame": "world", "transform": world_transform(x, y, heading)}))
            else:
                ws.send(json.dumps({"type": "pose", "frame": "map", "x": x, "z": -y, "heading": heading}))
            while True:
                try:
                    reply = json.loads(ws.recv(timeout=0))
                except TimeoutError:
                    break
                if reply.get("type") == "error":
                    print("server error:", reply["message"], flush=True)
                elif reply.get("type") == "status" and now - last_status > 3:
                    print("status:", {k: reply[k] for k in ("dotpad", "frames_sent", "map", "walls", "has_pose")}, flush=True)
                    last_status = now
            time.sleep(1 / RATE_HZ)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
