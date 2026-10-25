"""ctypes bindings for DotPad Windows SDK 3.0.2; vendor files stay external."""

import ctypes
import os
import sys
from pathlib import Path
from threading import Event, Lock

from .backend import Backend, ButtonHandler
from .model import (
    Button, ButtonAction, ButtonEvent, DotPadError, Geometry, NotConnectedError,
    UnsupportedError,
)

# Vendor callbacks are process-global. Do not let adapters replace each other's callbacks.
_sdk_owner = Lock()
_KEYS = (Button.FUNCTION_1, Button.FUNCTION_2, Button.FUNCTION_3, Button.FUNCTION_4,
         Button.PANNING_LEFT, Button.PANNING_RIGHT)


class WindowsBackend(Backend):
    def __init__(self, sdk_directory: str | Path, target: str, *, transport: str = "serial",
                 geometry: Geometry = Geometry(), connect_timeout: float = 15, _library=None):
        if transport not in ("serial", "ble"):
            raise ValueError("Transport must be 'serial' or 'ble'")
        if not target or connect_timeout <= 0:
            raise ValueError("Supply a device name/COM port and a positive timeout")
        self.geometry = geometry
        self.target = target
        self.transport = transport
        self.connect_timeout = connect_timeout
        self._sdk_directory = Path(sdk_directory).expanduser().resolve()
        self._library = _library
        self._dll_directory = None
        self._handle = None
        self._ready = Event()
        self._owns_sdk = False
        self._closing = False
        self._callbacks = []
        self.supports_buttons = False

    @property
    def connected(self):
        return self._handle is not None and not self._closing

    def _load(self):
        if self._library is None:
            if sys.platform != "win32":
                raise UnsupportedError("Windows DLLs require Windows; use MockBackend or BrowserBackend here")
            candidates = [self._sdk_directory / "DotPadSDK-3.0.2.dll", self._sdk_directory / "DotPadSDK.dll"]
            dll = next((path for path in candidates if path.is_file()), None)
            if dll is None:
                raise DotPadError("Place the Windows 3.0.2 SDK DLL and its dependencies in sdk_directory")
            self._dll_directory = os.add_dll_directory(str(self._sdk_directory))
            try:
                # Exported functions are cdecl; only CALLBACK function pointers are stdcall.
                self._library = ctypes.CDLL(str(dll))
            except OSError as exc:
                self._dll_directory.close()
                self._dll_directory = None
                raise DotPadError(f"Cannot load the DotPad DLL/dependencies: {exc}") from exc
        self._connect = self._bind(
            "DOT_PAD_CONNECT_SERIAL" if self.transport == "serial" else "DOT_PAD_CONNECT_BLE",
            [ctypes.c_wchar_p], None,
        )
        self._disconnect = self._bind("DOT_PAD_DISCONNECT", [ctypes.c_void_p], ctypes.c_bool)
        self._write_graphic = self._bind("DOT_PAD_DISPLAY_DATA",
                                        [ctypes.POINTER(ctypes.c_uint8), ctypes.c_int, ctypes.c_void_p], ctypes.c_bool)
        self._write_text = self._bind("DOT_PAD_BRAILLE_DISPLAY_DATA",
                                     [ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t, ctypes.c_void_p], ctypes.c_bool)
        self._register_message = self._bind("DOT_PAD_REGISTER_MESSAGE_CALLBACK", [ctypes.c_void_p], None)
        self._register_down = self._bind("DOT_PAD_REGISTER_KEY_DOWN_CALLBACK", [ctypes.c_void_p], None, optional=True)
        self._register_up = self._bind("DOT_PAD_REGISTER_KEY_UP_CALLBACK", [ctypes.c_void_p], None, optional=True)
        self.supports_buttons = self._register_down is not None and self._register_up is not None

    def _bind(self, name, args, result, optional=False):
        function = getattr(self._library, name, None)
        if function is None:
            if optional:
                return None
            raise DotPadError(f"SDK export missing: {name}")
        function.argtypes, function.restype = args, result
        return function

    def open(self, on_button: ButtonHandler):
        if not _sdk_owner.acquire(blocking=False):
            raise DotPadError("Another WindowsBackend owns the SDK's global callbacks")
        self._owns_sdk = True
        try:
            self._load()
            self._closing = False
            self._ready.clear()
            callback_type = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
            message_type = callback_type(None, ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p)

            def message(handle, code, _text):
                if self._closing:
                    return
                if code == 0 and handle:  # DOT_DATA_CODE_CONNECTED
                    self._handle = handle
                    self._ready.set()
                elif code == 1 and handle == self._handle:
                    self._handle = None

            message_callback = message_type(message)
            self._callbacks = [message_callback]
            self._register_message(message_callback)
            if self.supports_buttons:
                key_type = callback_type(None, ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p)

                def key_handler(action):
                    def receive(handle, key, _binary):
                        if not self._closing and handle == self._handle and 0 <= key < len(_KEYS):
                            on_button(ButtonEvent(_KEYS[key], action))
                    return key_type(receive)

                down, up = key_handler(ButtonAction.DOWN), key_handler(ButtonAction.UP)
                self._callbacks.extend((down, up))
                self._register_down(down)
                self._register_up(up)
            self._connect(self.target)  # void: readiness/handle arrive through the message callback.
            if not self._ready.wait(self.connect_timeout) or not self.connected:
                raise DotPadError(f"DotPad connection timed out: {self.target}")
        except BaseException:
            self.close()
            raise

    def close(self):
        self._closing = True
        self._ready.set()
        if self._owns_sdk:
            try:
                if hasattr(self, "_disconnect"):
                    self._disconnect(self._handle)
                if hasattr(self, "_register_message"):
                    self._register_message(None)
                for register in (getattr(self, "_register_down", None), getattr(self, "_register_up", None)):
                    if register is not None:
                        register(None)
            finally:
                self._handle = None
                self._owns_sdk = False
                _sdk_owner.release()
        # Retain DLL-directory and callback objects for this adapter's lifetime.

    def _write(self, function, cells):
        if not self.connected:
            raise NotConnectedError("Windows DotPad is disconnected")
        buffer = (ctypes.c_uint8 * len(cells)).from_buffer_copy(cells)
        if not function(buffer, len(cells), self._handle):
            raise DotPadError("The Windows SDK rejected the raw display write")

    def write_graphics(self, cells: bytes):
        self._write(self._write_graphic, cells)

    def write_braille(self, cells: bytes):
        self._write(self._write_text, cells)
