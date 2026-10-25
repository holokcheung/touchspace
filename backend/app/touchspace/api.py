"""Native app endpoints, isolated from the original scan/print API."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from collections import defaultdict, deque
from functools import lru_cache
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from .auth import issue, owner
from .chat import ChatService, ChatUnavailable, MessagesProvider, ProviderConfig
from .models import ChatRequest, ChatResponse, Model
from .package import MAX_PACKAGE, PackageError, validate_package
from .spatial import SpatialError
from .storage import Catalog

router = APIRouter(prefix="/api/touchspace", tags=["TouchSpace AR"])


@lru_cache
def get_catalog():
    repo = Path(__file__).resolve().parents[3]
    root = Path(os.environ.get("TOUCHSPACE_DATA_DIR", repo / "backend" / "data"))
    return Catalog(root if root.is_absolute() else repo / root)


@lru_cache
def get_chat():
    return ChatService(MessagesProvider(ProviderConfig.from_env()))


_budgets = defaultdict(deque)


def budget(request: Request, kind: str, limit: int):
    key = (request.client.host if request.client else "unknown", kind)
    now = time.monotonic()
    # Keep this demo limiter bounded even when source addresses change.
    if len(_budgets) > 10000:
        _budgets.clear()
    queue = _budgets[key]
    while queue and now-queue[0] > 60:
        queue.popleft()
    if len(queue) >= limit:
        raise HTTPException(429, "Please wait before trying again")
    queue.append(now)


class PairRequest(Model):
    code: str = Field(min_length=1, max_length=200)
    installation_id: UUID


@router.post("/publishing/session")
def pair(body: PairRequest, request: Request):
    budget(request, "pair", 6)
    return issue(body.code, str(body.installation_id))


@router.get("/maps")
def search(q: str = ""):
    if len(q) > 200:
        raise HTTPException(422, "Search query is too long")
    return get_catalog().search(q)


def load(map_id, authorization):
    try:
        # Public browsing remains available even after a demo upload token expires.
        return get_catalog().load(str(map_id))
    except KeyError:
        pass
    try:
        return get_catalog().load(str(map_id), owner(authorization))
    except KeyError:
        raise HTTPException(404, "Map not found") from None


@router.get("/maps/{map_id}")
def detail(map_id: UUID, authorization: str | None = Header(default=None)):
    package, _, visibility = load(map_id, authorization)
    return {"manifest": package.manifest.model_dump(mode="json", by_alias=True), "visibility": visibility}


@router.get("/maps/{map_id}/download")
def download(map_id: UUID, authorization: str | None = Header(default=None)):
    package, path, _ = load(map_id, authorization)
    return FileResponse(path, media_type="application/vnd.touchspace.map+zip", filename=f"{package.manifest.id}.touchspacemap")


@router.post("/maps", status_code=201)
async def upload(request: Request, file: UploadFile = File(), visibility: str = Form("private"),
                 publication_consent: bool = Form(False), authorization: str | None = Header(default=None)):
    identity = owner(authorization)
    if identity is None:
        raise HTTPException(401, "Pair with the server before uploading")
    budget(request, "upload", 10)
    if visibility not in ("private", "public"):
        raise HTTPException(422, "Visibility must be private or public")
    if visibility == "public" and not publication_consent:
        raise HTTPException(422, "Public maps require explicit publication consent")
    try:
        raw = await file.read(MAX_PACKAGE+1)
    finally:
        await file.close()
    if len(raw) > MAX_PACKAGE:
        raise HTTPException(413, "Package exceeds 64 MB")
    try:
        package = await run_in_threadpool(validate_package, raw)
        saved = get_catalog().save(package, identity, visibility)
        return {"manifest": saved.manifest.model_dump(mode="json", by_alias=True), "visibility": visibility}
    except PackageError as exc:
        raise HTTPException(422, str(exc)) from None
    except sqlite3.IntegrityError:
        raise HTTPException(409, "This map ID already exists. Packages are immutable; create a new scan revision.") from None


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest, request: Request, authorization: str | None = Header(default=None)):
    budget(request, "chat", 20)
    if body.map_package is not None:
        # Imported/demo maps need not be published. Context is validated but never saved.
        package = body.map_package
        canonical = json.dumps(package.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        identity = "inline:" + hashlib.sha256(canonical.encode()).hexdigest()
    else:
        package, _, visibility = load(body.map_id, authorization)
        identity = owner(authorization) if visibility == "private" else None
    try:
        return await get_chat().answer(package, body, identity)
    except ChatUnavailable as exc:
        raise HTTPException(503, str(exc)) from None
    except SpatialError as exc:
        raise HTTPException(422, str(exc)) from None
