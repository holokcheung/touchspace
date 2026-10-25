from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest
import trimesh
from shapely.geometry import Point
from shapely.ops import unary_union

from app.models import FloorMap

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_PATH = REPO_ROOT / "sample-data" / "demo-building.json"


@pytest.fixture
def demo_map() -> FloorMap:
    return FloorMap.model_validate(json.loads(DEMO_PATH.read_text()))


def rect_room(width: float, depth: float, *, rotation_deg: float = 0.0, origin: tuple[float, float] = (0.0, 0.0),
              door: bool = True, landmarks: bool = True) -> FloorMap:
    """A single rectangular room, optionally rotated about `origin`, with a door in the south wall."""
    a = math.radians(rotation_deg)

    def p(x: float, y: float) -> dict:
        return {"x": origin[0] + x * math.cos(a) - y * math.sin(a), "y": origin[1] + x * math.sin(a) + y * math.cos(a)}

    corners = [(0, 0), (width, 0), (width, depth), (0, depth)]
    walls = [{"id": f"w{i}", "start": p(*corners[i]), "end": p(*corners[(i + 1) % 4]), "thickness": 0.15} for i in range(4)]
    data: dict = {
        "id": "rect", "name": "Test Room", "source": {"kind": "synthetic"}, "walls": walls,
        "rooms": [{"id": "r1", "name": "Room", "polygon": [p(*c) for c in corners]}],
    }
    if door:
        data["doors"] = [{"id": "d1", "position": p(width / 2, 0), "width": 1.0, "wall_id": "w0"}]
    if landmarks:
        data["landmarks"] = [
            {"id": "lm_in", "name": "Front Door", "type": "entrance", "position": p(width / 2, 0.5)},
            {"id": "lm_wc", "name": "Restroom", "type": "restroom", "position": p(width * 0.8, depth * 0.8)},
        ]
    return FloorMap.model_validate(data)


def section_at(mesh: trimesh.Trimesh, z: float):
    """Horizontal cross-section of the mesh at height z, as one shapely geometry in mesh XY."""
    sec = mesh.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1])
    if sec is None:
        return Point(0, 0).buffer(0)
    planar, _ = sec.to_2D(to_2D=np.eye(4))
    return unary_union(list(planar.polygons_full))


@pytest.fixture(autouse=True)
def _no_real_external_calls():
    """Tests never call Claude, even if a developer's .env has a key. Tests that need it inject a fake."""
    from app.main import app, get_interpreter
    from app.services.claude_interpreter import ClaudeConfig, ClaudeInterpreter

    app.dependency_overrides[get_interpreter] = lambda: ClaudeInterpreter(ClaudeConfig(api_key=None, model="test"))
    yield
    app.dependency_overrides.pop(get_interpreter, None)
