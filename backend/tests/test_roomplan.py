from __future__ import annotations

import copy
import importlib.util
import json
import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app, get_store
from app.services.floorplan import process_map
from app.services.importers import detect_format, import_scan
from app.services.roomplan import RoomPlanImportError, decode_matrix, enum_case, import_roomplan
from app.services.storage import MapStore
from app.services.tactile import generate_tactile_model
from tests.conftest import REPO_ROOT

_spec = importlib.util.spec_from_file_location("make_rp", REPO_ROOT / "sample-data" / "scripts" / "make_synthetic_roomplan.py")
make_rp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(make_rp)

FIXTURE_PATH = REPO_ROOT / "sample-data" / "synthetic-roomplan-capturedroom.json"


def _processed(data: dict):
    fmap, warnings = import_roomplan(data)
    return process_map(fmap).map, warnings


# --------------------------------------------------------------------------- decoding


def test_enum_decoding_variants():
    assert enum_case({"wall": {}}) == ("wall", {})
    assert enum_case({"door": {"isOpen": False}}) == ("door", {"isOpen": False})
    assert enum_case("table") == ("table", {})
    with pytest.raises(ValueError):
        enum_case({"a": {}, "b": {}})


def test_transform_is_column_major():
    m = np.eye(4)
    m[:3, 0] = [0, 0, -1]  # some rotation
    m[:3, 3] = [1.5, 2.0, -3.0]  # translation lives in column 3
    flat = list(m.flatten(order="F"))
    assert flat[12:15] == [1.5, 2.0, -3.0]
    np.testing.assert_allclose(decode_matrix(flat), m)
    np.testing.assert_allclose(decode_matrix([list(m[:, i]) for i in range(4)]), m)  # list-of-columns form


def test_bad_transform_is_rejected():
    with pytest.raises(ValueError, match="16 numbers"):
        decode_matrix([1, 2, 3])
    with pytest.raises(ValueError, match="non-finite"):
        decode_matrix([float("nan")] * 16)


# --------------------------------------------------------------------------- geometry


@pytest.mark.parametrize("yaw", [0.0, 23.0, 137.0, -71.0, 180.0])
def test_room_is_recovered_at_any_scan_orientation(yaw):
    m, _ = _processed(make_rp.build(yaw_deg=yaw, shift=(4.2, 0.3, -7.5)))
    assert sorted([m.bounds.width, m.bounds.depth]) == pytest.approx([5.0, 7.0], abs=1e-4)
    for w in m.walls:
        angle = math.degrees(w.angle) % 90
        assert min(angle, 90 - angle) < 1e-3, "walls should be squared to the page"
    door = m.doors[0]
    wall = m.wall_by_id(door.wall_id)
    assert wall is not None and wall.length == pytest.approx(7.0, abs=1e-4)
    along = min(math.dist(door.position.as_tuple(), wall.start.as_tuple()), math.dist(door.position.as_tuple(), wall.end.as_tuple()))
    assert along == pytest.approx(0.3 * 7.0, abs=1e-3)


def test_plan_is_not_mirrored():
    """With no rotation, RoomPlan's -Z must be plan 'up': the north window ends up at the top."""
    fmap, _ = import_roomplan(make_rp.build(yaw_deg=0.0, shift=(0.0, 0.0, 0.0)))
    door, window = fmap.doors[0], fmap.windows[0]
    assert window.position.y == pytest.approx(5.0, abs=1e-4)
    assert door.position.y == pytest.approx(0.0, abs=1e-4)
    storage = next(o for o in fmap.objects if o.category == "storage")
    assert storage.position.x == pytest.approx(6.6, abs=1e-4)  # east side stays east


def test_objects_keep_position_size_and_rotation():
    m, _ = _processed(make_rp.build(yaw_deg=41.0))
    by_cat = {o.category: o for o in m.objects}
    sofa, storage = by_cat["sofa"], by_cat["storage"]
    assert (sofa.width, sofa.depth) == pytest.approx((2.1, 0.9))
    assert sofa.height == pytest.approx(0.85)
    assert (math.degrees(storage.rotation) - math.degrees(sofa.rotation)) % 180 == pytest.approx(90, abs=1e-3)
    assert math.dist(sofa.position.as_tuple(), by_cat["table"].position.as_tuple()) == pytest.approx(math.dist((1.6, 3.9), (3.6, 2.6)), abs=1e-4)
    assert all(not o.include_in_tactile for o in m.objects), "furniture is opt-in"


