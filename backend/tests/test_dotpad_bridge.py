"""Dot Pad display state rules and the proxy <-> bridge socket."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.dotpad import server
from app.dotpad.raster import Pose
from app.dotpad.state import DisplayState
from app.models.map import FloorMap

ROOT = Path(__file__).resolve().parents[2]
DEMO = FloorMap.model_validate(json.loads((ROOT / "sample-data/demo-building.json").read_text(encoding="utf-8")))


# ---------- state rules from docs/DOTPAD_API.md ----------


def test_blank_until_a_map_arrives():
    s = DisplayState("d")
    assert s.frame_hex() == "00" * 300


def test_zoom_steps_and_clamps():
    s = DisplayState("d")
    s.set_map(DEMO)
    for want in (2, 4, 8, 8):
        s.zoom_in()
        assert s.zoom == want
    for want in (4, 2, 1, 1):
        s.zoom_out()
        assert s.zoom == want


def test_new_map_resets_zoom_and_pose():
    s = DisplayState("d")
    s.set_map(DEMO)
    s.zoom_in()
    s.set_pose(Pose(4, 3, 0))
    s.set_map(DEMO)
    assert (s.zoom, s.pose, s.center) == (1, None, None)


def test_lost_pose_hides_marker_but_keeps_viewport():
    s = DisplayState("d")
    s.set_map(DEMO)
    s.zoom_in()
    s.set_pose(Pose(4, 3, 0))
    shown = s.frame_hex()
    s.set_pose(None)
    assert s.center == (4, 3)
    assert s.frame_hex() != shown  # marker gone, same viewport


def test_board_size_drives_frame_length():
    s = DisplayState("d")
    s.set_map(DEMO)
    s.set_board(20, 6)
    assert len(s.frame_hex()) == 2 * 20 * 6


# ---------- socket ----------


@pytest.fixture
def client():
    server.hub.states.clear()
    server.hub.bridges.clear()
    return TestClient(server.app)


def test_bridge_gets_frame_then_redraws_on_board_and_keys(client):
    r = client.post("/v1/dev/displays/d1/fixture", json={"mapPath": "demo-building.json"})
    assert r.status_code == 200
    with client.websocket_connect("/v1/bridge/d1") as ws:
        first = ws.receive_json()
        assert first["type"] == "frame" and first["zoom"] == 1 and len(first["hex"]) == 600

        ws.send_json({"type": "device", "state": "connected", "cellCols": 30, "cellRows": 10})
        assert ws.receive_json()["cellCols"] == 30

        ws.send_json({"type": "key", "key": "KeyFunction1"})
        assert ws.receive_json()["zoom"] == 2
        ws.send_json({"type": "key", "key": "KeyFunction2"})
        assert ws.receive_json()["zoom"] == 1


def test_fixture_with_pose_pushes_to_attached_bridge(client):
    client.post("/v1/dev/displays/d2/fixture", json={"mapPath": "demo-building.json"})
    with client.websocket_connect("/v1/bridge/d2") as ws:
        ws.receive_json()
        r = client.post(
            "/v1/dev/displays/d2/fixture", json={"pose": {"x": 4, "y": 3, "headingDeg": 90}}
        )
        assert r.json()["bridgeAttached"] is True
        assert ws.receive_json()["type"] == "frame"
    assert "@" in client.get("/v1/dev/displays/d2/preview").text


def test_fixture_path_cannot_escape_sample_data(client):
    r = client.post("/v1/dev/displays/d3/fixture", json={"mapPath": "../backend/pyproject.toml"})
    assert r.status_code == 422


def test_bridge_page_is_served(client):
    r = client.get("/bridge")
    assert r.status_code == 200 and "/bridge/sdk.js" in r.text
