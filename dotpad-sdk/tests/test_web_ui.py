"""Optional real Chromium tests: pip install .[browser-test]; playwright install chromium."""

from concurrent.futures import ThreadPoolExecutor
import os
from threading import Event

import pytest

from dotpad_sdk import BrowserBackend, DotPad, ViewerServer

playwright = pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as runtime:
        options = {"executable_path": os.environ["DOTPAD_BROWSER_EXECUTABLE"]} if "DOTPAD_BROWSER_EXECUTABLE" in os.environ else {}
        instance = runtime.chromium.launch(**options)
        yield instance
        instance.close()


def test_viewer_live_graphics_braille_encoding_buttons_and_mobile(browser, viewer, mock_pad):
    page = browser.new_page(viewport={"width": 1100, "height": 950}, device_scale_factor=1)
    try:
        page.goto(viewer.url)
        page.wait_for_function("document.querySelector('#connection').textContent === 'Mock connected'")
        mock_pad.display_graphics(b"\xff" + bytes(299))
        mock_pad.display_braille(b"\x40")
        page.wait_for_function("document.querySelector('#graphics').dataset.raised === '8' && document.querySelector('#braille').dataset.raised === '1'")
        decoded = page.evaluate("""async () => {
          const {decodePins} = await import('/pins.js');
          return [decodePins('08', 1, 1), decodePins('40', 1, 1, true)];
        }""")
        assert decoded[0] == decoded[1] == [[False, False], [False, False], [False, False], [True, False]]
        done, events = Event(), []
        mock_pad.on_button(lambda e: (events.append(e), done.set() if len(events) == 2 else None))
        page.get_by_role("button", name="Function 1", exact=True).click()
        assert done.wait(2)
        assert [e.action.value for e in events] == ["down", "up"]
        page.get_by_role("button", name="Panning right", exact=True).focus()
        page.keyboard.press("Space")
        page.wait_for_function("document.querySelector('#event-log').textContent.includes('right ↑')")
        page.get_by_role("button", name="Load demo", exact=True).click()
        page.wait_for_function("Number(document.querySelector('#graphics').dataset.raised) > 8")
        page.screenshot(path="/tmp/dotpad-sdk-viewer-desktop.png", full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path="/tmp/dotpad-sdk-viewer-mobile.png", full_page=True)
        page.get_by_role("button", name="Clear", exact=True).click()
        page.wait_for_function("document.querySelector('#graphics').dataset.raised === '0' && document.querySelector('#braille').dataset.raised === '0'")
    finally:
        page.close()


def test_hardware_page_calls_vendor_sdk_without_translation(browser, tmp_path):
    # This stub exercises actual bridge JS/HTTP, not a physical DotPad or the vendor transport stack.
    sdk_file = tmp_path / "vendor.js"
    sdk_file.write_text("""
      export const DisplayMode = {GraphicMode: 'GraphicMode', TextMode: 'TextMode'};
      export const DataCodes = {Disconnected: 'Disconnected'};
      export class DotPadScanner { async startBleScan() { return {}; } }
      export class DotPadSDK {
        setCallBack(message, key, down, up) { this.down = down; this.up = up; window.vendor = this; }
        async connectBleDevice() { return this.device = {isConnect:true,numberCellColumns:30,numberCellRows:10,numberBrailleCellColumns:20}; }
        displayGraphicData(hex, device, mode) { (window.writes ||= []).push({area:'graphics',hex,mode}); }
        async displayTextData(hex, device, mode, needsTranslation) { (window.writes ||= []).push({area:'braille',hex,mode,needsTranslation}); }
        disconnect() { this.device.isConnect = false; }
      }
    """)
    backend = BrowserBackend(connect_timeout=5, command_timeout=5)
    pad = DotPad(backend)
    with ViewerServer(pad, port=0, web_sdk=sdk_file) as server, ThreadPoolExecutor() as pool:
        page = browser.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'bluetooth', {value: {}})")
        try:
            opening = pool.submit(pad.open)
            page.goto(server.url + "/hardware")
            page.get_by_role("button", name="Connect Bluetooth", exact=True).click()
            page.wait_for_function("document.querySelector('#hardware-status').textContent.includes('awaiting Python')")
            opening.result(timeout=2)
            writing = pool.submit(pad.display_graphics, b"\x08" * 300)
            # Keep Playwright's event loop pumping while the browser processes the command.
            page.wait_for_function("window.writes?.length === 1")
            writing.result(timeout=2)
            writing = pool.submit(pad.display_braille, b"\x40")
            page.wait_for_function("window.writes?.length === 2")
            writing.result(timeout=2)
            writes = page.evaluate("window.writes")
            assert writes[0] == {"area": "graphics", "hex": "08" * 300, "mode": "GraphicMode"}
            assert writes[1] == {"area": "braille", "hex": "40" + "00" * 19, "mode": "TextMode", "needsTranslation": False}
            received = Event()
            pad.on_button(lambda _: received.set())
            page.evaluate("window.vendor.down(window.vendor.device, 'KeyFunction3')")
            page.wait_for_timeout(150)
            assert received.wait(2)
            page.get_by_role("button", name="Disconnect", exact=True).click()
            page.wait_for_function("document.querySelector('#hardware-status').textContent === 'Disconnected'")
            assert not pad.connected
        finally:
            pad.close()
            page.close()