def test_semantics_are_mapped_conservatively():
    fmap, warnings = import_roomplan(make_rp.build())
    assert fmap.doors[0].is_open is True
    assert fmap.doors[0].wall_id == fmap.walls[0].id  # via parentIdentifier
    assert fmap.windows and fmap.openings
    assert [r.name for r in fmap.rooms] == ["Living room (unconfirmed)"]
    areas = [lm for lm in fmap.landmarks if lm.type.value == "room"]
    assert [a.name for a in areas] == ["Living room (unconfirmed)"] and areas[0].source == "detected"
    assert sum(p.x * q.y - q.x * p.y for p, q in zip(fmap.rooms[0].polygon, fmap.rooms[0].polygon[1:] + fmap.rooms[0].polygon[:1])) / 2 == pytest.approx(35.0, abs=1e-3)
    stairs = [lm for lm in fmap.landmarks if lm.type.value == "stairs"]
    assert len(stairs) == 1 and stairs[0].source == "detected"
    assert not any(lm.type.value in ("entrance", "exit", "restroom") for lm in fmap.landmarks)
    assert fmap.navigation.nodes == [] and fmap.navigation.edges == []
    assert any("does not identify entrances" in w for w in warnings)


def test_synthetic_flag_controls_source_label():
    data = make_rp.build()
    assert import_roomplan(data)[0].source.kind == "synthetic"
    del data["_touchspace_synthetic"]
    fmap, _ = import_roomplan(data)
    assert fmap.source.kind == "roomplan" and "version 2" in fmap.source.description


def test_door_without_parent_is_attached_to_nearest_wall():
    data = make_rp.build()
    data["doors"][0]["parentIdentifier"] = None
    m, _ = _processed(data)
    assert m.doors[0].wall_id is not None


def test_bad_elements_are_skipped_with_a_warning():
    data = make_rp.build()
    data["objects"][0]["transform"] = [1, 2, 3]
    fmap, warnings = import_roomplan(data)
    assert len(fmap.objects) == len(data["objects"]) - 1
    assert any("objects[0]" in w and "16 numbers" in w for w in warnings)


def test_no_usable_walls_is_an_error():
    data = make_rp.build()
    for w in data["walls"]:
        w["transform"] = "garbage"
    with pytest.raises(RoomPlanImportError) as info:
        import_roomplan(data)
    assert "No usable walls" in str(info.value)
    assert any(d.startswith("walls[0]") for d in info.value.details)


def test_captured_structure_with_rooms_is_merged():
    room_a = make_rp.build(yaw_deg=10.0, shift=(0, 0, 0))
    room_b = make_rp.build(yaw_deg=10.0, shift=(8.0, 0, 0))
    structure = {"rooms": [room_a, room_b], "version": 2}
    assert detect_format(structure) == "roomplan"
    fmap, _ = import_roomplan(structure)
    assert len(fmap.walls) == 8 and len(fmap.rooms) == 2


def test_wall_ids_are_unique_even_with_colliding_prefixes():
    data = make_rp.build()
    for w in data["walls"]:
        w["identifier"] = "AAAAAAAA-" + w["identifier"]
    fmap, _ = import_roomplan(data)
    assert len({w.id for w in fmap.walls}) == 4


@pytest.mark.parametrize("seed", range(12))
def test_noisy_scans_still_produce_printable_models(seed):
    """Scanner noise: walls shifted a few cm and slightly mis-sized, arbitrary world yaw."""
    rng = np.random.default_rng(seed)
    data = make_rp.build(yaw_deg=float(rng.uniform(-180, 180)), shift=tuple(rng.uniform(-10, 10, 3)))
    for w in data["walls"]:
        t = w["transform"]
        t[12] += float(rng.normal(0, 0.03))
        t[14] += float(rng.normal(0, 0.03))
        w["dimensions"][0] += float(rng.normal(0, 0.02))
    m, _ = _processed(data)
    assert sorted([m.bounds.width, m.bounds.depth]) == pytest.approx([5.0, 7.0], abs=0.25)
    mesh, report = generate_tactile_model(m)
    assert all(c.passed for c in report.checks), [c for c in report.checks if not c.passed]


