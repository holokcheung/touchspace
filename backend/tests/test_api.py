from __future__ import annotations

import io
import json
import struct

import pytest
import trimesh
from fastapi.testclient import TestClient

from app.main import app, get_store
from app.services.storage import MapStore
from tests.conftest import DEMO_PATH, rect_room


@pytest.fixture
def client(tmp_path):
    store = MapStore(tmp_path)
    app.dependency_overrides[get_store] = lambda: store
    yield TestClient(app)
    app.dependency_overrides.clear()


def _upload(client: TestClient, content: bytes, filename: str = "scan.json"):
    return client.post("/api/scans", files={"file": (filename, content, "application/json")})


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_upload_valid_map(client):
    data = rect_room(6, 4).model_dump(mode="json")
    r = _upload(client, json.dumps(data).encode(), "kitchen_scan.json")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["map"]["id"].startswith("scan-")
    assert body["map"]["bounds"]["max_x"] == pytest.approx(6)
    assert body["model"]["status"] == "none"
    assert client.get(f"/api/maps/{body['map']['id']}").status_code == 200


def test_upload_invalid_json_is_explained(client):
    r = _upload(client, b'{"walls": [')
    assert r.status_code == 400
    err = r.json()["error"]
    assert err["code"] == "invalid_json" and "line 1" in err["message"]


def test_upload_unrecognized_structure(client):
    r = _upload(client, json.dumps({"hello": "world"}).encode())
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "unsupported_scan"


def test_upload_map_with_bad_fields(client):
    data = rect_room(6, 4).model_dump(mode="json")
    data["walls"][0]["thickness"] = -1
    r = _upload(client, json.dumps(data).encode())
    assert r.status_code == 422
    assert any("thickness" in d for d in r.json()["error"]["details"])


def test_upload_empty_file(client):
    r = _upload(client, b"   ")
    assert r.status_code == 400 and r.json()["error"]["code"] == "empty_file"


def test_demo_generate_and_download(client):
    r = client.post("/api/demo")
    assert r.status_code == 201
    map_id = r.json()["map"]["id"]
    assert r.json()["map"]["source"]["kind"] == "synthetic"

    assert client.get(f"/api/maps/{map_id}/stl").status_code == 404  # nothing generated yet

    g = client.post(f"/api/maps/{map_id}/generate")
    assert g.status_code == 200, g.text
    report = g.json()["report"]
    assert all(c["passed"] for c in report["checks"])

    s = client.get(f"/api/maps/{map_id}/stl")
    assert s.status_code == 200
    assert s.headers["content-type"] == "model/stl"
    assert "touchspace-demo-building-synthetic-map.stl" in s.headers["content-disposition"]
    (count,) = struct.unpack("<I", s.content[80:84])
    assert len(s.content) == 84 + 50 * count and count == report["triangle_count"]
    mesh = trimesh.load(io.BytesIO(s.content), file_type="stl")
    assert mesh.is_watertight
    assert mesh.extents[0] == pytest.approx(report["width_mm"], abs=0.01)


def test_editing_marks_model_stale_and_regenerate_applies_settings(client):
    map_id = client.post("/api/demo").json()["map"]["id"]
    client.post(f"/api/maps/{map_id}/generate")
    fmap = client.get(f"/api/maps/{map_id}").json()["map"]
    assert client.get(f"/api/maps/{map_id}/model").json()["status"] == "ready"

    fmap["landmarks"][0]["name"] = "Front Doors"
    r = client.put(f"/api/maps/{map_id}", json=fmap)
    assert r.status_code == 200
    assert r.json()["map"]["landmarks"][0]["name"] == "Front Doors"
    assert r.json()["model"]["status"] == "stale"

    settings = fmap["tactile"] | {"max_width_mm": 120, "max_depth_mm": 120}
    g = client.post(f"/api/maps/{map_id}/generate", json={"settings": settings})
    assert g.status_code == 200
    assert g.json()["report"]["width_mm"] <= 120
    assert client.get(f"/api/maps/{map_id}/model").json()["status"] == "ready"


def test_put_cannot_relabel_synthetic_data_as_real(client):
    map_id = client.post("/api/demo").json()["map"]["id"]
    fmap = client.get(f"/api/maps/{map_id}").json()["map"]
    fmap["source"] = {"kind": "roomplan", "description": "real scan"}
    r = client.put(f"/api/maps/{map_id}", json=fmap)
    assert r.json()["map"]["source"]["kind"] == "synthetic"


def test_generation_errors_are_reported(client):
    map_id = client.post("/api/demo").json()["map"]["id"]
    fmap = client.get(f"/api/maps/{map_id}").json()["map"]
    fmap["navigation"]["edges"][0]["a"] = "n_missing"
    put = client.put(f"/api/maps/{map_id}", json=fmap)
    assert any(i["severity"] == "error" for i in put.json()["issues"])
    g = client.post(f"/api/maps/{map_id}/generate")
    assert g.status_code == 422 and g.json()["error"]["code"] == "generation_failed"


def test_missing_ids(client):
    for method, path in [("get", "/api/maps/nope-1234"), ("post", "/api/maps/nope-1234/generate"),
                         ("get", "/api/maps/nope-1234/stl"), ("get", "/api/maps/..%2F..%2Fetc")]:
        r = getattr(client, method)(path)
        assert r.status_code == 404, path


def test_put_id_mismatch(client):
    map_id = client.post("/api/demo").json()["map"]["id"]
    fmap = client.get(f"/api/maps/{map_id}").json()["map"]
    fmap["id"] = "other-1234"
    assert client.put(f"/api/maps/{map_id}", json=fmap).status_code == 400


def test_invalid_settings_rejected(client):
    map_id = client.post("/api/demo").json()["map"]["id"]
    r = client.post(f"/api/maps/{map_id}/generate", json={"settings": {"wall_height_mm": -3}})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request"


def test_list_maps(client):
    client.post("/api/demo")
    _upload(client, DEMO_PATH.read_bytes())
    maps = client.get("/api/maps").json()
    assert len(maps) == 2
    assert {m["synthetic"] for m in maps} == {True}


def test_palace_of_fine_arts_sample(client):
    r = client.post("/api/samples/palace-of-fine-arts")
    assert r.status_code == 201, r.text
    m = r.json()["map"]
    assert m["name"] == "Palace of Fine Arts, first floor" and m["source"]["kind"] == "manual"
    assert "OpenStreetMap" in m["source"]["description"]
    names = {lm["name"] for lm in m["landmarks"]}
    assert {"Public entrance", "Business entrance", "Palace Games", "Theater", "Atrium"} <= names
    assert not r.json()["issues"]
    # The main app preserves the north-up trace used by the standalone viewer.
    from tests.conftest import REPO_ROOT
    original = json.loads((REPO_ROOT / "sample-data/palace-of-fine-arts.json").read_text())
    assert len(m["walls"]) == len(original["walls"])
    assert m["walls"][0]["start"] == original["walls"][0]["start"]
    assert m["walls"][0]["end"] == original["walls"][0]["end"]
