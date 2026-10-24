"""Step 1: RoomPlan JSON -> simple Python objects.

This is the ONLY file that knows the JSON format.

Verified against a RoomPlan export (version 2):
  * "dimensions" is [x, y, z] in metres. Local x = along the surface, y = height.
  * "transform" is 16 floats, column-major. Indices 12, 13, 14 hold the position.
  * "category" looks like {"door": {"isOpen": false}}.
  * "sections" holds room labels such as "bedroom" or "bathroom" with a centre point.

Floor-plan coordinates: RoomPlan is right-handed with y up. Seen from above, x points
right and z points toward the viewer, so the map uses (x, -z). Using (x, z) directly
would produce a mirror image, which is dangerous for a tactile map.
"""
import json
from dataclasses import dataclass
import numpy as np


@dataclass
class Surface:
    kind: str           # "wall", "door", "window", "opening", or an object type
    width: float        # metres, along local x
    depth: float        # metres, along local z (used for objects)
    center: np.ndarray  # (x, y) on the map plane, metres
    axis: np.ndarray    # unit vector of local x on the map plane
    story: int = 0      # floor number in multi-floor scans


@dataclass
class Section:
    label: str          # e.g. "bedroom", "bathroom", "unidentified"
    center: np.ndarray  # (x, y) on the map plane, metres
    story: int = 0


@dataclass
class Room:
    walls: list
    doors: list         # doors and openings, both become gaps in walls
    windows: list
    objects: list
    sections: list


def _category_name(cat):
    """{"door": {...}} -> "door". Empty or missing categories become "unknown"."""
    if isinstance(cat, dict):
        return next(iter(cat), "unknown")
    if cat is None or cat == "":
        return "unknown"
    return str(cat)


def _story(value):
    """Floor number. Anything that is not a whole number counts as floor 0."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _to_map(x, z):
    return np.array([x, -z], dtype=float)


def _flat16(t):
    """Transform as 16 numbers. A nested 4x4 list is flattened row by row."""
    a = np.asarray(t, dtype=float)
    if a.shape == (4, 4):
        a = a.reshape(16)
    if a.shape != (16,):
        raise ValueError(f"Unexpected transform shape {a.shape}")
    return a


def _layout_of(flat):
    """Which way 16 numbers are stored, judged from where the position (and the 1) sit.
    Column-major (Apple): position at 12,13,14 and zeros at 3,7,11.
    Row-major (some other tools): position at 3,7,11 and zeros at 12,13,14.
    Returns "col", "row", or None when it cannot tell (position is exactly 0,0,0)."""
    col = abs(flat[15] - 1) < 1e-6 and np.allclose(flat[[3, 7, 11]], 0)
    row = abs(flat[15] - 1) < 1e-6 and np.allclose(flat[[12, 13, 14]], 0)
    if col and not row:
        return "col"
    if row and not col:
        return "row"
    return None


def _matrix(t, layout="col"):
    flat = _flat16(t)
    m = flat.reshape(4, 4)
    return m.T if layout == "col" else m     # always return a normal row-major matrix


def _surface(item, kind=None, layout="col"):
    """Convert one JSON item. Returns None (with a printed reason) if the item is unusable,
    so one broken entry never takes down the whole map."""
    name = kind or _category_name(item.get("category", "unknown"))
    try:
        m = _matrix(item["transform"], layout)
        dims = [float(v) for v in item["dimensions"]]
    except (KeyError, ValueError, TypeError) as e:
        print(f"  skipped {name}: unreadable transform or dimensions ({e})")
        return None
    if not (np.all(np.isfinite(m)) and np.all(np.isfinite(dims))):
        print(f"  skipped {name}: contains NaN or infinite numbers")
        return None
    axis = _to_map(m[0, 0], m[2, 0])
    n = np.linalg.norm(axis)
    if n < 1e-6:
        print(f"  skipped {name}: its direction is undefined (lies flat or is degenerate)")
        return None
    if item.get("curve"):
        print(f"  warning: {name} is curved; drawn as a straight wall between its ends")
    return Surface(
        kind=name,
        width=dims[0],
        depth=dims[2],
        center=_to_map(m[0, 3], m[2, 3]),
        axis=axis / n,
        story=_story(item.get("story", 0)),
    )


def _all(data, key, kind=None, layout="col"):
    return [s for s in (_surface(i, kind, layout) for i in data.get(key, []) or [])
            if s is not None]


KEYS = ("walls", "doors", "openings", "windows", "objects", "sections")


def _merge_rooms(rooms):
    """Several room dictionaries -> one dictionary with all their lists joined."""
    merged = {k: [] for k in KEYS}
    for r in rooms:
        if isinstance(r, dict):
            for k in KEYS:
                merged[k] += r.get(k, []) or []
    return merged


def _detect_layout(data):
    votes = {"col": 0, "row": 0}
    for k in ("walls", "doors", "openings", "windows", "objects"):
        for item in data.get(k, []) or []:
            try:
                v = _layout_of(_flat16(item["transform"]))
            except (KeyError, ValueError, TypeError):
                continue
            if v:
                votes[v] += 1
    if votes["row"] > votes["col"]:
        print("  note: transforms are stored row by row (not Apple's usual order); reading them that way")
        return "row"
    return "col"


def load_room(path, story=None):
    """Read a RoomPlan JSON file.
    story: which floor to draw. None = the floor with the most walls."""
    # utf-8-sig: reads plain UTF-8 and also files saved with a BOM (Windows Notepad does that).
    # Without an explicit encoding, Windows would use the local code page and fail on non-ASCII.
    with open(path, encoding="utf-8-sig") as f:
        data = json.load(f)
    if isinstance(data, list):                       # a list of rooms
        print(f"  note: file holds {len(data)} rooms; drawing them together")
        data = _merge_rooms(data)
    elif isinstance(data, dict) and not data.get("walls") and isinstance(data.get("rooms"), list):
        print(f"  note: walls are inside {len(data['rooms'])} rooms; drawing them together")
        data = _merge_rooms(data["rooms"])
    if not isinstance(data, dict):
        raise ValueError("This file is not a RoomPlan scan (no walls list found).")
    layout = _detect_layout(data)
    walls = _all(data, "walls", "wall", layout)
    doors = _all(data, "doors", "door", layout) + _all(data, "openings", "opening", layout)
    windows = _all(data, "windows", "window", layout)
    objects = _all(data, "objects", None, layout)
    sections = []
    for s in data.get("sections", []) or []:
        c = s.get("center")
        try:
            ok = c is not None and len(c) == 3 and all(np.isfinite(np.asarray(c, dtype=float)))
        except (TypeError, ValueError):
            ok = False
        if ok:
            sections.append(Section(str(s.get("label", "unidentified")), _to_map(c[0], c[2]),
                                    _story(s.get("story", 0))))

    stories = sorted({w.story for w in walls})
    if len(stories) > 1:
        if story is None:
            story = max(stories, key=lambda st: sum(w.story == st for w in walls))
        print(f"  note: scan has floors {stories}; drawing floor {story} only")
    if story is not None:
        keep = lambda items: [i for i in items if i.story == story]
        walls, doors, windows, objects, sections = (keep(walls), keep(doors), keep(windows),
                                                    keep(objects), keep(sections))
    return Room(walls=walls, doors=doors, windows=windows, objects=objects, sections=sections)
