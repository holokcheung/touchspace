"""Live DotPad bridge: phone messages -> plan/pose -> pins -> DotPad (mock)."""

import json
import math
import time
from pathlib import Path

import pytest

pytest.importorskip("dotpad_sdk", reason="install ../dotpad-sdk into the backend venv")

from dotpad_sdk import DotPad, Geometry, MockBackend, unpack_graphics  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.live.__main__ import test_pattern as make_test_pattern  # noqa: E402
from app.live.fake_phone import growing_rooms, ios_geometry, world_transform  # noqa: E402
from app.live.output import DotPadOutput, Scene, pack  # noqa: E402
from app.live.render import WALKER_PIN, braille_cells, compass_name, render, status_text  # noqa: E402
from app.live.scene import (  # noqa: E402
    Plan, Pose, plan_from_message, plan_from_roomplan, pose_from_message, pose_from_world_transform, wall_pieces,
)
from app.live.server import LiveState, create_app  # noqa: E402
from app.models.map import FloorMap  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
ROOMPLAN = json.loads((REPO / "sample-data/synthetic-roomplan-capturedroom.json").read_text())
DEMO = json.loads((REPO / "sample-data/demo-building.json").read_text())

BOX = Plan(
    name="Box",
    walls=[((0, 0), (6, 0)), ((6, 0), (6, 4)), ((6, 4), (0, 4)), ((0, 4), (0, 0))],
    gaps=[((2.5, 0), (3.5, 0))],
    rooms=[("Kitchen", [(0, 0), (6, 0), (6, 4), (0, 4)])],
)


@pytest.mark.parametrize("heading", [0, 0.7, math.pi / 2, -2.5, math.pi])
def test_world_transform_round_trip(heading):
    pose = pose_from_world_transform(world_transform(1.5, -2.25, heading))
    assert pose.x == pytest.approx(1.5) and pose.y == pytest.approx(-2.25)
    assert math.cos(pose.heading - heading) == pytest.approx(1)


def test_heading_matches_ios_convention():
    # Camera looking down world -Z (its +Z column points to +Z) faces plan up: heading 0.
    ident = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 2, 1.4, -3, 1]
    pose = pose_from_world_transform(ident)
    assert (pose.x, pose.y, pose.heading) == pytest.approx((2, 3, 0))
    # Turned to face world +X: camera +Z column = (-1, 0, 0) -> heading +90 degrees (east).
    east = [0, 0, 1, 0, 0, 1, 0, 0, -1, 0, 0, 0, 0, 0, 0, 1]
    assert pose_from_world_transform(east).heading == pytest.approx(math.pi / 2)
    assert compass_name(math.pi / 2) == "E"


def test_map_pose_flips_z():
    pose = pose_from_message({"type": "pose", "frame": "map", "x": 1, "z": -4, "heading": 0.3})
    assert (pose.x, pose.y, pose.heading) == (1, 4, 0.3)
    assert pose_from_message({"frame": "none"}) is None
    with pytest.raises(ValueError):
        pose_from_message({"frame": "map", "x": "a", "z": 0, "heading": 0})


def test_wall_pieces_cut_doorways():
    pieces = wall_pieces(((0, 0), (6, 0)), BOX.gaps)
    assert [(round(a[0], 3), round(b[0], 3)) for a, b in pieces] == [(0, 2.5), (3.5, 6)]
    # A door on another wall leaves this one whole.
    assert len(wall_pieces(((6, 0), (6, 4)), BOX.gaps)) == 1


def test_render_box_with_door_and_walker():
    grid = render(BOX, Pose(3, 2, 0))
    raised = grid.raised()
    assert sum(map(sum, raised)) > 100
    bottom = max(r for r in range(grid.rows) if sum(raised[r]) > 30)
    gap = [c for c in range(5, 55) if not raised[bottom][c]]
    assert len(gap) >= 2  # a finger finds the doorway
    walker = [(c, r) for r in range(grid.rows) for c in range(grid.cols) if grid.pins[r][c] == WALKER_PIN]
    assert len(walker) == 5
    cx = sum(c for c, _ in walker) / 5
    assert abs(cx - 29.5) < 2


def test_walker_past_the_scan_stays_on_display():
    grid = render(BOX, Pose(20, 2, 0))
    assert any(p == WALKER_PIN for row in grid.pins for p in row)


