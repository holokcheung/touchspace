# DotPad module

The walkthrough imports this module through `index.ts`. It owns map-to-pin rendering,
preview UI, uncontracted English braille, and the physical-device connection. No other
frontend file imports the vendor SDK.

- `pins.ts`: map geometry → 60 × 40 pins → 300 eight-dot cell bytes (north up).
- `text.ts`: English letters, capitalization/number indicators and punctuation; pad to
  the device text-line width. Room names shorten as needed to keep the heading.
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

## Vendor source

`vendor/DotPadSDK-3.0.0.js` is an **unmodified** copy of Dot Inc.'s Web SDK 3.0.0:

https://github.com/dotincorp/dotpad-sdk-guide/tree/main/Web/3.0.0

Upstream Git blob: `604e60b64fa89754053feab6e7bb83855542d6d6`.
The accompanying `.d.ts` is a narrow local declaration of the APIs used here; upstream's
published declarations refer to unavailable Web Bluetooth/Serial globals and use
value objects as types. The vendor SDK handles protocol framing, line buffering, ACKs
and output diffs. TouchSpace sends `displayGraphicData` / `displayTextData` hex strings
and never implements a competing Bluetooth or serial protocol.

Text translation is local: the SDK expects braille hex and does not translate English.
Unsupported characters become blank cells. This is basic uncontracted English braille,
not a general language translation service.

## Validation

`npm test` covers packing, moving position markers, braille indicators, SDK handshake,
Bluetooth/USB selection, frame coalescing, incompatible boards, cancellation,
disconnection, timeout and unmount cleanup using an SDK fake. Physical pin order,
firmware behavior, and actual BLE/USB output still need validation on a real DotPad.
