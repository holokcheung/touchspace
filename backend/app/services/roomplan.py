"""Import Apple RoomPlan `CapturedRoom` / `CapturedStructure` JSON into a FloorMap.

The input is whatever `JSONEncoder().encode(capturedRoom)` produces on the
device; we do not define our own Apple-side format. Encoding details this
module relies on (Apple docs + observed exports):

* Every element has `identifier`, `category`, `confidence`, `dimensions`,
  `transform`, and optionally `parentIdentifier`, `polygonCorners`, `curve`,
  `story`.
* Enums encode as single-key objects: `{"wall": {}}`, `{"door": {"isOpen": true}}`,
  `{"high": {}}`. Plain strings are accepted too.
* `transform` is a simd_float4x4 encoded as 16 floats in column-major order:
  column 0 is the element's local x ("right", along a wall), column 1 is up,
  column 2 is the surface normal, column 3 is the translation of its center.
* `dimensions` is [width, height, depth] in meters; depth is 0 for surfaces.
* World space is ARKit's: meters, +Y up, right-handed. We project to the
  floor plan with plan x = X and plan y = -Z, which is the view from above
  without mirroring.

RoomPlan does not report wall thickness, room names, walkable routes, or
which door is an entrance, so none of those are invented here.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

import numpy as np

from app.models.map import (
    Door,
    FloorMap,
    Landmark,
    LandmarkType,
    MapObject,
    Opening,
    Point2D,
    Room,
    SourceInfo,
    Wall,
    Window,
)

IMPORTER_VERSION = "roomplan-importer/1"
DEFAULT_WALL_THICKNESS_M = 0.15  # RoomPlan surfaces have no thickness

SECTION_NAMES = {
    "bedroom": "Bedroom",
    "bathroom": "Bathroom",
    "kitchen": "Kitchen",
    "livingRoom": "Living room",
    "diningRoom": "Dining room",
}

OBJECT_LABELS = {"washerDryer": "Washer/dryer", "television": "TV"}


class RoomPlanImportError(ValueError):
    def __init__(self, message: str, details: list[str] | None = None):
        super().__init__(message)
        self.details = details or []


# --------------------------------------------------------------------------- decoding helpers


def enum_case(value: Any) -> tuple[str, dict]:
    """Decode a Swift enum: {"door": {"isOpen": true}} -> ("door", {"isOpen": True})."""
    if isinstance(value, str):
        return value, {}
    if isinstance(value, dict) and len(value) == 1:
        key, payload = next(iter(value.items()))
        return str(key), payload if isinstance(payload, dict) else {}
    raise ValueError(f"unrecognized enum value {value!r}")


def decode_matrix(value: Any) -> np.ndarray:
    """simd_float4x4 -> 4x4 numpy array. Accepts 16 column-major floats or 4 column arrays."""
    if isinstance(value, list) and len(value) == 16:
        m = np.array(value, dtype=float).reshape((4, 4), order="F")
    elif isinstance(value, list) and len(value) == 4 and all(isinstance(c, list) and len(c) == 4 for c in value):
        m = np.array(value, dtype=float).T  # list of columns
    else:
        raise ValueError("transform must be 16 numbers (column-major 4x4)")
    if not np.all(np.isfinite(m)):
        raise ValueError("transform contains non-finite numbers")
    return m


def decode_vec3(value: Any, name: str) -> np.ndarray:
    if not (isinstance(value, list) and len(value) >= 3):
        raise ValueError(f"{name} must be a list of 3 numbers")
    v = np.array(value[:3], dtype=float)
    if not np.all(np.isfinite(v)):
        raise ValueError(f"{name} contains non-finite numbers")
    return v


def to_plan(world: np.ndarray) -> Point2D:
    """World (X, Y-up, Z) -> plan (x, y) seen from above."""
    return Point2D(x=round(float(world[0]), 6), y=round(float(-world[2]), 6))


def apply(m: np.ndarray, local: tuple[float, float, float]) -> np.ndarray:
    return (m @ np.array([*local, 1.0]))[:3]


def plan_angle(m: np.ndarray) -> float:
    """Plan rotation (radians, CCW) of the element's local x axis."""
    u = m[:3, 0]
    return math.atan2(-u[2], u[0])