def test_empty_scene_is_flat():
    assert not any(map(any, render(None, None).raised()))


def test_status_line():
    assert status_text(BOX, Pose(1, 1, math.pi / 2), live=False) == "Kitchen E"
    assert status_text(BOX, Pose(9, 9, 0), live=False) == "off map N"
    assert status_text(None, None, live=True) == "scanning"
    long = Plan(name="x", rooms=[("A very long room name indeed", BOX.rooms[0][1])])
    text = status_text(long, Pose(1, 1, math.pi), live=False)
    assert text.endswith(" S") and len(braille_cells(text).rstrip(b"\0")) <= 20


def test_braille_cells():
    assert braille_cells("lobby e").hex() == "071503033d001100000000000000000000000000"
    assert braille_cells("room 12")[:7] == bytes([0x17, 0x15, 0x15, 0x0D, 0, 0x3C, 0x01]) and braille_cells("room 12")[7] == 0x03


def test_bit_orders_differ_on_the_probe_pin():
    g = Geometry()
    pins = [[False] * 60 for _ in range(40)]
    pins[3][0] = True  # bottom-left pin of the first cell
    assert pack(pins, g, "graphic")[0] == 0x08
    assert pack(pins, g, "braille")[0] == 0x40
    tp = make_test_pattern()
    assert pack(tp, g)[1 * 30 + 2] == 0x08  # docs/live-dotpad.md: the probe cell


def test_roomplan_scan_and_early_updates():
    plan = plan_from_roomplan(ROOMPLAN)
    assert len(plan.walls) == 4 and len(plan.gaps) == 2 and plan.rooms
    assert plan_from_roomplan({"walls": []}).walls == []
    stages = list(growing_rooms(ROOMPLAN))
    assert [len(plan_from_roomplan(s).walls) for s in stages] == [1, 2, 3, 4]


def test_ios_geometry_message_matches_floormap():
    fmap = FloorMap.model_validate(DEMO)
    geometry, doors = ios_geometry(fmap)
    plan = plan_from_message({"type": "map", "geometry": geometry, "doors": doors})
    direct = plan_from_message({"type": "map", "floormap": DEMO})
    assert render(plan, None).raised() == render(Plan(direct.name, direct.walls, direct.gaps, direct.rooms), None).raised()


def _wait(pred, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def mock_output():
    pad = DotPad(MockBackend())
    out = DotPadOutput(pad, min_interval=0).start()
    yield out
    out.stop()


def test_live_state_drives_the_pad(mock_output):
    state = LiveState(mock_output)
    state.handle({"type": "map", "floormap": DEMO})
    state.handle({"type": "pose", "frame": "plan", "x": 8, "y": 9, "heading": 0})
    assert _wait(lambda: mock_output.frames_sent >= 1 and any(map(any, unpack_graphics(bytes.fromhex(mock_output.pad.snapshot()["graphics_hex"])))))
    assert _wait(lambda: mock_output.pad.snapshot()["braille_hex"] != "00" * 20)
    state.pose_at -= 10
    state.expire_pose()
    assert state.pose is None


def test_websocket_token_status_and_errors(mock_output):
    app = create_app(LiveState(mock_output), token="abc123")
    client = TestClient(app)
    with pytest.raises(Exception):
        with client.websocket_connect("/phone?token=nope") as ws:
            ws.receive_json()
    with client.websocket_connect("/phone?token=abc123") as ws:
        assert ws.receive_json()["type"] == "status"
        ws.send_text("{oops")
        assert ws.receive_json()["type"] == "error"
        ws.send_text(json.dumps({"type": "map", "room": ROOMPLAN, "live": True}))
        ws.send_text(json.dumps({"type": "pose", "frame": "world", "transform": world_transform(3, 6, 0)}))
        status = None
        for _ in range(5):
            msg = ws.receive_json()
            if msg["type"] == "status" and msg["walls"]:
                status = msg
                break
        assert status and status["walls"] == 4 and status["has_pose"]
    assert client.get("/status").json()["map"] == "Live scan"


def test_walking_outside_the_scan_rescales_in_steps():
    from app.live.render import WALL
    walls = lambda g: [[p == WALL for p in row] for row in g.pins]  # noqa: E731
    # Same scale while walking 20 cm outside the scan: the walls stay put.
    assert walls(render(BOX, Pose(7.1, 2, 0))) == walls(render(BOX, Pose(7.3, 2, 0)))
