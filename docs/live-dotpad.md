# Live DotPad: iPhone → Mac → DotPad

James's plan, wired end to end: the iPhone's LiDAR (RoomPlan) and ARKit position stream over a
WebSocket to the Mac, which draws them as a 60 × 40 pin picture and sends it to the DotPad.

```
iPhone app ──ws://Mac:8765/phone──▶ python -m app.live ──▶ dotpad_sdk gateway ──▶ Chrome /hardware ──BLE/USB──▶ DotPad
 (RoomPlan room, camera pose)        (backend/app/live)      (dotpad-sdk/, PR #8)   (vendor Web SDK 3.0.4)
                                              └──▶ http://127.0.0.1:8767  on-screen mirror of the pins
```

What the pins show: walls as lines, doorways at least 2 pins wide, plan "up" at the top, landmark
symbols when the map has them, and an X where the phone is. The 20-cell braille line says the room
and the way the phone faces ("kitchen ne"). While scanning, walls appear as RoomPlan finds them.

## Checked so far / not checked

- Checked on a Mac: phone protocol, rendering, mock DotPad, reconnects, wrong-token rejection
  (`backend/tests/test_live.py`, 19 tests); the Swift `DotPadLink` compiled for macOS and streamed a
  map + poses to the bridge, which drew them correctly.
- **Not checked:** the real DotPad, the iOS app build (no Xcode on this Mac), and RoomPlan/ARKit
  on a phone. The bit order follows Dot Inc's own `brailleToGraphic` helper in Web SDK 3.0.4
  (left column = bits 0–3, right column = bits 4–7); confirm it with the test pattern below.

## One-time setup (Mac)

```sh
cd backend
.venv/bin/python -m pip install -e ../dotpad-sdk
mkdir -p ~/dotpad-vendor
curl -L -o ~/dotpad-vendor/DotPadSDK-3.0.4.js \
  https://raw.githubusercontent.com/dotincorp/dotpad-sdk-guide/main/Web/3.0.4/DemoApp/src/sdk/DotPadSDK-3.0.4.js
```

Dot Inc's repo has no license: keep the SDK file outside this repo and never commit it.
Use Chrome (Web Bluetooth / Web Serial). Turn the DotPad on.

## 1. Test pattern on the real DotPad (2 minutes)

```sh
.venv/bin/python -m app.live --dotpad browser --web-sdk ~/dotpad-vendor/DotPadSDK-3.0.4.js --test-pattern
```

Open the printed `/hardware` link in Chrome, press **Connect Bluetooth** or **Connect USB**, and pick the
DotPad. Then feel the pins:

| You should feel | If not |
|---|---|
| A frame around the whole edge | Grid size differs; tell James (geometry comes from the device) |
| A straight diagonal from upper left toward the middle | Scrambled or stepped diagonal → restart with `--bit-order braille` |
| One lone pin just inside the top-left corner, at the **bottom-left** of its 2 × 4 cell | Pin sits top-right instead → `--bit-order braille` |
| A capital **F** on the right, upright, facing right | Mirrored or upside down → tell us; the map would be too |
| Braille line: "dotpad test" | Braille line uses dot order; report it |

Write down which `--bit-order` worked and use it below.

## 2. Run the bridge

```sh
.venv/bin/python -m app.live --dotpad browser --web-sdk ~/dotpad-vendor/DotPadSDK-3.0.4.js
```

It prints the `/hardware` link (connect the DotPad again, keep the tab open), the mirror link
(put it on screen for judges), and the **phone URL**, e.g. `ws://192.168.1.20:8765/phone?token=3fa9c1`.
Options: `--map ../sample-data/demo-building.json` shows a map before the phone connects;
`--min-interval 1` if the DotPad lags behind; `--bit-order braille` if step 1 said so.

No DotPad at hand? Leave out `--dotpad`/`--web-sdk`: the mirror page shows the same pins.

## 3. iPhone (branch `ios-live-dotpad`, built on James's `ios-app`)

1. Build and run on a LiDAR iPhone (Xcode, branch `ios-live-dotpad`).
2. Settings (gear) → **DotPad live view** → type the phone URL → Save. The line under it should say
   "Connected to the Mac · DotPad connected".
3. Any of these now shows on the DotPad:
   - **Scan space**: walls appear as you scan; the X follows you, and keeps following after you
     finish the room (same AR session).
   - **Try demo spaces → 3D walkthrough**: the synthetic clinic/library maps, the X moves along the
     simulated route. Safest demo: no LiDAR or relocalization needed.
   - **Start AR navigation** on a saved scan: the saved map and the verified position.

No phone yet? Pretend to be one:

```sh
.venv/bin/python -m app.live.fake_phone "ws://127.0.0.1:8765/phone?token=..." --scan ../sample-data/synthetic-roomplan-capturedroom.json
.venv/bin/python -m app.live.fake_phone "ws://127.0.0.1:8765/phone?token=..." --map ../sample-data/demo-building.json
```

## Network at the venue

The phone must reach the Mac on port 8765.
1. Same Wi-Fi: try it first. Venue Wi-Fi often blocks device-to-device traffic.
2. Join the Mac to the **iPhone's Personal Hotspot**; use the `172.20.10.x` address the bridge prints.
3. Tunnel: `ngrok http 8765` and use `wss://<id>.ngrok-free.app/phone?token=...` (the app sends the
   ngrok skip-warning header).

The token stops other people on the network from drawing on your DotPad. `--no-token` turns it off.

## Messages (for anyone adding another sender)

JSON text frames to `/phone?token=...`. Plan coordinates: x right, y up; ARKit/iOS points map as
(x, z) → (x, −z). Heading: radians clockwise from "up" (ARKit −Z), the iOS app's convention.

```json
{"type": "map", "live": true, "room": {"rooms": [<RoomPlan CapturedRoom JSON>, ...]}}
{"type": "map", "name": "Clinic", "geometry": <iOS MapGeometry>, "doors": [<MapDoor>, ...]}
{"type": "map", "floormap": <FloorMap, as in sample-data/>}
{"type": "pose", "frame": "world", "transform": [16 floats, column-major ARKit camera.transform]}
{"type": "pose", "frame": "map", "x": 1.2, "z": -3.4, "heading": 0.5}
{"type": "pose", "frame": "none"}
```

The bridge replies with `{"type": "status", "dotpad": "connected", "frames_sent": 12, ...}` about once
a second and `{"type": "error", "message": ...}` for a message it can't use.

## Limits (say these in the pitch)

The position is ARKit's estimate and the map is what RoomPlan saw: no live obstacle sensing beyond
that. The DotPad shows a coarse picture (about 10–25 cm per pin for a room). It is a way to feel a
space and follow your position, not a replacement for a cane or guide dog.
