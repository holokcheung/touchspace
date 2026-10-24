from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
import trimesh

from app.services.floorplan import process_map
from app.services.roomplan_parser import RoomPlanImportError, parse_roomplan_data
from app.services.tactile import export_stl, generate_tactile_model


REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE = REPO_ROOT / "sample-data" / "roomplan-real-sample.json"


@pytest.fixture
def roomplan_sample() -> dict:
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


def test_public_roomplan_fixture_parses_native_arrays(roomplan_sample):
    fmap = parse_roomplan_data(roomplan_sample)
    assert len(fmap.walls) == 20
    assert len(fmap.doors) == 4
    assert len(fmap.windows) == 4
    assert fmap.openings == []  # the source explicitly has an empty array
    assert len(fmap.objects) == 13
    assert len(fmap.rooms) == 1
    assert fmap.source.kind == "roomplan"
    # The sample is rotated in world space; its first wall is not axis aligned.
    assert abs(fmap.walls[0].angle) > 0.01


def test_transform_applies_translation_and_projects_world_x_minus_z(roomplan_sample):
    fmap = parse_roomplan_data(roomplan_sample)
    chair = fmap.objects[0]
    assert chair.position.x == pytest.approx(2.2686875)
    assert chair.position.y == pytest.approx(6.0977283)
    assert chair.rotation == pytest.approx(3.12055, abs=1e-4)


def test_processed_roomplan_attaches_doors_and_produces_bounds(roomplan_sample):
    result = process_map(parse_roomplan_data(roomplan_sample))
    assert all(door.wall_id for door in result.map.doors)
    assert result.map.bounds is not None
    assert result.map.bounds.width == pytest.approx(7.4417, abs=0.01)
    assert result.map.bounds.depth == pytest.approx(6.4479, abs=0.01)


def test_public_fixture_generates_and_reloads_a_real_stl(roomplan_sample):
    fmap = process_map(parse_roomplan_data(roomplan_sample)).map
    mesh, report = generate_tactile_model(fmap)
    data = export_stl(mesh)
    loaded = trimesh.load(io.BytesIO(data), file_type="stl")
    assert len(loaded.faces) > 0
    assert loaded.is_watertight
    assert report.width_mm <= fmap.tactile.max_width_mm
    assert report.depth_mm <= fmap.tactile.max_depth_mm
    assert all(check.passed for check in report.checks)


def test_invalid_transform_has_element_context(roomplan_sample):
    roomplan_sample["walls"][0]["transform"] = [0, 1, 2]
    with pytest.raises(RoomPlanImportError, match=r"walls\[0\].*16-number"):
        parse_roomplan_data(roomplan_sample)


def test_missing_required_structural_array_is_rejected(roomplan_sample):
    roomplan_sample.pop("doors")
    with pytest.raises(RoomPlanImportError, match="doors"):
        parse_roomplan_data(roomplan_sample)
