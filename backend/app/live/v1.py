"""James's Dot Pad proxy contract (docs/DOTPAD_API.md on ios-app), served by the live bridge.

  POST   /v1/sessions               {displayId, mode} -> 201 {sessionId, wsUrl}
  PUT    /v1/sessions/{id}/map      {mapRevision, coordinateFrameId, floorPlan: FloorMap}
  DELETE /v1/sessions/{id}
  WS     /v1/sessions/{id}/stream   iOS sends poses, gets status/error

HTTP and the WebSocket upgrade need `Authorization: Bearer <pairingToken>`. One display, one
session. F1/F2 on the DotPad zoom in/out through 1, 2, 4, 8.

Choices the contract leaves open, made here for a demo:
* Creating a session while the old one has no open stream replaces it (an app restart must not
  lock the display); with a stream open it is 409 DISPLAY_BUSY, as written.
* `?token=` is accepted as well as the Authorization header.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import secrets
import time
import uuid
from dataclasses import dataclass, field
from threading import RLock
from typing import Any

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from app.models.map import FloorMap

from .output import DotPadOutput, Scene
from .render import ZOOMS
from .scene import Plan, Pose, plan_from_floormap

MAX_SEQ = 2**53 - 1
STALE_S = 2.0
POSE_KEYS = {"type", "seq", "mapRevision", "coordinateFrameId", "tracking", "position", "headingRad"}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message

    def response(self) -> JSONResponse:
        return JSONResponse({"error": {"code": self.code, "message": self.message}}, status_code=self.status)


@dataclass
class Session:
    id: str
    mode: str
    map_revision: str | None = None
    frame_id: str | None = None
    map_digest: str | None = None
    plan: Plan | None = None
    pose: Pose | None = None
    pose_state: str = "none"  # none | valid | lost | stale
    pose_at: float = 0.0
    last_seq: int | None = None
    zoom: int = 1
    center: tuple[float, float] | None = None  # viewport kept when the position goes away
    stream: WebSocket | None = None
    version: int = 0  # bumps on every state change, so streams know when to send status
    extra: dict[str, Any] = field(default_factory=dict)


class ProxyState:
    def __init__(self, output: DotPadOutput, *, token: str | None, display_id: str = "dotpad"):
        self.output = output
        self.token = token
        self.display_id = display_id
        self.session: Session | None = None
        self.lock = RLock()
        self._device_state = None
        output.pad.on_button(self._button)

    # ---- device

    def device_state(self) -> str:
        if self.output.connected:
            return "connected"
        return "error" if self.output.last_error and "timeout" not in self.output.last_error.lower() else "disconnected"

    def _button(self, event) -> None:
        if event.action.value != "down" or event.button.value not in ("function1", "function2"):
            return
        with self.lock:
            s = self.session
            if s is None or s.plan is None:
                return
            i = ZOOMS.index(s.zoom) + (1 if event.button.value == "function1" else -1)
            s.zoom = ZOOMS[min(max(i, 0), len(ZOOMS) - 1)]
            self._changed(s)

    # ---- state

    def _changed(self, s: Session) -> None:
        s.version += 1
        if s.pose is not None:
            s.center = (s.pose.x, s.pose.y)
        pose = s.pose if s.pose_state == "valid" else None
        self.output.show(Scene(plan=s.plan, pose=pose, live=False, zoom=s.zoom, center=s.center))

    def status(self, s: Session) -> dict:
        return {
            "type": "status",
            "mapRevision": s.map_revision,
            "coordinateFrameId": s.frame_id,
            "mapState": "ready" if s.plan is not None else "empty",
            "deviceState": self.device_state(),
            "zoom": s.zoom,
            "poseState": s.pose_state,
            "lastAcceptedSeq": s.last_seq,
        }

    def get(self, session_id: str) -> Session:
        s = self.session
        if s is None or s.id != session_id:
            raise ApiError(404, "SESSION_NOT_FOUND", "No such session. Create one and upload the map again.")
        return s

    def check_token(self, header: str | None, query: str | None) -> None:
        if self.token is None:
            return
        given = header[7:] if header and header.lower().startswith("bearer ") else (query or "")
        if not secrets.compare_digest(given.strip(), self.token):
            raise ApiError(401, "UNAUTHORIZED", "Missing or wrong pairing token.")

    def create(self, body: Any) -> Session:
        if not isinstance(body, dict) or set(body) != {"displayId", "mode"}:
            raise ApiError(422, "INVALID_REQUEST", "Body must be exactly {displayId, mode}.")
        if body["mode"] not in ("live", "walkthrough"):
            raise ApiError(422, "INVALID_REQUEST", 'mode must be "live" or "walkthrough".')
        if body["displayId"] != self.display_id:
            raise ApiError(404, "DISPLAY_NOT_FOUND", f"This bridge drives display {self.display_id!r}.")
        with self.lock:
            if self.session is not None and self.session.stream is not None:
                raise ApiError(409, "DISPLAY_BUSY", "Another session is streaming to this display.")
            self.session = Session(id=uuid.uuid4().hex, mode=body["mode"])
            self.output.show(Scene(plan=None, pose=None, live=False))
            return self.session

    def put_map(self, s: Session, body: Any) -> dict:
        if not isinstance(body, dict) or set(body) != {"mapRevision", "coordinateFrameId", "floorPlan"}:
            raise ApiError(422, "INVALID_REQUEST", "Body must be exactly {mapRevision, coordinateFrameId, floorPlan}.")
        rev, frame, raw = body["mapRevision"], body["coordinateFrameId"], body["floorPlan"]
        if not (isinstance(rev, str) and rev and isinstance(frame, str) and frame):
            raise ApiError(422, "INVALID_REQUEST", "mapRevision and coordinateFrameId must be nonempty strings.")
        if not isinstance(raw, dict) or raw.get("schema_version") != "1.0" or raw.get("units") != "meters":
            raise ApiError(422, "INVALID_REQUEST", 'floorPlan needs schema_version "1.0" and units "meters".')
        try:
            fmap = FloorMap.model_validate(raw)
        except ValidationError as exc:
            raise ApiError(422, "INVALID_REQUEST", f"floorPlan is not a valid FloorMap: {exc.errors()[0]['msg']}") from None
        walls = {w.id for w in fmap.walls}
        for g in [*fmap.doors, *fmap.openings]:
            if not g.wall_id or g.wall_id not in walls:
                raise ApiError(422, "INVALID_REQUEST", f"Door/opening {g.id!r} needs the wall_id of an existing wall.")
        digest = hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()
        with self.lock:
            if s.map_revision == rev:
                if s.frame_id != frame or s.map_digest != digest:
                    raise ApiError(409, "REVISION_CONFLICT", "This mapRevision was already used for different content.")
                return {"mapRevision": rev, "coordinateFrameId": frame, "state": "ready"}
            if rev in s.extra.setdefault("revisions", {}) and s.extra["revisions"][rev] != (frame, digest):
                raise ApiError(409, "REVISION_CONFLICT", "This mapRevision was already used for different content.")
            s.extra["revisions"][rev] = (frame, digest)
            s.map_revision, s.frame_id, s.map_digest = rev, frame, digest
            s.plan = plan_from_floormap(fmap)
            s.pose, s.pose_state, s.zoom, s.center = None, "none", 1, None
            self._changed(s)
        return {"mapRevision": rev, "coordinateFrameId": frame, "state": "ready"}

    def delete(self, s: Session) -> None:
        with self.lock:
            self.session = None
            self.output.show(Scene(plan=None, pose=None, live=False))

    def pose(self, s: Session, raw: str) -> dict | None:
        """Apply one stream frame. Returns a StreamError to send, or None."""
        try:
            msg = json.loads(raw)
        except ValueError:
            return _err("INVALID_REQUEST", "Not JSON.", None)
        seq = msg.get("seq") if isinstance(msg, dict) else None
        seq = seq if isinstance(seq, int) and not isinstance(seq, bool) else None
        if not isinstance(msg, dict) or msg.get("type") != "pose" or set(msg) != POSE_KEYS:
            return _err("INVALID_REQUEST", f"Expected a pose with exactly {sorted(POSE_KEYS)}.", seq)
        if seq is None or not 1 <= seq <= MAX_SEQ:
            return _err("INVALID_REQUEST", "seq must be a positive integer.", None)
        tracking, position, heading = msg["tracking"], msg["position"], msg["headingRad"]
        if tracking == "valid":
            ok = (isinstance(position, dict) and set(position) == {"x", "y"}
                  and all(_finite(position[k]) for k in ("x", "y")) and _finite(heading) and 0 <= heading < 2 * math.pi)
            if not ok:
                return _err("INVALID_REQUEST", "A valid pose needs a finite position {x, y} and headingRad in [0, 2π).", seq)
        elif tracking != "lost" or position is not None or heading is not None:
            return _err("INVALID_REQUEST", 'tracking must be "valid", or "lost" with null position and headingRad.', seq)
        with self.lock:
            if s.plan is None:
                return _err("MAP_NOT_READY", "Upload the map before sending poses.", seq)
            if msg["mapRevision"] != s.map_revision or msg["coordinateFrameId"] != s.frame_id:
                return _err("MAP_MISMATCH", "Pose is for a different map revision or coordinate frame.", seq)
            if s.last_seq is not None and seq <= s.last_seq:
                return None  # old or repeated: drop silently
            s.last_seq = seq
            s.pose_at = time.monotonic()
            if tracking == "valid":
                s.pose, s.pose_state = Pose(float(position["x"]), float(position["y"]), float(heading)), "valid"
            else:
                s.pose, s.pose_state = None, "lost"
            self._changed(s)
        return None

    def expire(self, s: Session) -> None:
        with self.lock:
            if s.pose_state == "valid" and time.monotonic() - s.pose_at > STALE_S:
                s.pose, s.pose_state = None, "stale"
                self._changed(s)


def _finite(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _err(code: str, message: str, seq: int | None) -> dict:
    return {"type": "error", "code": code, "message": message, "seq": seq}


def create_router(proxy: ProxyState) -> APIRouter:
    router = APIRouter(prefix="/v1")

    async def body_of(request: Request) -> Any:
        try:
            return await request.json()
        except ValueError:
            raise ApiError(422, "INVALID_REQUEST", "Body must be JSON.") from None

    def auth(request: Request) -> None:
        proxy.check_token(request.headers.get("authorization"), request.query_params.get("token"))

    @router.post("/sessions")
    async def create_session(request: Request):
        try:
            auth(request)
            s = proxy.create(await body_of(request))
        except ApiError as exc:
            return exc.response()
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        ws = "wss" if proto == "https" else "ws"
        host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
        return JSONResponse({"sessionId": s.id, "wsUrl": f"{ws}://{host}/v1/sessions/{s.id}/stream"}, status_code=201)

    @router.put("/sessions/{session_id}/map")
    async def put_map(session_id: str, request: Request):
        try:
            auth(request)
            return JSONResponse(proxy.put_map(proxy.get(session_id), await body_of(request)))
        except ApiError as exc:
            return exc.response()

    @router.delete("/sessions/{session_id}")
    async def delete_session(session_id: str, request: Request):
        try:
            auth(request)
            s = proxy.get(session_id)
        except ApiError as exc:
            return exc.response()
        stream = s.stream
        proxy.delete(s)
        if stream is not None:
            try:
                await stream.close(code=1000)
            except RuntimeError:
                pass
        return Response(status_code=204)

    @router.websocket("/sessions/{session_id}/stream")
    async def stream(ws: WebSocket, session_id: str):
        try:
            proxy.check_token(ws.headers.get("authorization"), ws.query_params.get("token"))
            s = proxy.get(session_id)
        except ApiError as exc:
            await ws.close(code=1008, reason=exc.code)
            return
        await ws.accept()
        old, s.stream = s.stream, ws
        if old is not None:
            try:
                await old.close(code=4001, reason="replaced by a new connection")
            except RuntimeError:
                pass
        sent_version, sent_device, last = -1, None, 0.0
        try:
            while proxy.session is s and s.stream is ws:
                try:
                    raw = await asyncio.wait_for(ws.receive_text(), timeout=0.25)
                except asyncio.TimeoutError:
                    raw = None
                if raw is not None:
                    error = proxy.pose(s, raw)
                    if error:
                        await ws.send_json(error)
                proxy.expire(s)
                device = proxy.device_state()
                now = time.monotonic()
                if s.version != sent_version or device != sent_device or now - last >= 1.0:
                    await ws.send_json(proxy.status(s))
                    sent_version, sent_device, last = s.version, device, now
        except WebSocketDisconnect:
            pass
        finally:
            if s.stream is ws:
                s.stream = None

    return router
