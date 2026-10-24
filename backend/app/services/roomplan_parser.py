"""Import Apple's Codable CapturedRoom shape into the app's normalized model.

RoomPlan's serialized transform is a 16-value simd_float4x4 in column-major
order. Surfaces use local X for width and local Y for height; a floor uses
local X/Y as its plane. Objects use local X/Z for their floor footprint.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np

from app.models.map import (
    Door,
    FloorMap,
    Landmark,
    LandmarkType,
    MapObject,
    Point2D,
    Room,
    SourceInfo,
    Wall,
    WallGap,
    Window,
    Opening,
)

IMPORTER_VERSION = "1.0"
REQUIRED_ARRAYS = ("walls", "doors", "windows", "openings", "objects", "floors")


class RoomPlanImportError(ValueError):
    """Raised when a RoomPlan document cannot be interpreted safely."""


def _point(value: np.ndarray) -> Point2D:
    return Point2D(x=float(value[0]), y=float(-value[2]))


def _matrix(element: dict[str, Any], kind: str, index: int) -> np.ndarray:
    raw = element.get("transform")
    if not isinstance(raw, list) or len(raw) != 16:
        raise RoomPlanImportError(f"{kind}[{index}] needs a 16-number transform matrix.")
    try:
        values = np.asarray(raw, dtype=float)
    except (TypeError, ValueError) as exc:
        raise RoomPlanImportError(f"{kind}[{index}] has a non-numeric transform matrix.") from exc
    if not np.isfinite(values).all():
        raise RoomPlanImportError(f"{kind}[{index}] has a non-finite transform value.")
    # Apple's simd matrix serialization lists the columns consecutively.
    matrix = values.reshape((4, 4), order="F")
    if not np.allclose(matrix[3], [0, 0, 0, 1], atol=1e-4):
        raise RoomPlanImportError(f"{kind}[{index}] has an invalid homogeneous transform row.")
    return matrix


def _dimensions(element: dict[str, Any], kind: str, index: int, count: int = 3) -> tuple[float, ...]:
    raw = element.get("dimensions")
    if not isinstance(raw, list) or len(raw) < count:
        raise RoomPlanImportError(f"{kind}[{index}] needs at least {count} dimensions.")
    try:
        result = tuple(float(v) for v in raw[:count])
    except (TypeError, ValueError) as exc:
        raise RoomPlanImportError(f"{kind}[{index}] has non-numeric dimensions.") from exc
    if not all(math.isfinite(v) for v in result) or any(v < 0 for v in result):
        raise RoomPlanImportError(f"{kind}[{index}] has invalid dimensions.")
    return result


def _confidence(element: dict[str, Any]) -> str | None:
    value = element.get("confidence")
    if not isinstance(value, dict):
        return None
    for level in ("high", "medium", "low"):
        if level in value:
            return level
    return None


def _category(element: dict[str, Any]) -> str:
    value = element.get("category")
    if isinstance(value, dict) and value:
        return str(next(iter(value)))
    return "unknown"


def _element_id(element: dict[str, Any], kind: str, index: int) -> str:
    value = element.get("identifier")
    return str(value) if value else f"roomplan-{kind}-{index + 1}"


def _transform_point(matrix: np.ndarray, x: float, y: float, z: float = 0.0) -> np.ndarray:
    return matrix @ np.array([x, y, z, 1.0])


def _surface_polygon(element: dict[str, Any], matrix: np.ndarray, kind: str, index: int) -> list[Point2D]:
    """Return a floor outline. polygonCorners are optional local 2D/3D points."""
    corners = element.get("polygonCorners")
    if isinstance(corners, list) and len(corners) >= 3:
        projected: list[Point2D] = []
        for corner in corners:
            try:
                if isinstance(corner, dict):
                    xyz = [float(corner.get(k, 0.0)) for k in ("x", "y", "z")]
                elif isinstance(corner, list) and len(corner) >= 2:
                    xyz = [float(corner[0]), float(corner[1]), float(corner[2]) if len(corner) > 2 else 0.0]
                else:
                    continue
                projected.append(_point(_transform_point(matrix, *xyz[:3])))
            except (TypeError, ValueError):
                continue
        if len(projected) >= 3:
            return projected
    width, height, _ = _dimensions(element, kind, index)
    local = [(-width / 2, -height / 2), (width / 2, -height / 2),
             (width / 2, height / 2), (-width / 2, height / 2)]
    return [_point(_transform_point(matrix, x, y)) for x, y in local]


def parse_roomplan_data(data: dict[str, Any], *, name: str = "RoomPlan scan") -> FloorMap:
    """Convert an Apple-style CapturedRoom JSON object to a FloorMap.

    Missing optional arrays are treated as empty. A malformed present item is
    reported with its collection and index instead of silently inventing data.
    """
    if not isinstance(data, dict):
        raise RoomPlanImportError("The RoomPlan document must be a JSON object.")
    for key in ("walls", "doors", "objects"):
        if not isinstance(data.get(key), list):
            raise RoomPlanImportError(f"The RoomPlan document needs a '{key}' array.")
    for key in REQUIRED_ARRAYS:
        if key in data and not isinstance(data[key], list):
            raise RoomPlanImportError(f"RoomPlan '{key}' must be an array when present.")

    fmap = FloorMap(
        id=f"roomplan-{uuid4().hex[:12]}",
        name=name[:200] or "RoomPlan scan",
        source=SourceInfo(kind="roomplan", description="Imported Codable CapturedRoom JSON", importer_version=IMPORTER_VERSION),
        floor_level=data.get("story") if isinstance(data.get("story"), int) else None,
    )

    for kind in REQUIRED_ARRAYS:
        values = data.get(kind, [])
        for index, item in enumerate(values):
            if not isinstance(item, dict):
                raise RoomPlanImportError(f"{kind}[{index}] must be an object.")
            matrix = _matrix(item, kind, index)
            dims = _dimensions(item, kind, index)
            ident = _element_id(item, kind, index)
            conf = _confidence(item)
            category = _category(item)
            metadata = {"source_category": category, "story": item.get("story"),
                        "parent_identifier": item.get("parentIdentifier"),
                        "unsupported_curve": bool(item.get("curve"))}

            if kind == "walls":
                width, height, _ = dims
                a = _point(_transform_point(matrix, -width / 2, 0))
                b = _point(_transform_point(matrix, width / 2, 0))
                fmap.walls.append(Wall(id=ident, start=a, end=b, thickness=0.15,
                                       height=height or None, confidence=conf, metadata=metadata))
            elif kind in ("doors", "openings", "windows"):
                width = dims[0]
                pos = _point(matrix[:, 3])
                if kind == "doors":
                    details = item.get("category", {}).get("door", {}) if isinstance(item.get("category"), dict) else {}
                    fmap.doors.append(Door(id=ident, position=pos, width=max(width, 0.01),
                                           is_open=details.get("isOpen") if isinstance(details, dict) else None,
                                           confidence=conf, metadata=metadata))
                elif kind == "openings":
                    fmap.openings.append(Opening(id=ident, position=pos, width=max(width, 0.01),
                                                 confidence=conf, metadata=metadata))
                else:
                    fmap.windows.append(Window(id=ident, position=pos, width=max(width, 0.01),
                                               confidence=conf, metadata=metadata))
            elif kind == "objects":
                width, height, depth = dims
                # A vertical object's local X axis projected to the X/-Z map plane
                # determines the orientation of its footprint.
                local_x = matrix[:3, 0]
                angle = math.atan2(-float(local_x[2]), float(local_x[0]))
                fmap.objects.append(MapObject(
                    id=ident, category=category, position=_point(matrix[:, 3]),
                    width=max(width, 0.01), depth=max(depth, 0.01), height=height or None,
                    rotation=angle, confidence=conf, include_in_tactile=False,
                    label=category.replace("_", " ").title(), metadata=metadata,
                ))
            elif kind == "floors":
                polygon = _surface_polygon(item, matrix, kind, index)
                fmap.rooms.append(Room(id=ident, name="Room outline", polygon=polygon))

    return fmap


def parse_roomplan_file(path: str | Path, *, name: str | None = None) -> FloorMap:
    """Load and parse a RoomPlan JSON file from disk."""
    source = Path(path)
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RoomPlanImportError(f"Could not read a valid JSON file: {exc}") from exc
    return parse_roomplan_data(data, name=name or source.stem.replace("-", " ").title())
