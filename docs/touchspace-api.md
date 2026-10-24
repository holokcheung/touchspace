# Touchspace AI backend

The indoor exploration feature lives in `backend/app/touchspace/`. It reuses the FastAPI application, dependency-injection conventions, configured `TOUCHSPACE_DATA_DIR`, atomic file-writing helper, CORS configuration, and error envelope. The legacy `/api/scans`, `/api/maps`, and STL endpoints are preserved. There is no second backend.

The existing repository has no account/auth implementation or metadata DB. This MVP therefore uses a **single operator upload guard** (`TOUCHSPACE_UPLOAD_TOKEN`, at least 24 random characters), a stable catalog-operator owner, and feature-local SQLite metadata migrations. It does not introduce a user-registration service. Anyone holding that credential can manage/access the operator's private uploads. Rotate it without changing map ownership. Public browsing/downloads are read-only and need no token. Private map details, download, and chat return 404 without the upload credential. Missing/short server credentials disable upload with 503; incorrect/missing client credentials return 401. iOS stores its upload credential in Keychain.

Packages live at `<TOUCHSPACE_DATA_DIR>/touchspace/packages/<sha256>.touchspacemap`. `catalog.sqlite3` stores manifest metadata, visibility, owner, schema version, SHA-256, byte size, storage key, publication date, and warnings. Startup applies `migrations.sql`. Existing IDs are immutable for different content; a new scan/revision must use a new map ID. Re-uploading identical content can change visibility, and every public upload requires consent. Chat sessions retain only the last resolved stable ID for 30 minutes, scoped to map/session/caller group; neither transcripts nor continuous poses are stored.

| Request | Behavior |
| --- | --- |
| `GET /api/touchspace/maps?q=venue` | Search up to 100 public manifests by title/coverage. No map geometry, poses, or world data. |
| `POST /api/touchspace/maps` | Multipart `file`, optional `visibility=private` (default), `publication_consent=false` (default). Bearer upload guard required. |
| `GET /api/touchspace/maps/{id}` | Manifest, visibility, checksum, byte size, warnings, `worldDataStatus`. Public or authorized private access. |
| `GET /api/touchspace/maps/{id}/download` | Original complete ZIP, including saved world data. SHA-256 integrity check, ETag, no-store cache policy. |
| `POST /api/touchspace/chat` | Grounded map question; request/response below. Same access rules as the map. |

Interactive contracts and generated input/output schemas: `/docs` and `/openapi.json` on the running server. Errors use `{"error":{"code":"…","message":"…","details":null}}`.

```json
{
  "mapId": "touchspace-demo",
  "sessionId": "e26e689c-d909-4b18-ae44-f6d0d88b9a01",
  "message": "how are the rooms connected?",
  "pose": null
}
```

`pose`, when supplied, carries `coordinateFrameId`, `position:{x,z}`, `heading` in radians, `tracking` (`localized`, `relocalizing`, `limited`, `failed`), `frameVerified`, and an ISO-8601 `timestamp`. Pose-dependent operations require a matching saved frame, verified localization, a timestamp at most 10 seconds old, and a position inside surveyed rooms. The server validates the client's claim; physical localization is ARKit's responsibility on the phone.

```json
{
  "sessionId": "e26e689c-d909-4b18-ae44-f6d0d88b9a01",
  "reply": "Gallery doorway connects Lobby and Gallery. Volunteer marked traversable at scan time; current conditions are unknown.",
  "sourceIds": ["gallery-door"],
  "action": null,
  "interpreter": "local-fallback",
  "toolResults": [{
    "operation": "room_connections",
    "sourceIds": ["gallery-door"],
    "data": {"connections": []},
    "error": null
  }],
  "poseUsed": false
}
```

The connections array above is abbreviated; actual responses include deterministic door records. Route results include node IDs, waypoints, and measured meters. The only structured action is `{"type":"destination","destinationId":"<recorded landmark>"}`. iOS validates that ID, selects the destination, and requires the user to start/recalculate a route locally. It never executes free-form reply text as navigation.

Set `TOUCHSPACE_GEMINI_API_KEY` (or the existing `GEMINI_API_KEY` if the feature-specific variable is empty or absent) to enable backend-hosted Gemini intent interpretation. `TOUCHSPACE_GEMINI_MODEL` selects the provider model (default `gemini-3.8-flash`). No provider key is shipped in the app. Gemini receives the submitted question, entity IDs/names/types, and prior target ID; deterministic code receives the current pose. The model can only choose one of `get_pose`, `list_rooms`, `nearby_landmarks`, `relative_direction`, `room_connections`, `get_route`, `route_summary`, `get_map_overview`, or `unknown`. It cannot return reply text, routes, coordinates, or distances. Model selections are schema/ID validated; answers and source measurements come from deterministic tools. Unknown properties remain unknown. Provider failures/timeouts fall back to a bounded local intent parser, reported in `interpreter`. Local waypoint guidance never calls the LLM.

Uploads accept `.touchspacemap` or `.zip`, bounded to 64 MiB (including expanded ZIP contents). Feature middleware checks declared and chunked multipart body size before parsing/spooling. Public uploads require explicit consent and structurally valid world data. `worldDataStatus=present-unverified` means the server has inspected the archive structure, **not** that a device has successfully decoded or relocalized it. iOS securely decodes and checks the saved anchor before accepting real world data. Drafts without world data can be uploaded privately but cannot appear as live community maps.

The upload guard is appropriate to this repository's MVP, not a multi-tenant identity/authorization system. Deployment should supply HTTPS and normal platform request/concurrency limits. No continuous obstacle sensing, door-state sensing, multi-floor navigation, cross-session stitching, moderation UI, or cloud publication is implemented.

Implementation references: [Apple RoomPlan session continuity](https://developer.apple.com/documentation/roomplan/scanning-the-rooms-of-a-single-structure), [Apple world-map persistence](https://developer.apple.com/documentation/arkit/saving-and-loading-world-data), [Gemini structured output](https://ai.google.dev/gemini-api/docs/generate-content/structured-output), [current model availability](https://ai.google.dev/gemini-api/docs/deprecations).
