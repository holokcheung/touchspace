# DotPad gateway

Python 3.11+. Raw graphics, raw braille cells, refresh, and optional button down/up callbacks. The core and mock use only Python's standard library; real hardware requires external vendor SDK files.

This directory is independently installable: copy it anywhere, then run these commands from inside it using your Python environment. The core and mock viewer need no other checkout or vendor SDK files.

```sh
python -m pip install -e '.[test]'
dotpad-viewer --demo  # http://127.0.0.1:8767
python -m pytest
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

**Vendor files are not bundled.** The gateway and mock are self-contained; the complete hardware stack is not. Obtain the following files from [Dot Inc's SDK repository](https://github.com/dotincorp/dotpad-sdk-guide):

| Mode | Vendor files to supply |
|---|---|
| Mock viewer / headless mock | None. |
| Windows native SDK 3.0.2 | `DotPadSDK-3.0.2.dll` (or `DotPadSDK.dll`), `TTBEngine.dll`, `MeCab.dll`, and `liblouis.dll`, together in the directory passed as `sdk_directory`. All DLLs must match your **Python process's x86/x64 architecture**. |
| Browser hardware bridge, Web SDK 3.0.4 | Only `DotPadSDK-3.0.4.js`, passed as `web_sdk` or `dotpad-viewer --backend browser --web-sdk /path/to/DotPadSDK-3.0.4.js`. No `.d.ts`, WASM, or translation assets are needed for raw output. |

For Windows, preserve the vendor support files: `mecabrc`, plus `ipadic/` and `tables/` extracted from `ipadic.zip` and `tables.zip`, following the vendor's installation instructions. The gateway does not call translation APIs; supplying the complete vendor runtime avoids relying on undocumented SDK initialization behavior. Headers and demo executables are not needed by the Python bindings.

Vendor files can live anywhere; no SDK checkout path is hardcoded. Close and reopen the gateway to start a new session after disconnection.

**Current platform coverage:** native bindings are implemented only for Windows. The browser bridge is a separate hardware route, not a binding to each platform's native SDK.

| Platform | Gateway support / vendor requirement |
|---|---|
| Windows | Native DLL adapter, or browser bridge; files listed above. |
| Web | Browser bridge with vendor JS and a running Python gateway; requires supported Web Bluetooth/Web Serial APIs. |
| macOS | Mock and browser bridge where hardware APIs are supported; no native macOS adapter. |
| Linux | Mock and browser bridge where hardware APIs are supported. No native adapter: vendor SDK 1.0.0 does not expose the required raw graphic/braille APIs. |
| Android | **Native adapter not implemented.** A future Kotlin/JNI bridge would need `android-sdk-3.0.3.aar` (including its native libraries). Browser bridging is possible only where the mobile browser exposes the required hardware API; it does not provide general Android USB support. |
| iOS / iPadOS | **Native adapter not implemented.** A future Swift bridge would need `DotPadFrameworks.xcframework` from SDK 2.3.2. Its supplied build targets physical ARM64 iOS devices, not the simulator. No supported iOS browser hardware route is included. |

Android/iOS vendor files are not bundled, and supplying them alone does not enable those platforms. Future native adapters can share the byte/event contract and implement the operations in the small [Backend interface](src/dotpad_sdk/backend.py); no Swift or Kotlin bindings are included. The Python mock/viewer can run wherever a suitable Python runtime is available, but this package does not ship native mobile apps.

Optional browser tests (mock and vendor-stub integration; no DotPad required):

```sh
python -m pip install -e '.[browser-test]'
python -m playwright install chromium
python -m pytest tests/test_web_ui.py
```
