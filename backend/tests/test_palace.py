"""Integrity checks for the hand-traced venue geometry and both delivery paths."""
from pathlib import Path

from shapely.geometry import LineString, Point, Polygon

from app.models import FloorMap
from app.services.floorplan import validate_map

ROOT = Path(__file__).resolve().parents[2]


def test_palace_trace_has_valid_rooms_and_usable_door_gaps():
    raw = (ROOT / 'sample-data/palace-of-fine-arts.json').read_text()
    assert raw == (ROOT / 'frontend/standalone/maps/palace-of-fine-arts.json').read_text()
    m = FloorMap.model_validate_json(raw)
    assert not validate_map(m)
    # Calibrated to the printed plan dimension, not the old OSM auditorium span.
    northings = [p.y for w in m.walls for p in (w.start, w.end)]
    assert 208 < max(northings) - min(northings) < 210
    shell = Polygon([p.as_tuple() for p in m.rooms[-1].polygon])
    for room in m.rooms:
        polygon = Polygon([p.as_tuple() for p in room.polygon])
        assert polygon.is_valid and polygon.area > 0, room.id
        # Sub-pixel tracing differences are acceptable; no meaningful spill.
        assert polygon.difference(shell).area < 0.1, room.id
    for door in m.doors:
        wall = m.wall_by_id(door.wall_id)
        line = LineString([wall.start.as_tuple(), wall.end.as_tuple()])
        point = Point(door.position.as_tuple())
        assert line.distance(point) < 0.002, door.id
        offset = line.project(point)
        assert offset >= door.width / 2 - 0.002, door.id
        assert offset + door.width / 2 <= line.length + 0.002, door.id
    for i in range(1, 8):
        room = next(r for r in m.rooms if r.id == f"r_breakout{i}")
        landmark = next(l for l in m.landmarks if l.id == f"lm_breakout{i}")
        assert Polygon([p.as_tuple() for p in room.polygon]).contains(
            Point(landmark.position.as_tuple())
        ), landmark.id
