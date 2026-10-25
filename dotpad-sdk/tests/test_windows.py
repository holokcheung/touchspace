from threading import Event

import pytest

from dotpad_sdk import DotPad, DotPadError, Geometry, NotConnectedError, UnsupportedError, WindowsBackend


class Function:
    def __init__(self, implementation):
        self.implementation = implementation

    def __call__(self, *args):
        return self.implementation(*args)


class FakeDLL:
    def __init__(self, *, ready=True, buttons=True):
        self.message = self.down = self.up = None
        self.writes, self.disconnected = [], []
        self.fail = False
        self.DOT_PAD_CONNECT_SERIAL = Function(lambda target: self.message(123, 0, target.encode()) if ready else None)
        self.DOT_PAD_CONNECT_BLE = self.DOT_PAD_CONNECT_SERIAL
        self.DOT_PAD_DISCONNECT = Function(lambda handle: self.disconnected.append(handle) or True)
        self.DOT_PAD_REGISTER_MESSAGE_CALLBACK = Function(lambda cb: setattr(self, "message", cb))
        self.DOT_PAD_DISPLAY_DATA = Function(lambda data, length, handle: self.write("graphics", data, length, handle))
        self.DOT_PAD_BRAILLE_DISPLAY_DATA = Function(lambda data, length, handle: self.write("braille", data, length, handle))
        if buttons:
            self.DOT_PAD_REGISTER_KEY_DOWN_CALLBACK = Function(lambda cb: setattr(self, "down", cb))
            self.DOT_PAD_REGISTER_KEY_UP_CALLBACK = Function(lambda cb: setattr(self, "up", cb))

    def write(self, area, data, length, handle):
        self.writes.append((area, bytes(data[:length]), handle))
        return not self.fail


def test_windows_native_exports_raw_data_refresh_and_callbacks():
    dll = FakeDLL()
    backend = WindowsBackend("/unused", "COM3", geometry=Geometry(2, 1, 4), _library=dll)
    events, done = [], Event()
    with DotPad(backend) as pad:
        pad.display_graphics(b"\x08\x10")
        pad.refresh_graphics()
        pad.display_braille(b"\x40\x80")
        assert dll.writes == [("graphics", b"\x08\x10", 123), ("graphics", b"\x08\x10", 123), ("braille", b"\x40\x80\0\0", 123)]
        assert dll.DOT_PAD_CONNECT_SERIAL.restype is None
        assert backend.supports_buttons
        pad.on_button(lambda event: (events.append(event), done.set() if len(events) == 2 else None))
        dll.down(999, 0, b"1")  # Other device: ignored.
        dll.down(123, 4, b"1")
        dll.up(123, 4, b"0")
        assert done.wait(2)
        assert [(e.button.value, e.action.value) for e in events] == [("panning_left", "down"), ("panning_left", "up")]
    assert dll.disconnected == [123]
    assert dll.message is dll.down is dll.up is None


def test_windows_rejection_and_native_disconnect():
    dll = FakeDLL()
    with DotPad(WindowsBackend("/unused", "DotPad320-1", transport="ble", _library=dll)) as pad:
        dll.fail = True
        with pytest.raises(DotPadError, match="rejected"):
            pad.display_graphics(bytes(300))
        assert not pad.snapshot()["graphics_submitted"]
        dll.message(123, 1, b"disconnected")
        with pytest.raises(NotConnectedError):
            pad.display_braille(b"\x01")


def test_windows_callback_support_is_optional():
    dll = FakeDLL(buttons=False)
    with DotPad(WindowsBackend("/unused", "COM3", _library=dll)) as pad:
        assert not pad.snapshot()["supports_buttons"]
        pad.display_graphics(bytes(300))


def test_windows_global_callbacks_have_one_owner_and_timeout_cleans_up():
    first = WindowsBackend("/unused", "COM3", _library=FakeDLL())
    second = WindowsBackend("/unused", "COM4", _library=FakeDLL())
    with DotPad(first):
        with pytest.raises(DotPadError, match="owns"):
            DotPad(second).open()
        assert first.connected
    with DotPad(second):
        pass
    dll = FakeDLL(ready=False)
    with pytest.raises(DotPadError, match="timed out"):
        DotPad(WindowsBackend("/unused", "COM3", connect_timeout=.01, _library=dll)).open()
    assert dll.disconnected == [None]
    assert dll.message is None
    with DotPad(WindowsBackend("/unused", "COM3", _library=FakeDLL())):
        pass  # Owner lock was released after failure.


def test_non_windows_host_gives_actionable_error(monkeypatch):
    monkeypatch.setattr("dotpad_sdk.windows.sys.platform", "darwin")
    with pytest.raises(UnsupportedError, match="BrowserBackend"):
        DotPad(WindowsBackend("/unused", "COM3")).open()
