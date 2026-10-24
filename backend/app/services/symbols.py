"""Standard tactile landmark symbols.

Each symbol differs in outline and topology (corners, curvature, holes,
number of parts) rather than only in size, so they can be told apart by
touch. These are prototype shapes, not a published tactile standard.
"""

from __future__ import annotations

import math

from shapely import affinity
from shapely.geometry import MultiPolygon, Point, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from app.models.map import LandmarkType

# Order used for the legend strip.
SYMBOL_ORDER: list[LandmarkType] = [
    LandmarkType.entrance,
    LandmarkType.exit,
    LandmarkType.restroom,
    LandmarkType.stairs,
    LandmarkType.elevator,
    LandmarkType.information,
]

SYMBOL_NAMES: dict[LandmarkType, str] = {
    LandmarkType.entrance: "solid triangle",
    LandmarkType.exit: "solid square",
    LandmarkType.restroom: "solid circle",
    LandmarkType.stairs: "three parallel bars",
    LandmarkType.elevator: "hollow ring",
    LandmarkType.information: "plus sign",
}

_CIRCLE_RES = 32


def has_symbol(landmark_type: LandmarkType) -> bool:
    return landmark_type in SYMBOL_NAMES


def symbol_footprint(landmark_type: LandmarkType, cx: float, cy: float, size: float) -> BaseGeometry:
    """2D footprint (mm) of a symbol centered at (cx, cy) that fits in a `size` x `size` box."""
    half = size / 2
    if landmark_type == LandmarkType.entrance:
        r = half * 1.1  # circumradius; slightly larger so its area is comparable to the others
        pts = [(r * math.cos(math.radians(a)), r * math.sin(math.radians(a)) - r * 0.25) for a in (90, 210, 330)]
        shape: BaseGeometry = Polygon(pts)
    elif landmark_type == LandmarkType.exit:
        side = size * 0.85
        shape = box(-side / 2, -side / 2, side / 2, side / 2)
    elif landmark_type == LandmarkType.restroom:
        shape = Point(0, 0).buffer(half, quad_segs=_CIRCLE_RES // 4)
    elif landmark_type == LandmarkType.stairs:
        bar_h = size * 0.2
        step = (size - bar_h) / 2
        shape = MultiPolygon([box(-half, y - bar_h / 2, half, y + bar_h / 2) for y in (-step, 0.0, step)])
    elif landmark_type == LandmarkType.elevator:
        ring = max(1.2, size * 0.2)
        shape = Point(0, 0).buffer(half, quad_segs=_CIRCLE_RES // 4).difference(
            Point(0, 0).buffer(half - ring, quad_segs=_CIRCLE_RES // 4))
    elif landmark_type == LandmarkType.information:
        arm = size * 0.3
        shape = unary_union([box(-half, -arm / 2, half, arm / 2), box(-arm / 2, -half, arm / 2, half)])
    else:
        raise ValueError(f"No tactile symbol for landmark type '{landmark_type.value}'")
    return affinity.translate(shape, cx, cy)