# --------------------------------------------------------------------------- public real-world export

REAL_EXPORT = REPO_ROOT / "sample-data" / "third-party" / "open3dfloorplan-test-roomplan.json"


def test_public_roomplan_export_imports_and_prints():
    """A public CapturedRoom export (see sample-data/third-party/README.md), not synthetic data."""
    data = json.loads(REAL_EXPORT.read_text())
    result = import_scan(data)
    fmap = result.map
    assert result.format == "roomplan" and fmap.source.kind == "roomplan"
    assert (len(fmap.walls), len(fmap.doors), len(fmap.windows), len(fmap.objects)) == (20, 4, 4, 13)
    assert all(d.wall_id for d in fmap.doors), "every door names its wall via parentIdentifier"
    assert {d.is_open for d in fmap.doors} <= {True, False}

    # One floor outline holds two bedrooms, a bathroom and an unidentified area:
    # it must not be named after just one of them.
    assert [r.name for r in fmap.rooms] == ["Room 1"]
    areas = sorted(lm.name for lm in fmap.landmarks if lm.type.value == "room")
    assert areas == ["Bathroom (unconfirmed)", "Bedroom (unconfirmed)", "Bedroom 2 (unconfirmed)"]
    assert not any(lm.type.value == "restroom" for lm in fmap.landmarks), "a bathroom guess is not a confirmed restroom"

    processed = process_map(fmap)
    assert not [i for i in processed.issues if i.severity == "error"]
    m = processed.map
    assert sorted([m.bounds.width, m.bounds.depth]) == pytest.approx([6.54, 7.52], abs=0.05)
    # This scan's walls are not all parallel (one group sits 3-4° off the rest). Alignment must
    # follow the majority of the wall length rather than averaging the groups.
    def off_square(w):
        a = math.degrees(w.angle) % 90
        return min(a, 90 - a)
    squared = sum(w.length for w in m.walls if off_square(w) < 0.5) / sum(w.length for w in m.walls)
    assert squared > 0.6, f"only {squared:.0%} of wall length is within 0.5° of square"
    mesh, report = generate_tactile_model(m)
    assert all(c.passed for c in report.checks)


# --------------------------------------------------------------------------- end to end


def test_fixture_file_matches_generator():
    assert json.loads(FIXTURE_PATH.read_text()) == json.loads(json.dumps(make_rp.build()))


def test_imported_scan_prints(tmp_path):
    result = import_scan(json.loads(FIXTURE_PATH.read_text()))
    assert result.format == "roomplan"
    m = process_map(result.map).map
    m.landmarks  # stairs only; still printable
    mesh, report = generate_tactile_model(m)
    assert all(c.passed for c in report.checks)


def test_upload_roomplan_through_api(tmp_path):
    store = MapStore(tmp_path)
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        r = client.post("/api/scans", files={"file": ("living_room.json", FIXTURE_PATH.read_bytes(), "application/json")})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["processing_steps"][0] == "Read an Apple RoomPlan export."
        assert body["map"]["name"] == "Living Room"
        assert body["map"]["source"]["kind"] == "synthetic"
        assert any(i["code"] == "import_note" for i in body["issues"])
        g = client.post(f"/api/maps/{body['map']['id']}/generate")
        assert g.status_code == 200, g.text
    finally:
        app.dependency_overrides.clear()


def test_broken_roomplan_upload_explains_problem(tmp_path):
    store = MapStore(tmp_path)
    app.dependency_overrides[get_store] = lambda: store
    try:
        data = copy.deepcopy(make_rp.build())
        for w in data["walls"]:
            w["dimensions"] = [0, 2.5, 0]
        r = TestClient(app).post("/api/scans", files={"file": ("x.json", json.dumps(data).encode(), "application/json")})
        assert r.status_code == 422
        err = r.json()["error"]
        assert "No usable walls" in err["message"] and any("width must be positive" in d for d in err["details"])
    finally:
        app.dependency_overrides.clear()
