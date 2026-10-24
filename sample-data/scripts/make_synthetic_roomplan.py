"""Write sample-data/synthetic-roomplan-capturedroom.json.

This is SYNTHETIC data shaped like Apple's `CapturedRoom` JSON encoding
(enums as single-key objects, column-major 4x4 transforms, [w, h, d]
dimensions). It exists so the upload/import path can be demonstrated and
tested without an iPhone. It is not a real scan, and it carries a
`_touchspace_synthetic` flag so the importer labels it as synthetic.

The room is laid out in a tidy local frame, then the whole scene is rotated
and shifted, the way a real RoomPlan world frame depends on where the phone
started.

Run from the repo root:  python sample-data/scripts/make_synthetic_roomplan.py
"""

from __future__ import annotations

import json
import math
import uuid
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parent.parent / "synthetic-roomplan-capturedroom.json"

WALL_HEIGHT = 2.6
FLOOR_Y = -1.35  # RoomPlan world origin is wherever the session started, often near chest height


def _uuid(seed: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"touchspace/{seed}")).upper()


def world_frame(yaw_deg: float, shift: tuple[float, float, float]) -> np.ndarray:
    """Global rotation about +Y and translation applied to every element."""
    a = math.radians(yaw_deg)
    g = np.eye(4)
    g[:3, :3] = [[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]]
    g[:3, 3] = shift
    return g


def local_matrix(px: float, py: float, y: float, plan_angle: float) -> np.ndarray:
    """Element frame from plan position/angle: local x along plan direction, local y up."""
    c, s = math.cos(plan_angle), math.sin(plan_angle)
    m = np.eye(4)
    m[:3, 0] = [c, 0, -s]  # plan direction (c, s) -> world (X, -Z)
    m[:3, 1] = [0, 1, 0]
    m[:3, 2] = [s, 0, c]  # right-handed: col0 x col1
    m[:3, 3] = [px, y, -py]
    return m


def flat(m: np.ndarray) -> list[float]:
    return [round(float(v), 6) for v in m.flatten(order="F")]  # simd column-major


def build(yaw_deg: float = 23.0, shift: tuple[float, float, float] = (1.7, 0.0, -2.4)) -> dict:
    g = world_frame(yaw_deg, shift)

    def element(seed: str, category: dict, m: np.ndarray, dims: list[float], **extra) -> dict:
        return {
            "identifier": _uuid(seed),
            "category": category,
            "confidence": {"high": {}},
            "transform": flat(g @ m),
            "dimensions": dims,
            "story": 0,
            **extra,
        }

    # Room in the local plan frame: 7 m (x) by 5 m (y).
    corners = [(0.0, 0.0), (7.0, 0.0), (7.0, 5.0), (0.0, 5.0)]
    walls = []
    wall_ids = []
    for i in range(4):
        (x1, y1), (x2, y2) = corners[i], corners[(i + 1) % 4]
        angle = math.atan2(y2 - y1, x2 - x1)
        m = local_matrix((x1 + x2) / 2, (y1 + y2) / 2, FLOOR_Y + WALL_HEIGHT / 2, angle)
        seed = f"wall-{i}"
        wall_ids.append(_uuid(seed))
        walls.append(element(seed, {"wall": {}}, m, [math.dist((x1, y1), (x2, y2)), WALL_HEIGHT, 0.0],
                             parentIdentifier=None, polygonCorners=[], completedEdges=[], curve=None))

    def on_wall(seed: str, wall: int, t: float, width: float, height: float, category: dict, bottom: float = 0.0) -> dict:
        (x1, y1), (x2, y2) = corners[wall], corners[(wall + 1) % 4]
        px, py = x1 + (x2 - x1) * t, y1 + (y2 - y1) * t
        m = local_matrix(px, py, FLOOR_Y + bottom + height / 2, math.atan2(y2 - y1, x2 - x1))
        return element(seed, category, m, [width, height, 0.0], parentIdentifier=wall_ids[wall],
                       polygonCorners=[], completedEdges=[], curve=None)

    doors = [on_wall("door-south", 0, 0.30, 0.9, 2.05, {"door": {"isOpen": True}})]
    openings = [on_wall("opening-east", 1, 0.55, 1.6, 2.2, {"opening": {}})]
    windows = [on_wall("window-north", 2, 0.5, 1.8, 1.2, {"window": {}}, bottom=0.9)]

    # Floor: local x/y span the floor plane; local z is up.
    fm = np.eye(4)
    fm[:3, 0] = [1, 0, 0]
    fm[:3, 1] = [0, 0, -1]  # local +y -> world -Z (plan +y)
    fm[:3, 2] = [0, 1, 0]
    fm[:3, 3] = [3.5, FLOOR_Y, -2.5]
    floor_corners = [[x - 3.5, y - 2.5, 0.0] for x, y in corners]
    floors = [element("floor", {"floor": {}}, fm, [7.0, 5.0, 0.0], parentIdentifier=None,
                      polygonCorners=floor_corners, completedEdges=[], curve=None)]

    def obj(seed: str, category: str, px: float, py: float, w: float, h: float, d: float, angle_deg: float = 0.0) -> dict:
        m = local_matrix(px, py, FLOOR_Y + h / 2, math.radians(angle_deg))
        return element(seed, {category: {}}, m, [w, h, d], parentIdentifier=None, attributes=[])

    objects = [
        obj("sofa", "sofa", 1.6, 3.9, 2.1, 0.85, 0.9),
        obj("table", "table", 3.6, 2.6, 1.6, 0.75, 0.9),
        obj("chair-1", "chair", 3.0, 1.8, 0.5, 0.9, 0.5),
        obj("chair-2", "chair", 4.2, 1.8, 0.5, 0.9, 0.5),
        obj("storage", "storage", 6.6, 1.0, 0.45, 1.9, 1.2, angle_deg=90),
        obj("tv", "television", 3.6, 4.85, 1.2, 0.7, 0.1),
        obj("stairs", "stairs", 5.6, 3.6, 1.0, 2.6, 2.2, angle_deg=90),
    ]

    center = g @ np.array([3.0, FLOOR_Y, -2.8, 1.0])
    sections = [{"label": {"livingRoom": {}}, "center": [round(float(v), 6) for v in center[:3]], "story": 0}]

    return {
        "_touchspace_synthetic": True,
        "_touchspace_description": "Synthetic 7 m x 5 m living room in RoomPlan CapturedRoom format. Not a real scan.",
        "identifier": _uuid("room"),
        "story": 0,
        "version": 2,
        "walls": walls,
        "doors": doors,
        "windows": windows,
        "openings": openings,
        "floors": floors,
        "objects": objects,
        "sections": sections,
    }


if __name__ == "__main__":
    OUT.write_text(json.dumps(build(), indent=2) + "\n")
    print(f"wrote {OUT}")
