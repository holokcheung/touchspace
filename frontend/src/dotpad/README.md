# DotPad module

The walkthrough imports this module through `index.ts`. It owns map-to-pin rendering,
preview UI, uncontracted English braille, and the physical-device connection. No other
frontend file imports the vendor SDK. This is the sole DotPad integration: the browser
connects directly over Bluetooth or USB; no Python gateway, WebSocket bridge or iOS
DotPad service is required.

- `pins.ts`: map geometry → 60 × 40 pins → 300 eight-dot cell bytes (north up).
  Graphic cells use the SDK's column order (bits 0–3 left, 4–7 right); text cells
  retain standard braille dot numbering.
- `text.ts`: English letters, capitalization/number indicators and punctuation; pad to
  the device text-line width. Room names shorten as needed to keep the heading.
- `discovery.ts`: the vendor Bluetooth filter, an explicit unfiltered fallback,
  and permission errors that the vendor scanner otherwise suppresses.
- `device.ts`: Bluetooth/USB picker, SDK readiness callback, board-size check,
  coalesced updates (150 ms), disconnect/timeout/error handling and cleanup.
- `Panel.tsx` / `Preview.tsx`: connection controls and accessible pin preview.

## Hardware

Open the connected app in Chrome on **HTTPS or localhost**. In the walkthrough,
choose **DotPad**, then **Connect Bluetooth** or **Connect USB**. Select the device in
Chrome's picker. Output begins after the SDK's `DataCodes.Connected` callback, then
tracks position even when you switch to another side panel. **Lower all pins** clears
the display; the next movement updates it again. Leaving the walkthrough disconnects.

The current map rasterizer supports boards with **30 × 10 graphic cells** (60 × 40
pins). Other boards are rejected with an explanation. The text width comes from the
connected board. Firefox and Safari can show the preview but cannot connect through
these SDK transports. A file opened directly from disk may also be unable to connect;
serve the standalone build on localhost or HTTPS to use hardware.

## Reconnecting without rescanning

After this origin has been granted access to a DotPad, the panel uses
`navigator.bluetooth.getDevices()` to show **Reconnect DotPad320X_BD35** (or the
corresponding device name). This calls the vendor SDK with the existing browser
BluetoothDevice, without opening the chooser or performing a new discovery scan.
The permission is specific to this origin, so a device selected on port 3000 must
still be selected once on port 5173. This path requires browser support for
`getDevices()` and cannot make powered-off or nonconnectable hardware connect.

The reported device disappeared from subsequent chooser scans and became visible
again after restarting it. That suggests peripheral advertising or browser scan
state; matching scan options alone cannot distinguish those causes. Restart once
and select it in TouchSpace, then use Reconnect on later attempts.

## Empty Bluetooth picker

The default scan uses exactly the same `namePrefix: "DotPad"` filter and UART service
UUID as the vendor 3.0.4 demo. **Show all Bluetooth devices** removes only the name
filter, keeping the required service in `optionalServices`; choose your DotPad in that
list. This accommodates devices advertising another name, without changing the SDK's
connection protocol. Picker errors are shown rather than silently discarded.

Disconnect the device in the demo first when comparing discovery between apps.
`localhost:3000`, `localhost:5173`, and `127.0.0.1:5173` have separate browser device
permissions. A device remembered by the demo is not automatically granted to TouchSpace.
If the picker remains empty with all devices shown, check this origin's Chrome
Bluetooth/nearby-device permissions and whether the device is advertising. No hardware
cause is inferred solely from a passing mocked discovery test.

## Vendor source

`vendor/DotPadSDK-3.0.4.js` is an **unmodified** copy of Dot Inc.'s Web SDK 3.0.4:

https://github.com/dotincorp/dotpad-sdk-guide/tree/main/Web/3.0.4

Upstream Git blob: `fc798f689437333a52b32b3fad0be6d09a32f74b`.
The accompanying `.d.ts` is a narrow local declaration of the APIs used here; upstream's
published declarations refer to unavailable Web Bluetooth/Serial globals and use
value objects as types. Copied from the working local `dotpad-sdk-guide/Web/3.0.4/DemoApp/src/sdk` checkout
at commit `88583a619f10292b670943461aa4eec3cdda689e`.
The vendor SDK handles protocol framing, line buffering, ACKs
and output diffs. TouchSpace sends `displayGraphicData` / `displayTextData` hex strings
and never implements a competing Bluetooth or serial protocol.

Text translation remains local and sends already-encoded hex. SDK 3.0.4 also offers
optional WASM translation, which this module does not call or download.
Unsupported characters become blank cells. This is basic uncontracted English braille,
not a general language translation service.

## Validation

`npm test` covers packing, moving position markers, braille indicators, SDK handshake,
Bluetooth/USB selection, frame coalescing, incompatible boards, cancellation,
disconnection, timeout and unmount cleanup using an SDK fake. Physical pin order,
firmware behavior, and actual BLE/USB output still need validation on a real DotPad.
