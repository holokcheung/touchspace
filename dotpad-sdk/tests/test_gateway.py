import logging
from threading import Event, Thread

import pytest

from dotpad_sdk import Button, ButtonAction, DotPad, DotPadError, Geometry, MockBackend, NotConnectedError


def test_raw_frames_refresh_padding_and_independent_areas(mock_pad):
    backend = mock_pad.backend
    graphics = bytes(range(100)) * 3
    mock_pad.display_graphics(graphics)
    mock_pad.display_braille(b"\x40\x80")
    assert backend.graphics == graphics
    assert backend.braille == b"\x40\x80" + bytes(18)
    mock_pad.refresh_graphics()
    mock_pad.refresh_braille()
    assert (backend.graphics_writes, backend.braille_writes) == (2, 2)
    mock_pad.display_braille(b"\x01")
    assert backend.braille == b"\x01" + bytes(19)
    assert backend.graphics == graphics
    mock_pad.display_braille(b"")
    assert backend.braille == bytes(20)


def test_inputs_are_copied(mock_pad):
    graphics = bytearray([0xFF]) * 300
    mock_pad.display_graphics(graphics)
    graphics[0] = 0
    assert mock_pad.backend.graphics[0] == 0xFF
    mock_pad.display_braille(memoryview(b"\x81"))
    assert mock_pad.backend.braille[0] == 0x81


@pytest.mark.parametrize("data", [b"", bytes(299), bytes(301)])
def test_invalid_graphic_size_does_not_write(mock_pad, data):
    with pytest.raises(ValueError):
        mock_pad.display_graphics(data)
    assert mock_pad.backend.graphics_writes == 0


@pytest.mark.parametrize("method,data,error", [
    ("display_graphics", [0] * 300, TypeError),
    ("display_braille", "hello", TypeError),
    ("display_braille", bytes(21), ValueError),
])
def test_reject_ambiguous_or_oversized_input(mock_pad, method, data, error):
    with pytest.raises(error):
        getattr(mock_pad, method)(data)


def test_lifecycle_and_uninitialized_refresh():
    pad = DotPad(MockBackend())
    with pytest.raises(NotConnectedError):
        pad.display_braille(b"a")
    with pad:
        assert pad.open() is pad
        with pytest.raises(ValueError):
            pad.refresh_graphics()
        with pytest.raises(ValueError):
            pad.refresh_braille()
        pad.display_graphics(bytes(300))
    pad.close()
    assert not pad.connected
    with pytest.raises(NotConnectedError):
        pad.refresh_graphics()
    with pad:
        with pytest.raises(ValueError):
            pad.refresh_graphics()


def test_failed_write_preserves_last_successful_frame(mock_pad, monkeypatch):
    original = mock_pad.backend.write_graphics
    mock_pad.display_graphics(b"\x01" * 300)
    revision = mock_pad.snapshot()["revision"]
    def fail(_):
        raise DotPadError("output rejected")
    monkeypatch.setattr(mock_pad.backend, "write_graphics", fail)
    with pytest.raises(DotPadError, match="rejected"):
        mock_pad.display_graphics(b"\xFF" * 300)
    assert mock_pad.snapshot()["revision"] == revision
    monkeypatch.setattr(mock_pad.backend, "write_graphics", original)
    mock_pad.refresh_graphics()
    assert mock_pad.backend.graphics == b"\x01" * 300


def test_button_order_deduplication_and_unsubscribe(mock_pad):
    events, received = [], Event()
    def record(event):
        events.append(event)
        if len(events) == 4:
            received.set()
    unsubscribe = mock_pad.on_button(record)
    for action in ("down", "down", "up", "up", "down", "up"):
        mock_pad.backend.emit_button(Button.FUNCTION_1, action)
    assert received.wait(2)
    assert [event.action for event in events] == [ButtonAction.DOWN, ButtonAction.UP] * 2
    unsubscribe()
    unsubscribe()
    assert record not in mock_pad._listeners
    assert all(event.button is Button.FUNCTION_1 for event in events)


def test_callback_failure_isolated_and_callback_can_write(mock_pad, caplog):
    done = Event()
    def broken(_):
        raise ValueError("listener failed")
    def redraw(_):
        mock_pad.display_braille(b"\x07")
        done.set()
    mock_pad.on_button(broken)
    mock_pad.on_button(redraw)
    with caplog.at_level(logging.ERROR):
        mock_pad.backend.emit_button("panning_left", "down")
        assert done.wait(2)
    assert mock_pad.backend.braille[0] == 7
    assert "listener failed" in caplog.text


def test_concurrent_writes_are_complete_frames(mock_pad):
    threads = [Thread(target=mock_pad.display_graphics, args=(bytes([i]) * 300,)) for i in range(25)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert mock_pad.backend.graphics_writes == 25
    assert len(set(mock_pad.backend.graphics)) == 1


def test_custom_geometry_and_mock_disconnect():
    geometry = Geometry(2, 1, 4)
    with DotPad(MockBackend(geometry)) as pad:
        pad.display_graphics(b"\x01\x02")
        pad.display_braille(b"\x40")
        assert pad.snapshot()["braille_hex"] == "40000000"
        pad.backend.close()
        with pytest.raises(NotConnectedError):
            pad.display_graphics(b"\x00\x00")


@pytest.mark.parametrize("dimensions", [(0, 10, 20), (30, -1, 20), (30, 10, True), (30, 10, 1.5)])
def test_invalid_geometry(dimensions):
    with pytest.raises(ValueError):
        Geometry(*dimensions)


def test_failed_open_cleans_up():
    class FailingMock(MockBackend):
        def open(self, callback):
            super().open(callback)
            raise DotPadError("cannot connect")
    pad = DotPad(FailingMock())
    with pytest.raises(DotPadError, match="cannot connect"):
        pad.open()
    assert not pad.backend.connected
    assert pad._worker is None
