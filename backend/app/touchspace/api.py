from __future__ import annotations

import secrets
from functools import lru_cache
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from .config import TouchspaceSettings, get_touchspace_settings
from .models import CatalogResponse, ChatRequest, ChatResponse
from .package import MAX_BYTES, PackageError, validate_package
from .storage import Catalog, CatalogError

router = APIRouter(prefix='/api/touchspace', tags=['Touchspace AI indoor exploration'])


@lru_cache
def get_catalog() -> Catalog:
    # Reuse the established data root, file-writing helpers, and dependency-injection pattern.
    from app.main import get_settings
    return Catalog(get_settings().data_dir / 'touchspace')


def authorized_owner(authorization: str | None = Header(None), settings: TouchspaceSettings = Depends(get_touchspace_settings)) -> str | None:
    token = authorization.removeprefix('Bearer ') if authorization and authorization.startswith('Bearer ') else ''
    if len(settings.upload_token) >= 24 and token and secrets.compare_digest(token.encode(), settings.upload_token.encode()):
        # One existing-project upload guard, with a stable owner across credential rotation.
        return 'catalog-operator'
    return None


def require_owner(owner: str | None = Depends(authorized_owner), settings: TouchspaceSettings = Depends(get_touchspace_settings)) -> str:
    if len(settings.upload_token) < 24:
        raise HTTPException(503, 'Uploads are disabled. Configure TOUCHSPACE_UPLOAD_TOKEN with at least 24 random characters.')
    if owner is None:
        raise HTTPException(401, 'An authorized upload token is required.', headers={'WWW-Authenticate': 'Bearer'})
    return owner


def lookup(catalog: Catalog, map_id: str, owner: str | None):
    try:
        return catalog.lookup(map_id, owner)
    except KeyError:
        raise HTTPException(404, 'Map not found or private.') from None


@router.get('/maps', response_model=list[CatalogResponse])
def maps(q: str = Query('', max_length=200), catalog: Catalog = Depends(get_catalog)):
    return catalog.search(q.strip())


@router.post('/maps', status_code=201, response_model=CatalogResponse)
async def upload(file: UploadFile = File(...), visibility: Literal['private', 'public'] = Form('private'),
                 publication_consent: bool = Form(False), owner: str = Depends(require_owner), catalog: Catalog = Depends(get_catalog)):
    name = (file.filename or '').lower()
    if not name.endswith(('.touchspacemap', '.zip')) or file.content_type not in ('application/zip', 'application/octet-stream', 'application/x-zip-compressed', 'application/vnd.touchspace.map'):
        raise HTTPException(415, 'Upload a Touchspace map ZIP package.')
    if visibility == 'public' and not publication_consent:
        raise HTTPException(422, 'Public sharing requires explicit publication consent.')
    raw = await file.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise HTTPException(413, 'Packages must be at most 64 MiB.')
    try:
        package = await run_in_threadpool(validate_package, raw)
        if visibility == 'public' and not package.world_data:
            raise PackageError('Map-only drafts cannot be published as live-navigable community maps. Upload privately or rescan with world data.')
        return await run_in_threadpool(catalog.save, package, raw, owner=owner, visibility=visibility)
    except PackageError as exc:
        raise HTTPException(422, str(exc)) from None
    except CatalogError as exc:
        raise HTTPException(409, str(exc)) from None


@router.get('/maps/{map_id}', response_model=CatalogResponse)
def details(map_id: str, owner: str | None = Depends(authorized_owner), catalog: Catalog = Depends(get_catalog)):
    return catalog.response(lookup(catalog, map_id, owner))


@router.get('/maps/{map_id}/download')
def download(map_id: str, owner: str | None = Depends(authorized_owner), catalog: Catalog = Depends(get_catalog)):
    row = lookup(catalog, map_id, owner)
    try:
        # Verify storage integrity before returning the complete original package.
        catalog.load(map_id, owner)
        path = catalog.path(row)
    except (CatalogError, PackageError) as exc:
        raise HTTPException(409, str(exc)) from None
    return FileResponse(path, media_type='application/zip', filename=f'{map_id}.touchspacemap',
                        headers={'Cache-Control': 'no-store', 'ETag': '"'+row['checksum']+'"'})


@router.post('/chat', response_model=ChatResponse)
async def chat(body: ChatRequest, owner: str | None = Depends(authorized_owner), catalog: Catalog = Depends(get_catalog), settings: TouchspaceSettings = Depends(get_touchspace_settings)):
    from .chat import answer
    lookup(catalog, body.mapId, owner)
    try:
        package = await run_in_threadpool(catalog.load, body.mapId, owner)
        return await answer(body, package, catalog, owner or 'anonymous', settings)
    except (CatalogError, PackageError) as exc:
        raise HTTPException(409, str(exc)) from None
