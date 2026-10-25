# DotPad gateway

Python 3.11+, no runtime dependencies. Raw graphics, raw braille cells, refresh, and optional button down/up callbacks.

From the repository root, using your Python environment:

```sh
python -m pip install -e './dotpad-sdk[test]'
dotpad-viewer --demo  # http://127.0.0.1:8767
python -m pytest -c dotpad-sdk/pyproject.toml dotpad-sdk/tests
```

Use the viewer **in the same process** as your application to see its frames:

```python
from dotpad_sdk import DotPad, MockBackend, ViewerServer

pad = DotPad(MockBackend())
pad.on_button(lambda event: print(event.button.value, event.action.value))
with ViewerServer(pad) as viewer:
    print(viewer.url)
    with pad:
        pad.display_graphics(bytes([0xFF]) + bytes(299))
        pad.display_braille(b"\x01\x03\x09")
        pad.refresh_graphics()
        pad.refresh_braille()
        input("Enter to stop\n")
```

- Graphics: one byte per 2×4-pin cell, row-major; default 30×10 cells (60×40 pins). Use `pack_graphics(pin_grid)` for a grid of booleans.
- Braille: standard dot 1–8 bit masks, up to 20 cells by default; shorter lines are zero-padded. Graphic and braille bit layouts differ; see [contract.json](src/dotpad_sdk/contract.json).
- Refresh resubmits the last successful bytes. A successful call means SDK submission, not confirmed physical pin completion. Callbacks run on a gateway thread; `on_button()` returns an unsubscribe function.

| Backend | Usage |
|---|---|
| `MockBackend()` | Headless mock; `ViewerServer` adds a top-down pin viewer and six working buttons. Accepts a custom `Geometry`. |
| `WindowsBackend(sdk_directory, "COM3")` | Native Windows SDK **3.0.2** DLL bindings; `transport="ble"` accepts a device name. Supply the matching x86/x64 vendor DLLs and dependencies. Defaults to 30×10 graphics / 20 braille cells; override `geometry` for other layouts. |
| `BrowserBackend()` | Python → local browser → vendor Web SDK **3.0.4** → BLE/USB hardware. Start `ViewerServer(pad, web_sdk="/path/to/DotPadSDK-3.0.4.js")` before `pad.open()`, then connect at `/hardware`. Keep that tab open. Requires browser/OS hardware API support. |

The browser bridge needs only the vendor JS file; translation assets are unused. Vendor binaries/JS are not bundled. Close and reopen the gateway to start a new session after disconnection. Linux's native 1.0.0 SDK cannot provide these raw-output APIs; use the browser route where supported.

Future Swift/native adapters can implement the small [Backend interface](src/dotpad_sdk/backend.py) and share the byte/event contract. No Swift bindings are included.

Optional browser tests (mock and vendor-stub integration; no DotPad required):

```sh
python -m pip install -e './dotpad-sdk[browser-test]'
python -m playwright install chromium
python -m pytest -c dotpad-sdk/pyproject.toml dotpad-sdk/tests/test_web_ui.py
```
