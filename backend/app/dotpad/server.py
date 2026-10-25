"""Dot Pad proxy server (step 2: bridge link and a dev fixture).

Run from backend/:
    python -m uvicorn app.dotpad.server:app --port 8001
Then open http://localhost:8001/bridge in Chrome and connect the Dot Pad.

Bridge link (internal, owned by the proxy team per docs/DOTPAD_API.md):
    WS /v1/bridge/{display_id}
    bridge -> proxy  {"type": "device", "state": "connected", "cellCols": 30, "cellRows": 10}
                     {"type": "device", "state": "disconnected" | "error"}
                     {"type": "key", "key": "KeyFunction1"}
    proxy -> bridge  {"type": "frame", "hex": "...", "cellCols": 30, "cellRows": 10, "zoom": 1}

The iOS session API (/v1/sessions...) is step 3 and will drive the same DisplayState.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from app.dotpad.raster import Pose, render, to_ascii
from app.dotpad.state import DisplayState
from app.models.map import FloorMap

REPO_ROOT = Path(__file__).resolve().parents[3]
STATIC = Path(__file__).resolve().parent / "static"
# The Dot Inc. SDK is not committed to this repo. Point at a local copy of dotpad-sdk-guide.
SDK_JS = Path(
    os.environ.get(
        "DOTPAD_SDK_JS",
        REPO_ROOT / "dotpad-sdk-guide" / "Web" / "3.0.4" / "DemoApp" / "src" / "sdk" / "DotPadSDK-3.0.4.js",
    )
)
FIXTURE_DIR = REPO_ROOT / "sample-data"


class Hub:
    """Display states plus the bridge socket attached to each one."""

    def __init__(self) -> None:
        self.states: dict[str, DisplayState] = {}
        self.bridges: dict[str, WebSocket] = {}

    def state(self, display_id: str) -> DisplayState:
        if display_id not in self.states:
            self.states[display_id] = DisplayState(display_id)
        return self.states[display_id]

    async def push(self, display_id: str) -> None:
        """Send the current frame. Older unsent frames are never queued: only the latest goes out."""
        ws = self.bridges.get(display_id)
        if ws is None:
            return
        s = self.state(display_id)
        msg = {"type": "frame", "hex": s.frame_hex(), "cellCols": s.cell_cols, "cellRows": s.cell_rows, "zoom": s.zoom}
        try:
            await ws.send_text(json.dumps(msg))
        except Exception:  # bridge went away mid-send; its own handler cleans up
            pass


hub = Hub()
router = APIRouter()


# ---------- bridge ----------


@router.get("/bridge")
def bridge_page() -> FileResponse:
    return FileResponse(STATIC / "bridge.html", media_type="text/html")


@router.get("/bridge/sdk.js")
def bridge_sdk() -> FileResponse:
    if not SDK_JS.is_file():
        raise HTTPException(404, f"Dot Pad SDK not found at {SDK_JS}. Set DOTPAD_SDK_JS.")
    return FileResponse(SDK_JS, media_type="text/javascript")


@router.websocket("/v1/bridge/{display_id}")
async def bridge_socket(ws: WebSocket, display_id: str) -> None:
    await ws.accept()
    old = hub.bridges.get(display_id)
    hub.bridges[display_id] = ws
    if old is not None:  # one bridge per display: the newest one wins
        try:
            await old.close(code=4001)
        except Exception:
            pass
    s = hub.state(display_id)
    await hub.push(display_id)
    try:
        while True:
            try:
                msg = json.loads(await ws.receive_text())
            except json.JSONDecodeError:
                continue
            kind = msg.get("type")
            if kind == "device":
                s.device_state = str(msg.get("state", "error"))
                if s.device_state == "connected" and msg.get("cellCols") and msg.get("cellRows"):
                    s.set_board(int(msg["cellCols"]), int(msg["cellRows"]))
                    await hub.push(display_id)  # redraw for the real board size
            elif kind == "key":
                key = msg.get("key")
                if key == "KeyFunction1":
                    s.zoom_in()
                elif key == "KeyFunction2":
                    s.zoom_out()
                else:
                    continue
                await hub.push(display_id)
    except WebSocketDisconnect:
        pass
    finally:
        if hub.bridges.get(display_id) is ws:
            del hub.bridges[display_id]
            s.device_state = "disconnected"


# ---------- dev fixture (stand-in for iOS until step 3) ----------


class FixturePose(BaseModel):
    x: float
    y: float
    headingDeg: float = 0.0


class Fixture(BaseModel):
    mapPath: str | None = None  # relative to sample-data/, e.g. "demo-building.json"
    floorPlan: FloorMap | None = None
    pose: FixturePose | None = None


@router.post("/v1/dev/displays/{display_id}/fixture")
async def load_fixture(display_id: str, body: Fixture) -> dict:
    s = hub.state(display_id)
    if body.floorPlan is not None:
        s.set_map(body.floorPlan)
    elif body.mapPath:
        path = (FIXTURE_DIR / body.mapPath).resolve()
        if FIXTURE_DIR.resolve() not in path.parents or not path.is_file():
            raise HTTPException(422, "mapPath must name a file inside sample-data/")
        s.set_map(FloorMap.model_validate(json.loads(path.read_text(encoding="utf-8"))))
    if s.map is None:
        raise HTTPException(422, "no map loaded yet: send mapPath or floorPlan")
    p = body.pose
    s.set_pose(Pose(p.x, p.y, math.radians(p.headingDeg)) if p else None)
    await hub.push(display_id)
    return {"displayId": display_id, "zoom": s.zoom, "bridgeAttached": display_id in hub.bridges}


@router.post("/v1/dev/displays/{display_id}/key/{key}")
async def press_key(display_id: str, key: str) -> dict:
    """Simulate F1/F2 without the device."""
    s = hub.state(display_id)
    if key == "KeyFunction1":
        s.zoom_in()
    elif key == "KeyFunction2":
        s.zoom_out()
    else:
        raise HTTPException(422, "key must be KeyFunction1 or KeyFunction2")
    await hub.push(display_id)
    return {"zoom": s.zoom}


@router.get("/v1/dev/displays/{display_id}/preview", response_class=PlainTextResponse)
def preview(display_id: str) -> str:
    s = hub.state(display_id)
    if s.map is None:
        return "(no map)"
    head = f"{display_id}  zoom={s.zoom}  device={s.device_state}  board={s.cell_cols}x{s.cell_rows} cells\n"
    return head + to_ascii(render(s.map, s.pin_cols, s.pin_rows, s.zoom, s.center, s.pose))


app = FastAPI(title="TouchSpace Dot Pad proxy")
app.include_router(router)
