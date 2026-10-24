from __future__ import annotations

import math

import pytest

from app.models import FloorMap, Point2D
from app.services.floorplan import (
    FloorPlanError,
    attach_gaps_to_walls,
    dominant_angle,
    process_map,
    snap_wall_endpoints,
    validate_map,
)
from tests.conftest import rect_room


def _wall_dirs(fmap: FloorMap) -> list[float]:
    return [math.degrees(w.angle) % 180 for w in fmap.walls]


def test_rectangular_room_produces_expected_walls():
    result = process_map(rect_room(6, 4))
    m = result.map
    assert len(m.walls) == 4
    assert m.bounds is not None
    assert m.bounds.min_x == pytest.approx(0) and m.bounds.min_y == pytest.approx(0)
    assert m.bounds.width == pytest.approx(6) and m.bounds.depth == pytest.approx(4)
    lengths = sorted(round(w.length, 6) for w in m.walls)
    assert lengths == [4, 4, 6, 6]
    assert not [i for i in result.issues if i.severity == "error"]


@pytest.mark.parametrize("angle", [17.0, 30.0, -38.0, 63.0])
def test_rotated_walls_are_squared_to_the_page(angle):
    m = process_map(rect_room(6, 4, rotation_deg=angle, origin=(5.0, -3.0))).map
    for d in _wall_dirs(m):
        assert min(abs(d - 0), abs(d - 90), abs(d - 180)) < 1e-6
    dims = sorted([m.bounds.width, m.bounds.depth])
    assert dims == pytest.approx([4, 6])
    # Door must follow its wall through the rotation.
    door = m.doors[0]
    wall = m.wall_by_id(door.wall_id)
    assert wall is not None
    cross = abs((wall.end.x - wall.start.x) * (door.position.y - wall.start.y)
                - (wall.end.y - wall.start.y) * (door.position.x - wall.start.x)) / wall.length
    assert cross < 1e-6


def test_dominant_angle_ignores_quarter_turns():
    m = rect_room(6, 4, rotation_deg=20)
    assert math.degrees(dominant_angle(m.walls)) == pytest.approx(20, abs=1e-6)
    m = rect_room(6, 4, rotation_deg=110)  # same orientation family as 20°
    assert math.degrees(dominant_angle(m.walls)) == pytest.approx(20, abs=1e-6)


def test_dominant_angle_follows_majority_of_wall_length():
    m = rect_room(10, 6, rotation_deg=2.0)  # 32 m of wall at 2°
    m.walls.append(m.walls[0].model_copy(update={
        "id": "w_odd", "start": Point2D(x=1, y=1),
        "end": Point2D(x=1 + 8 * math.cos(math.radians(-3)), y=1 + 8 * math.sin(math.radians(-3)))}))
    assert math.degrees(dominant_angle(m.walls)) == pytest.approx(2.0, abs=1e-6)


def test_snapping_closes_small_corner_gaps():
    m = rect_room(6, 4, door=False)
    m.walls[1].start = Point2D(x=6.07, y=0.05)  # scanner left the SE corner slightly open
    moved = snap_wall_endpoints(m, tolerance=0.12)
    assert moved >= 2
    assert m.walls[0].end == m.walls[1].start


def test_snapping_extends_t_junction():
    m = rect_room(6, 4, door=False)
    m.walls.append(m.walls[0].model_copy(update={"id": "w_part", "start": Point2D(x=3, y=0.08), "end": Point2D(x=3, y=4)}))
    snap_wall_endpoints(m, tolerance=0.12)
    part = m.wall_by_id("w_part")
    assert part.start.y == pytest.approx(0, abs=1e-9) and part.start.x == pytest.approx(3)


def test_door_without_wall_is_attached_to_nearest_wall():
    m = rect_room(6, 4)
    m.doors[0].wall_id = None
    m.doors[0].position = Point2D(x=2.0, y=0.1)
    issues = attach_gaps_to_walls(m, tolerance=0.35)
    assert not issues
    assert m.doors[0].wall_id == "w0"
    assert m.doors[0].position.y == pytest.approx(0)


def test_far_door_is_reported_not_attached():
    m = rect_room(6, 4)
    m.doors[0].wall_id = None
    m.doors[0].position = Point2D(x=3.0, y=2.0)
    issues = attach_gaps_to_walls(m, tolerance=0.35)
    assert [i.code for i in issues] == ["gap_not_on_wall"]
    assert m.doors[0].wall_id is None


def test_map_without_walls_is_rejected():
    m = FloorMap.model_validate({"id": "x", "name": "Empty", "source": {"kind": "manual"}})
    with pytest.raises(FloorPlanError):
        process_map(m)


def test_validation_catches_broken_references(demo_map):
    demo_map.navigation.edges[0].b = "n_nowhere"
    demo_map.landmarks[0].nav_node_id = "n_missing"
    demo_map.doors[0].wall_id = "w_missing"
    codes = {i.code for i in validate_map(demo_map) if i.severity == "error"}
    assert {"missing_node", "missing_wall"} <= codes


def test_demo_map_is_valid_and_already_clean(demo_map):
    result = process_map(demo_map)
    assert not [i for i in result.issues if i.severity in ("error", "warning")]
    assert result.steps == []  # synthetic plan is already square and at the origin
    assert result.map.source.synthetic
    assert result.map.bounds.width == pytest.approx(16) and result.map.bounds.depth == pytest.approx(10)
