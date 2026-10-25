"""WebSocket endpoint the iPhone streams to, and the state it feeds to the DotPad.

Protocol (JSON text frames to ws://<mac>:8765/phone?token=<token>):

  {"type": "hello", "client": "TouchSpace iOS 1.0"}
  {"type": "map", "room": {...RoomPlan CapturedRoom...}, "live": true}   live scan, ARKit world frame
  {"type": "map", "geometry": {...MapGeometry...}, "doors": [...], "name": "Clinic"}   saved iOS map
  {"type": "map", "floormap": {...FloorMap...}}                          web app / sample-data format
  {"type": "pose", "frame": "world", "transform": [16 floats, column-major]}   ARKit camera.transform
  {"type": "pose", "frame": "map", "x": 1.2, "z": -3.4, "heading": 0.5}        iOS VerifiedPose
  {"type": "pose", "frame": "none"}                                      tracking lost: hide the X

The server answers with {"type": "status", ...} about once a second, and {"type": "error"} for a
message it could not use (the connection stays open).
"""

from __future__ import annotations

import asyncio
import json
import secrets
import time
from threading import Lock

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .output import DotPadOutput, Scene
from .scene import Plan, Pose, plan_from_message, pose_from_message

MAX_MESSAGE_BYTES = 4 * 1024 * 1024
# Hide the X when the phone stops reporting a position.
POSE_TIMEOUT_S = 4.0


class LiveState:
    def __init__(self, output: DotPadOutput, plan: Plan | None = None):
        self.output = output
        self.plan = plan
        self.live = False
        self.pose: Pose | None = None
        self.pose_at = 0.0
        self.client: str | None = None
        self.messages = 0
        self._lock = Lock()
        self._push()

    def handle(self, msg: dict) -> None:
        kind = msg.get("type")
        with self._lock:
            if kind == "hello":
                self.client = str(msg.get("client") or "phone")[:80]
                return
            if kind == "map":
                self.plan = plan_from_message(msg)
                self.live = bool(msg.get("live", "room" in msg))
            elif kind == "pose":
                self.pose = pose_from_message(msg)
                self.pose_at = time.monotonic()
            else:
                raise ValueError('"type" must be hello, map or pose')
            self.messages += 1
            self._push()

    def expire_pose(self) -> None:
        with self._lock:
            if self.pose is not None and time.monotonic() - self.pose_at > POSE_TIMEOUT_S:
                self.pose = None
                self._push()

    def _push(self) -> None:
        self.output.show(Scene(plan=self.plan, pose=self.pose, live=self.live))

    def status(self) -> dict:
        with self._lock:
            return {
                "type": "status",
                "dotpad": "connected" if self.output.connected else "waiting",
                "dotpad_error": self.output.last_error,
                "frames_sent": self.output.frames_sent,
                "map": self.plan.name if self.plan else None,
                "walls": len(self.plan.walls) if self.plan else 0,
                "has_pose": self.pose is not None,
                "messages": self.messages,
            }


def create_app(state: LiveState, token: str | None) -> FastAPI:
    app = FastAPI(title="TouchSpace live DotPad bridge")

    @app.get("/status")
    def status() -> dict:
        return state.status()

    @app.websocket("/phone")
    async def phone(ws: WebSocket):
        if token is not None and not secrets.compare_digest(ws.query_params.get("token", ""), token):
            await ws.close(code=1008, reason="wrong token")
            return
        await ws.accept()
        await ws.send_json(state.status())
        last_status = time.monotonic()
        try:
            while True:
                try:
                    raw = await asyncio.wait_for(ws.receive_text(), timeout=1.0)
                except asyncio.TimeoutError:
                    raw = None
                if raw is not None:
                    try:
                        if len(raw) > MAX_MESSAGE_BYTES:
                            raise ValueError("message too large")
                        msg = json.loads(raw)
                        if not isinstance(msg, dict):
                            raise ValueError("expected a JSON object")
                        state.handle(msg)
                    except Exception as exc:  # bad input must not drop the phone
                        await ws.send_json({"type": "error", "message": str(exc)[:300]})
                state.expire_pose()
                if time.monotonic() - last_status >= 1.0:
                    await ws.send_json(state.status())
                    last_status = time.monotonic()
        except WebSocketDisconnect:
            pass

    return app