def _confidence(el: dict) -> str | None:
    try:
        key, _ = enum_case(el.get("confidence"))
    except ValueError:
        return None
    return key if key in ("low", "medium", "high") else None


def _short_id(prefix: str, identifier: str, used: set[str]) -> str:
    base = f"{prefix}_{re.sub(r'[^a-zA-Z0-9]', '', identifier)[:8].lower() or 'x'}"
    candidate, n = base, 2
    while candidate in used:
        candidate, n = f"{base}_{n}", n + 1
    used.add(candidate)
    return candidate


def _humanize(category: str) -> str:
    if category in OBJECT_LABELS:
        return OBJECT_LABELS[category]
    return re.sub(r"(?<!^)(?=[A-Z])", " ", category).capitalize()


# --------------------------------------------------------------------------- structure handling


def _collect(data: dict) -> dict[str, list]:
    """Gather element lists from a CapturedRoom, or a CapturedStructure's merged lists or its rooms."""
    keys = ("walls", "doors", "windows", "openings", "objects", "floors", "sections")
    if isinstance(data.get("walls"), list) and data["walls"]:
        return {k: list(data.get(k) or []) for k in keys}
    rooms = data.get("rooms")
    if isinstance(rooms, list) and rooms:
        merged: dict[str, list] = {k: [] for k in keys}
        for room in rooms:
            if isinstance(room, dict):
                for k in keys:
                    merged[k].extend(room.get(k) or [])
        return merged
    return {k: list(data.get(k) or []) for k in keys}


