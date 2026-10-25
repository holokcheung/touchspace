"""James's Dot Pad proxy contract (DOTPAD_API.md) on the live bridge, against a mock DotPad."""

import json
import math
import time
from pathlib import Path

import pytest

pytest.importorskip("dotpad_sdk", reason="install ../dotpad-sdk into the backend venv")

from dotpad_sdk import Button, ButtonAction, ButtonEvent, DotPad, MockBackend  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.live.output import DotPadOutput  # noqa: E402
from app.live.v1 import ProxyState, create_router  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
DEMO = json.loads((REPO / "sample-data/demo-building.json").read_text())
AUTH = {"Authorization": "Bearer tok"}


@pytest.fixture
def env():
    pad = DotPad(MockBackend())
    out = DotPadOutput(pad, min_interval=0).start()
    proxy = ProxyState(out, token="tok", display_id="pad-1")
    app = FastAPI()
    app.include_router(create_router(proxy))
    yield TestClient(app), proxy, out
    out.stop()


def make_session(client, mode="live"):
    r = client.post("/v1/sessions", json={"displayId": "pad-1", "mode": mode}, headers=AUTH)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["wsUrl"].startswith("ws://") and body["wsUrl"].endswith(f"/v1/sessions/{body['sessionId']}/stream")
    return body["sessionId"]


def put_map(client, sid, rev="r1", frame="f1", plan=DEMO):
    return client.put(f"/v1/sessions/{sid}/map", json={"mapRevision": rev, "coordinateFrameId": frame, "floorPlan": plan}, headers=AUTH)


def pose(seq, x=8.0, y=9.0, heading=0.0, rev="r1", frame="f1", tracking="valid"):
    p = {"type": "pose", "seq": seq, "mapRevision": rev, "coordinateFrameId": frame, "tracking": tracking,
         "position": {"x": x, "y": y} if tracking == "valid" else None, "headingRad": heading if tracking == "valid" else None}
    return json.dumps(p)


def until(ws, pred, n=20):
    for _ in range(n):
        msg = ws.receive_json()
        if pred(msg):
            return msg
    raise AssertionError("expected message never came")


def test_auth_and_session_errors(env):
    client, _, _ = env
    assert client.post("/v1/sessions", json={"displayId": "pad-1", "mode": "live"}).json()["error"]["code"] == "UNAUTHORIZED"
    r = client.post("/v1/sessions", json={"displayId": "other", "mode": "live"}, headers=AUTH)
    assert (r.status_code, r.json()["error"]["code"]) == (404, "DISPLAY_NOT_FOUND")
    r = client.post("/v1/sessions", json={"displayId": "pad-1", "mode": "fly"}, headers=AUTH)
    assert (r.status_code, r.json()["error"]["code"]) == (422, "INVALID_REQUEST")
    r = put_map(client, "nope")
    assert (r.status_code, r.json()["error"]["code"]) == (404, "SESSION_NOT_FOUND")


def test_map_upload_rules(env):
    client, proxy, _ = env
    sid = make_session(client)
    r = put_map(client, sid)
    assert r.status_code == 200 and r.json() == {"mapRevision": "r1", "coordinateFrameId": "f1", "state": "ready"}
    assert put_map(client, sid).status_code == 200  # same revision, same content: fine
    assert put_map(client, sid, frame="f2").json()["error"]["code"] == "REVISION_CONFLICT"
    bad = dict(DEMO, doors=[dict(DEMO["doors"][0], wall_id="missing")])
    r = put_map(client, sid, rev="r2", plan=bad)
    assert (r.status_code, r.json()["error"]["code"]) == (422, "INVALID_REQUEST")
    assert proxy.session.map_revision == "r1"  # failed upload keeps the old map
    r = put_map(client, sid, rev="r3", plan=dict(DEMO, units="feet"))
    assert r.status_code == 422


def test_stream_pose_flow(env):
    client, proxy, out = env
    sid = make_session(client)
    with client.websocket_connect(f"/v1/sessions/{sid}/stream", headers=AUTH) as ws:
        first = ws.receive_json()
        assert first == {"type": "status", "mapRevision": None, "coordinateFrameId": None, "mapState": "empty",
                         "deviceState": "connected", "zoom": 1, "poseState": "none", "lastAcceptedSeq": None}
        ws.send_text(pose(1))
        assert until(ws, lambda m: m["type"] == "error")["code"] == "MAP_NOT_READY"
        assert put_map(client, sid).status_code == 200
        ws.send_text(pose(1, rev="old"))
        assert until(ws, lambda m: m["type"] == "error")["code"] == "MAP_MISMATCH"
        ws.send_text(pose(2, heading=7.0))
        err = until(ws, lambda m: m["type"] == "error")
        assert (err["code"], err["seq"]) == ("INVALID_REQUEST", 2)  # heading outside [0, 2π)
        ws.send_text(json.dumps({**json.loads(pose(3)), "extra": 1}))
        assert until(ws, lambda m: m["type"] == "error")["code"] == "INVALID_REQUEST"
        ws.send_text(pose(5, heading=math.pi / 2))
        st = until(ws, lambda m: m["type"] == "status" and m["lastAcceptedSeq"] == 5)
        assert st["poseState"] == "valid" and st["mapState"] == "ready"
        ws.send_text(pose(4))  # older: dropped silently
        ws.send_text(pose(6, tracking="lost"))
        st = until(ws, lambda m: m["type"] == "status" and m["lastAcceptedSeq"] == 6)
        assert st["poseState"] == "lost"
        ws.send_text(pose(7))
        until(ws, lambda m: m["type"] == "status" and m["poseState"] == "valid")
        proxy.session.pose_at -= 5
        assert until(ws, lambda m: m["type"] == "status" and m["poseState"] == "stale")["lastAcceptedSeq"] == 7
    assert out.frames_sent >= 1


def test_buttons_zoom_and_busy_display(env):
    client, proxy, out = env
    sid = make_session(client)
    put_map(client, sid)
    with client.websocket_connect(f"/v1/sessions/{sid}/stream?token=tok") as ws:
        ws.receive_json()
        ws.send_text(pose(1))
        until(ws, lambda m: m.get("poseState") == "valid")
        before = out.pad.snapshot()["graphics_hex"]
        for _ in range(4):
            proxy._button(ButtonEvent(Button.FUNCTION_1, ButtonAction.DOWN))
        assert until(ws, lambda m: m.get("zoom") == 8)["zoom"] == 8
        proxy._button(ButtonEvent(Button.FUNCTION_2, ButtonAction.DOWN))
        assert until(ws, lambda m: m.get("zoom") == 4)
        end = time.monotonic() + 2
        while out.pad.snapshot()["graphics_hex"] == before and time.monotonic() < end:
            time.sleep(0.02)
        assert out.pad.snapshot()["graphics_hex"] != before  # zoomed picture differs
        r = client.post("/v1/sessions", json={"displayId": "pad-1", "mode": "live"}, headers=AUTH)
        assert (r.status_code, r.json()["error"]["code"]) == (409, "DISPLAY_BUSY")
    # Stream closed: a restarted app may take the display over.
    assert make_session(client) != sid
    assert client.delete(f"/v1/sessions/{sid}", headers=AUTH).status_code == 404
