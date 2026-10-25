from threading import Event

import pytest

from dotpad_sdk import DotPad, MockBackend, ViewerServer
from conftest import request


def test_viewer_assets_and_state_follow_python(viewer, mock_pad):
    for asset in ("/", "/viewer.css", "/viewer.js", "/pins.js", "/hardware", "/hardware.js"):
        status, body = request(viewer.url + asset)
        assert status == 200
        assert body
    status, html = request(viewer.url)
    assert html.count(b"data-button=") == 6
    assert b'id="graphics"' in html and b'id="braille"' in html
    mock_pad.display_graphics(b"\x08" * 300)
    mock_pad.display_braille(b"\x40")
    status, state = request(viewer.url + "/api/state")
    assert status == 200
    assert state["graphics_hex"] == "08" * 300
    assert state["braille_hex"] == "40" + "00" * 19


def test_mock_buttons_reach_python(viewer, mock_pad):
    done = Event()
    mock_pad.on_button(lambda e: done.set() if e.button.value == "function2" and e.action.value == "down" else None)
    assert request(viewer.url + "/api/buttons", {"button": "function2", "action": "down"})[0] == 200
    assert done.wait(2)
    state = request(viewer.url + "/api/state")[1]
    assert state["pressed"] == ["function2"]
    assert request(viewer.url + "/api/buttons", {"button": "function2", "action": "up"})[0] == 200


def test_demo_clear_refresh_and_atomic_validation(viewer, mock_pad):
    assert request(viewer.url + "/api/mock/demo", {})[0] == 200
    assert any(mock_pad.backend.graphics)
    before = mock_pad.snapshot()
    status, _ = request(viewer.url + "/api/mock/frame", {"graphics_hex": "ff" * 300, "braille_hex": "ff" * 21})
    assert status == 400
    assert mock_pad.snapshot() == before
    assert request(viewer.url + "/api/mock/refresh", {})[0] == 200
    assert mock_pad.backend.graphics_writes == 2
    assert request(viewer.url + "/api/mock/clear", {})[0] == 200
    assert not any(mock_pad.backend.graphics)
    assert not any(mock_pad.backend.braille)


def test_http_rejects_bad_input_unknown_paths_and_cross_origin(viewer):
    base = viewer.url
    assert request(base + "/api/buttons", {"button": "power", "action": "down"})[0] == 400
    assert request(base + "/api/buttons", [1, 2])[0] == 400
    assert request(base + "/api/mock/frame", {"graphics_hex": "zz"})[0] == 400
    assert request(base + "/api/mock/frame", {})[0] == 400
    assert request(base + "/missing")[0] == 404
    assert request(base + "/../gateway.py")[0] == 404
    assert request(base + "/api/bridge/commands?session=none")[0] == 409
    assert request(base + "/api/buttons", {}, headers={"Origin": "https://example.com"})[0] == 403
    assert request(base + "/api/state", headers={"Host": "evil.test"})[0] == 403
    assert request(base + "/api/buttons", {}, headers={"Content-Type": "text/plain"})[0] == 415


def test_server_lifecycle_and_loopback_binding():
    with pytest.raises(ValueError, match="localhost"):
        ViewerServer(DotPad(MockBackend()), host="0.0.0.0")
    server = ViewerServer(DotPad(MockBackend()), port=0)
    with pytest.raises(RuntimeError):
        _ = server.url
    with server:
        assert server.start() is server
        assert request(server.url + "/api/state")[1]["connected"] is False
    server.close()
    assert server._thread is None
