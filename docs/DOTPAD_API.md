# Dot Pad proxy contract (v1 proposal)

Dot Pad displays refreshable tactile graphics and Braille. Its [Web SDK](https://github.com/dotincorp/dotpad-sdk-guide/blob/main/Web/3.0.3/README.md) runs in Chrome/Chromium using Web Bluetooth or Web Serial, supports graphics output and button callbacks, and reports device layout. A browser bridge must run on the computer connected to the display; a backend process alone cannot use this SDK.

## Design and data flow

```text
iOS -- HTTPS map upload; WebSocket poses --> Proxy
                                              |
                                 map + pose + viewport -> dot array
                                              |
                                              v
                                        Browser bridge
                                              | Web SDK (BLE/USB)
                                              v
                                           Dot Pad

Dot Pad buttons -> bridge -> proxy changes zoom -> redraw
```

- iOS owns geometry, localization, and real/simulated pose. AR world-map data stays on iOS.
- Proxy owns map validation, rasterization, marker/orientation overlay, viewport, zoom, and session/device state.
- Bridge owns device connection, SDK packing/output, button forwarding, and device completion/error reporting. Its internal transport belongs to the proxy team.
- One session controls one paired display. Initial view fits the whole map with map-up fixed. F1/F2 increase/decrease zoom through `1, 2, 4, 8`; zoomed views follow the latest valid position, clamped to map bounds. Without a valid position, retain the viewport. New maps reset zoom to 1.
- Render position as a distinct marker plus a heading indicator. Coalesce pending renders to the latest state and pace writes to device completion. Discover display dimensions through the SDK rather than assuming a model.

## Conventions and shared schemas

Base path `/v1`; HTTPS/WSS in hosted deployments. HTTP JSON uses `Content-Type: application/json`. HTTP requests and the iOS WebSocket upgrade use `Authorization: Bearer <pairingToken>`. Provision the token and `displayId` during setup; pairing UI/API is outside this contract. Tokens authorize only their paired display and sessions.

Schemas below use TypeScript notation: all fields required unless marked `?`; `null` is explicit. IDs/revisions are nonempty opaque strings, numbers must be finite, and `seq` is a positive integer no greater than `2^53 - 1`. Reject unknown envelope fields/types; floor-plan fields follow the existing model.

- Geometry and poses share map-local meters: `+x` right, `+y` up on the plan. Map-up need not be geographic north.
- `headingRad` is clockwise from map-up in `[0, 2π)`: 0 up, π/2 right. It represents phone facing in live mode and virtual camera facing in walkthrough mode.
- iOS converts map-local `(x,z)` to `(x,y) = (x,-z)` and normalizes heading. Apply saved-map alignment before sending live AR poses.
- `coordinateFrameId` identifies the shared origin/axes; `mapRevision` identifies immutable geometry. Never reuse a revision for different geometry or a different frame.

```ts
type Point = { x: number; y: number };
type Mode = "live" | "walkthrough";
type Zoom = 1 | 2 | 4 | 8;
type ErrorCode =
  | "UNAUTHORIZED" | "SESSION_NOT_FOUND" | "DISPLAY_NOT_FOUND"
  | "DISPLAY_BUSY" | "INVALID_REQUEST" | "REVISION_CONFLICT"
  | "MAP_NOT_READY" | "MAP_MISMATCH" | "DEVICE_ERROR" | "INTERNAL_ERROR";
type ApiError = { error: { code: ErrorCode; message: string } };
```

`FloorMap` reuses the complete [existing Pydantic schema](../backend/app/models/map.py), including its defaults and validation; require `schema_version: "1.0"` and `units: "meters"` for this API. Required fields are `id`, `name`, and `source.kind` (`synthetic | roomplan | manual`). Rendering fields:

| Field | Shape (arrays default to `[]`) |
|---|---|
| `walls` | `{id, start: Point, end: Point, thickness?: number}`; thickness defaults to 0.15 m |
| `doors`, `openings` | `{id, position: Point, width: number, wall_id?: string \| null}`; position is gap center, width is along wall |
| `landmarks` | `{id, name, type, position: Point, show_on_tactile?: boolean}`; visibility defaults to true |
| `objects`, `rooms`, other optional fields | Exact shapes in the linked model; objects render only when `include_in_tactile=true` and `hidden=false` |

Landmark `type`: `entrance | exit | restroom | stairs | elevator | information | room | hallway | other`. Supply `wall_id` for every rendered door/opening; validate that the wall exists. Object `rotation` retains the existing model's radians counterclockwise from +x convention, distinct from pose heading. Physical print settings in `tactile` do not control display zoom.

Minimal valid `FloorMap` example:

```json
{
  "schema_version": "1.0", "id": "map-1", "name": "Demo room",
  "units": "meters", "source": {"kind": "synthetic"},
  "walls": [{"id": "w1", "start": {"x": 0, "y": 0}, "end": {"x": 5, "y": 0}}]
}
```

## HTTP endpoints

`{id}` is the `sessionId` returned by creation. All error bodies use `ApiError`.

| Endpoint | Request schema | Success schema |
|---|---|---|
| `POST /sessions` | `{displayId: string, mode: Mode}` | **201** `{sessionId: string, wsUrl: string}`; absolute WSS URL below |
| `PUT /sessions/{id}/map` | `{mapRevision: string, coordinateFrameId: string, floorPlan: FloorMap}` | **200** `{mapRevision: string, coordinateFrameId: string, state: "ready"}` |
| `DELETE /sessions/{id}` | No body | **204**, no body; clear output, release display, close stream with 1000 |

- Common failures: **401** `UNAUTHORIZED`, **404** `SESSION_NOT_FOUND`, **422** `INVALID_REQUEST`, **500** `INTERNAL_ERROR`.
- Create additionally returns **404** `DISPLAY_NOT_FOUND` or **409** `DISPLAY_BUSY`. A known disconnected display may still get a session.
- Map upload atomically replaces the active map after validation; failure preserves the previous map. Repeating the same revision/frame/content succeeds without resetting state; conflicting reuse returns **409** `REVISION_CONFLICT`.
- A new revision clears the pose, resets zoom, and emits status. `ready` means available for rendering, independently of device connection; it does not confirm physical output.

## iOS WebSocket: `/v1/sessions/{id}/stream`

Upgrade returns **101** or an HTTP error above. Frames are UTF-8 JSON objects. One active iOS stream per session; a new connection replaces the old one (close code 4001). Server sends a status snapshot immediately on connection, on state changes, and at least once per second. Use WebSocket ping/pong for transport keepalive; no application heartbeat message.

### iOS → proxy

```ts
type Pose = {
  type: "pose";
  seq: number;
  mapRevision: string;
  coordinateFrameId: string;
} & (
  | { tracking: "valid"; position: Point; headingRad: number }
  | { tracking: "lost"; position: null; headingRad: null }
);
```

Send up to 5 Hz, including while stationary. Wait for map acceptance first. `mode` comes from the session, so a simulated pose cannot implicitly become a live pose.

### Proxy → iOS

```ts
type Status = {
  type: "status";
  mapRevision: string | null;
  coordinateFrameId: string | null;
  mapState: "empty" | "ready";
  deviceState: "disconnected" | "connecting" | "connected" | "error";
  zoom: Zoom;
  poseState: "none" | "valid" | "lost" | "stale";
  lastAcceptedSeq: number | null;
};
type StreamError = {
  type: "error";
  code: ErrorCode;
  message: string;
  seq: number | null; // offending pose sequence, if available
};
type ServerMessage = Status | StreamError;
```

- Initially map/frame/sequence are null, map state is `empty`, pose state is `none`, and zoom is 1. Sequence state persists across map replacement and stream reconnection.
- Reject poses before map upload (`MAP_NOT_READY`), with mismatched revision/frame (`MAP_MISMATCH`), or invalid fields/JSON (`INVALID_REQUEST`). Errors leave the accepted state intact and the stream open.
- Discard `seq <= lastAcceptedSeq` silently. Only an accepted pose advances the sequence and refreshes freshness; acknowledgement means accepted, not physically displayed.
- After two seconds without an accepted pose, mark a previously valid pose `stale` and hide its marker/heading. A `lost` pose hides them immediately. Retain the floor plan.
- On reconnect, continue increasing `seq` and send only the current pose. If sequence state is lost, read `lastAcceptedSeq` from the initial snapshot and use a higher value. Never replay queued movement. Missing sessions require creation and map upload again.
- On device reconnect, render the latest map/viewport and any still-valid pose. Button events change proxy zoom only; iOS receives the resulting status.

## Parallel implementation

The iOS team implements session/map requests and pose streaming against a mock proxy. The proxy team implements these schemas, a dot-grid preview, and the SDK bridge against a replayed map/pose fixture.
