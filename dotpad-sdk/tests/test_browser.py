from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep

import pytest

from dotpad_sdk import BrowserBackend, DotPad, DotPadError, Geometry, NotConnectedError, ViewerServer
from conftest import request


def next_command(backend, session="test"):
    deadline = monotonic() + 2
    while monotonic() < deadline:
        commands = backend.take_commands(session)
        if commands:
            return commands[0]
        sleep(.005)
    raise AssertionError("No command received")


def test_browser_raw_frames_acknowledgements_and_errors():
    backend = BrowserBackend(command_timeout=2)
    backend.attach("test", Geometry(2, 1, 4))
    with DotPad(backend) as pad, ThreadPoolExecutor() as pool:
        future = pool.submit(pad.display_graphics, b"\x08\x10")
        command = next_command(backend)
        assert command["area"] == "graphics" and command["hex"] == "0810"
        assert backend.take_commands("test") == []
        assert not future.done()
        backend.acknowledge("test", command["id"])
        future.result(timeout=2)
        future = pool.submit(pad.display_braille, b"\x40")
        command = next_command(backend)
        assert command["hex"] == "40000000"
        backend.acknowledge("test", command["id"], "hardware rejected output")
        with pytest.raises(DotPadError, match="rejected"):
            future.result(timeout=2)
        assert not pad.snapshot()["braille_submitted"]


def test_bridge_http_roundtrip_and_button_callback(tmp_path):
    backend = BrowserBackend(connect_timeout=2, command_timeout=2)
    pad = DotPad(backend)
    vendor_file = tmp_path / "sdk.js"
    vendor_file.write_text("export const version = 'test';")
    with ViewerServer(pad, port=0, web_sdk=vendor_file) as server, ThreadPoolExecutor() as pool:
        opening = pool.submit(pad.open)
        assert request(server.url + "/api/bridge/connect", {"session": "http", "geometry": {"graphic_columns": 2, "graphic_rows": 1, "braille_cells": 4}})[0] == 200
        opening.result(timeout=2)
        try:
            assert request(server.url + "/vendor-sdk.js")[1] == vendor_file.read_bytes()
            write = pool.submit(pad.display_graphics, b"\x80\x01")
            deadline = monotonic() + 2
            commands = []
            while not commands and monotonic() < deadline:
                commands = request(server.url + "/api/bridge/commands?session=http")[1]["commands"]
            assert commands[0]["hex"] == "8001"
            assert request(server.url + "/api/bridge/ack", {"session": "http", "id": commands[0]["id"]})[0] == 200
            write.result(timeout=2)
            done = Event()
            pad.on_button(lambda _: done.set())
            assert request(server.url + "/api/bridge/button", {"session": "http", "button": "panning_right", "action": "down"})[0] == 200
            assert done.wait(2)
            assert request(server.url + "/api/buttons", {"button": "function1", "action": "down"})[0] == 409
            assert request(server.url + "/api/bridge/disconnect", {"session": "http"})[0] == 200
            assert not pad.connected
        finally:
            pad.close()


def test_timeout_and_disconnect_invalidate_pending_commands():
    backend = BrowserBackend(command_timeout=.03)
    backend.attach("test", Geometry())
    with DotPad(backend) as pad:
        with pytest.raises(DotPadError, match="unknown"):
            pad.display_braille(b"a")
        assert not pad.connected
        with pytest.raises(NotConnectedError):
            backend.take_commands("test")

    backend = BrowserBackend(command_timeout=2)
    backend.attach("test", Geometry())
    with DotPad(backend) as pad, ThreadPoolExecutor() as pool:
        future = pool.submit(pad.display_braille, b"a")
        command = next_command(backend)
        backend.detach("test")
        with pytest.raises(DotPadError, match="disconnected"):
            future.result(timeout=2)
        backend.attach("new", Geometry())
        with pytest.raises(NotConnectedError):
            backend.acknowledge("test", command["id"])
        assert backend.take_commands("new") == []


def test_connection_timeout_cancellation_and_session_ownership():
    with pytest.raises(DotPadError, match="hardware"):
        DotPad(BrowserBackend(connect_timeout=.01)).open()
    backend = BrowserBackend(connect_timeout=10)
    with ThreadPoolExecutor() as pool:
        future = pool.submit(backend.open, lambda _: None)
        sleep(.02)
        backend.close()
        with pytest.raises(NotConnectedError):
            future.result(timeout=2)
    backend = BrowserBackend()
    backend.attach("test", Geometry())
    with pytest.raises(DotPadError, match="already"):
        backend.attach("other", Geometry())
    backend.close()