def looks_like_roomplan(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    elements = _collect(data)
    for k in ("walls", "doors", "objects", "floors"):
        for el in elements[k][:1]:
            if isinstance(el, dict) and "transform" in el and "dimensions" in el:
                return True
    return False


# --------------------------------------------------------------------------- main entry point


def import_roomplan(data: dict, *, name: str | None = None) -> tuple[FloorMap, list[str]]:
    """Convert RoomPlan JSON to a FloorMap. Returns (map, warnings). Raises RoomPlanImportError."""
    if not isinstance(data, dict):
        raise RoomPlanImportError("A RoomPlan export must be a JSON object.")
    elements = _collect(data)
    warnings: list[str] = []
    problems: list[str] = []
    used_ids: set[str] = set()

    def bad(path: str, exc: Exception) -> None:
        problems.append(f"{path}: {exc}")

    # ---- walls
    walls: list[Wall] = []
    wall_by_uuid: dict[str, str] = {}
    stories: list[int] = []
    tilted = 0
    curved = 0
    for i, el in enumerate(elements["walls"]):
        path = f"walls[{i}]"
        try:
            if not isinstance(el, dict):
                raise ValueError("expected an object")
            m = decode_matrix(el.get("transform"))
            dims = decode_vec3(el.get("dimensions"), "dimensions")
            width, height = float(dims[0]), float(dims[1])
            if width <= 0:
                raise ValueError("wall width must be positive")
            if abs(m[1, 1]) < 0.9:  # local up should be world up for a standing wall
                tilted += 1
            if el.get("curve") is not None:
                curved += 1
            start, end = apply(m, (-width / 2, 0, 0)), apply(m, (width / 2, 0, 0))
            uuid = str(el.get("identifier") or f"wall{i}")
            wid = _short_id("w", uuid, used_ids)
            wall_by_uuid[uuid] = wid
            if isinstance(el.get("story"), int):
                stories.append(el["story"])
            walls.append(Wall(
                id=wid, start=to_plan(start), end=to_plan(end), thickness=DEFAULT_WALL_THICKNESS_M,
                height=height if height > 0 else None, confidence=_confidence(el),
                metadata={"roomplan_id": uuid},
            ))
        except (ValueError, TypeError) as exc:
            bad(path, exc)

    if not walls:
        raise RoomPlanImportError(
            "No usable walls were found in this RoomPlan export. Scan again and make sure RoomPlan outlines the walls.",
            problems[:10],
        )
    if tilted:
        warnings.append(f"{tilted} wall(s) are not upright in the scan; their floor-plan position may be off.")
    if curved:
        warnings.append(f"{curved} curved wall(s) were straightened into a single segment.")

    # ---- doors, openings, windows
    def gaps(kind: str, cls):
        out = []
        for i, el in enumerate(elements[kind]):
            path = f"{kind}[{i}]"
            try:
                m = decode_matrix(el.get("transform"))
                dims = decode_vec3(el.get("dimensions"), "dimensions")
                if dims[0] <= 0:
                    raise ValueError("width must be positive")
                uuid = str(el.get("identifier") or f"{kind}{i}")
                parent = el.get("parentIdentifier")
                kwargs: dict[str, Any] = dict(
                    id=_short_id(kind[0], uuid, used_ids), position=to_plan(m[:3, 3]), width=float(dims[0]),
                    wall_id=wall_by_uuid.get(str(parent)) if parent else None, confidence=_confidence(el),
                    metadata={"roomplan_id": uuid, "height": float(dims[1])},
                )
                if cls is Door:
                    try:
                        _, payload = enum_case(el.get("category"))
                        if isinstance(payload.get("isOpen"), bool):
                            kwargs["is_open"] = payload["isOpen"]
                    except ValueError:
                        pass
                out.append(cls(**kwargs))
            except (ValueError, TypeError, AttributeError) as exc:
                bad(path, exc)
        return out

    doors = gaps("doors", Door)
    openings = gaps("openings", Opening)
    windows = gaps("windows", Window)

    # ---- floors -> room outlines
    floor_polys: list[list[Point2D]] = []
    for i, el in enumerate(elements["floors"]):
        try:
            m = decode_matrix(el.get("transform"))
            corners = el.get("polygonCorners") or []
            if len(corners) >= 3:
                local = [decode_vec3(c, "polygonCorners") for c in corners]
            else:
                dims = decode_vec3(el.get("dimensions"), "dimensions")
                hw, hd = dims[0] / 2, dims[1] / 2
                local = [np.array(p) for p in ((-hw, -hd, 0), (hw, -hd, 0), (hw, hd, 0), (-hw, hd, 0))]
            poly = [to_plan(apply(m, tuple(c))) for c in local]
            if _polygon_area(poly) > 0.25:
                floor_polys.append(poly)
        except (ValueError, TypeError, AttributeError) as exc:
            bad(f"floors[{i}]", exc)

    # ---- sections (room-type guesses) name the floor they sit in
    sections: list[tuple[str, Point2D]] = []
    for i, el in enumerate(elements["sections"]):
        try:
            label, _ = enum_case(el.get("label"))
            sections.append((label, to_plan(decode_vec3(el.get("center"), "center"))))
        except (ValueError, TypeError, AttributeError) as exc:
            bad(f"sections[{i}]", exc)

    # A floor outline only takes a section's name when that is the only kind of area inside it;
    # one floor often spans several areas (an apartment with bedrooms and a bathroom).
    rooms: list[Room] = []
    for n, poly in enumerate(floor_polys, start=1):
        inside = {lbl for lbl, c in sections if _point_in(c, poly)}
        guess = SECTION_NAMES.get(next(iter(inside))) if len(inside) == 1 else None
        rooms.append(Room(
            id=f"r_{n}",
            name=f"{guess} (unconfirmed)" if guess else f"Room {n}",
            polygon=poly,
            description="Room type guessed by RoomPlan; please confirm or rename." if guess else "",
        ))

    # Each recognized section also becomes a named area at its center, so several areas
    # sharing one floor can still be told apart and asked about.
    landmarks: list[Landmark] = []
    seen: Counter[str] = Counter()
    for lbl, center in sections:
        if lbl not in SECTION_NAMES:
            continue
        seen[lbl] += 1
        label = SECTION_NAMES[lbl] + (f" {seen[lbl]}" if seen[lbl] > 1 else "")
        landmarks.append(Landmark(
            id=_short_id("lm_area", f"{lbl}{seen[lbl]}", used_ids), name=f"{label} (unconfirmed)",
            type=LandmarkType.room, position=center, source="detected",
            description=f"RoomPlan guessed this area is a {SECTION_NAMES[lbl].lower()}. Confirm or rename it.",
        ))

    # ---- objects
    objects: list[MapObject] = []
    for i, el in enumerate(elements["objects"]):
        try:
            m = decode_matrix(el.get("transform"))
            dims = decode_vec3(el.get("dimensions"), "dimensions")
            category, _ = enum_case(el.get("category"))
            uuid = str(el.get("identifier") or f"object{i}")
            obj = MapObject(
                id=_short_id("o", uuid, used_ids), category=category, position=to_plan(m[:3, 3]),
                width=max(float(dims[0]), 0.01), depth=max(float(dims[2]), 0.01), height=float(dims[1]) or None,
                rotation=round(plan_angle(m), 6), label=_humanize(category), confidence=_confidence(el),
                metadata={"roomplan_id": uuid},
            )
            objects.append(obj)
            if category == "stairs":
                landmarks.append(Landmark(
                    id=_short_id("lm", uuid, used_ids), name="Stairs", type=LandmarkType.stairs,
                    position=obj.position, source="detected",
                    description="RoomPlan detected stairs here. Confirm before relying on it.",
                ))
        except (ValueError, TypeError, AttributeError) as exc:
            bad(f"objects[{i}]", exc)

    if problems:
        warnings.append(f"Skipped {len(problems)} element(s) that could not be read: " + "; ".join(problems[:5])
                        + ("…" if len(problems) > 5 else ""))

    synthetic = bool(data.get("_touchspace_synthetic"))
    version = data.get("version")
    story = data.get("story") if isinstance(data.get("story"), int) else (Counter(stories).most_common(1)[0][0] if stories else None)
    source = SourceInfo(
        kind="synthetic" if synthetic else "roomplan",
        description=(str(data.get("_touchspace_description") or "Synthetic data in RoomPlan format.") if synthetic
                     else f"Apple RoomPlan export{f' (format version {version})' if version is not None else ''}."),
        importer_version=IMPORTER_VERSION,
    )
    fmap = FloorMap(
        id="import-pending",
        name=name or ("Synthetic RoomPlan scan" if synthetic else "RoomPlan scan"),
        source=source, floor_level=story, walls=walls, doors=doors, openings=openings, windows=windows,
        objects=objects, rooms=rooms, landmarks=landmarks,
    )
    if not doors and not openings:
        warnings.append("RoomPlan found no doors or openings. Add them in the editor, or the tactile map will be a closed box.")
    warnings.append("RoomPlan does not identify entrances, exits or restrooms. Mark them in the floor-plan editor.")
    return fmap, warnings


def _polygon_area(poly: list[Point2D]) -> float:
    return abs(sum(p.x * q.y - q.x * p.y for p, q in zip(poly, poly[1:] + poly[:1]))) / 2


def _point_in(p: Point2D, poly: list[Point2D]) -> bool:
    inside = False
    for a, b in zip(poly, poly[1:] + poly[:1]):
        if (a.y > p.y) != (b.y > p.y) and p.x < a.x + (p.y - a.y) * (b.x - a.x) / (b.y - a.y):
            inside = not inside
    return inside
