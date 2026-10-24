"""TouchSpace AI HTTP API.

Run locally:  uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from app.models.map import FloorMap, SourceInfo, ValidationIssue
from app.models.tactile import TactileReport, TactileSettings
from app.services.assistant import AskContext, AskResult, answer
from app.services.floorplan import FloorPlanError, process_map, validate_map
from app.services.gemini import GeminiConfig, GeminiInterpreter
from app.services.importers import ImportError_, import_scan
from app.services.routing import SAFETY_NOTE, RouteResult, RoutingError, plan_route
from app.services.storage import MapNotFound, MapStore, map_revision, new_map_id
from app.services.tactile import TactileGenerationError, export_stl, generate_tactile_model, stl_filename
from app.services.voice import MAX_TTS_CHARS, CartesiaVoice, VoiceConfig, VoiceUnavailable

VERSION = "0.4.0"
REPO_ROOT = Path(__file__).resolve().parents[2]
MAX_UPLOAD_BYTES = 15 * 1024 * 1024


def _load_dotenv(path: Path) -> None:
    """Read KEY=value lines from the repo's .env without overriding real environment variables."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


_load_dotenv(REPO_ROOT / ".env")


# --------------------------------------------------------------------------- config / dependencies


class Settings(BaseModel):
    data_dir: Path
    demo_path: Path
    roomplan_sample_path: Path
    cors_origins: list[str]


@lru_cache
def get_settings() -> Settings:
    data_dir = Path(os.environ.get("TOUCHSPACE_DATA_DIR", REPO_ROOT / "backend" / "data"))
    if not data_dir.is_absolute():
        data_dir = REPO_ROOT / data_dir
    origins = os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    return Settings(
        data_dir=data_dir,
        demo_path=REPO_ROOT / "sample-data" / "demo-building.json",
        roomplan_sample_path=REPO_ROOT / "sample-data" / "third-party" / "open3dfloorplan-test-roomplan.json",
        cors_origins=[o.strip() for o in origins.split(",") if o.strip()],
    )


@lru_cache
def get_store() -> MapStore:
    return MapStore(get_settings().data_dir)


@lru_cache
def get_voice() -> CartesiaVoice:
    return CartesiaVoice(VoiceConfig.from_env())


@lru_cache
def get_interpreter() -> GeminiInterpreter:
    return GeminiInterpreter(GeminiConfig.from_env())


# --------------------------------------------------------------------------- errors


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: Any = None):
        self.status, self.code, self.message, self.details = status, code, message, details


def _error_body(code: str, message: str, details: Any = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}


# --------------------------------------------------------------------------- response models


class ModelStatus(BaseModel):
    status: Literal["none", "ready", "stale"]
    generated_at: str | None = None
    filename: str | None = None
    report: TactileReport | None = None


class MapResponse(BaseModel):
    map: FloorMap
    issues: list[ValidationIssue]
    model: ModelStatus
    processing_steps: list[str] = []


class MapSummary(BaseModel):
    id: str
    name: str
    synthetic: bool
    updated_at: str | None
    walls: int
    landmarks: int
    model_status: Literal["none", "ready", "stale"]


class GenerateRequest(BaseModel):
    settings: TactileSettings | None = None


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TTS_CHARS)
    speed: float = Field(1.0, ge=0.6, le=1.5)


class TranscriptResponse(BaseModel):
    text: str


class RouteRequest(BaseModel):
    origin: str = Field(min_length=1, description="Landmark id or navigation node id")
    destination: str = Field(min_length=1, description="Landmark id or navigation node id")
    avoid_stairs: bool = False


class RouteResponse(RouteResult):
    safety_note: str | None = None


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    context: AskContext = Field(default_factory=AskContext)


# --------------------------------------------------------------------------- app


app = FastAPI(title="TouchSpace AI API", version=VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "X-Model-Stale"],
)


@app.exception_handler(ApiError)
async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content=_error_body(exc.code, exc.message, exc.details))


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    details = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:20]]
    return JSONResponse(status_code=422, content=_error_body("invalid_request", "The request has invalid fields.", details))


def _load(store: MapStore, map_id: str) -> FloorMap:
    try:
        return store.load(map_id)
    except MapNotFound:
        raise ApiError(404, "map_not_found", f"No map with id '{map_id}'.") from None


def _model_status(store: MapStore, fmap: FloorMap, include_report: bool = True) -> ModelStatus:
    stored = store.load_report(fmap.id)
    if stored is None:
        return ModelStatus(status="none")
    status = "ready" if stored.map_revision == map_revision(fmap) else "stale"
    return ModelStatus(status=status, generated_at=stored.generated_at, filename=stored.filename,
                       report=stored.report if include_report else None)


def _map_response(store: MapStore, fmap: FloorMap, steps: list[str] | None = None,
                  issues: list[ValidationIssue] | None = None) -> MapResponse:
    return MapResponse(map=fmap, issues=issues if issues is not None else validate_map(fmap),
                       model=_model_status(store, fmap), processing_steps=steps or [])


def _ingest(store: MapStore, data: Any, *, map_id: str, name: str | None) -> MapResponse:
    try:
        imported = import_scan(data, name=name)
    except ImportError_ as exc:
        raise ApiError(422, "unsupported_scan", str(exc), exc.details) from None
    fmap = imported.map
    fmap.id = map_id
    try:
        result = process_map(fmap)
    except FloorPlanError as exc:
        raise ApiError(422, "unprocessable_plan", str(exc)) from None
    saved = store.save(result.map)
    import_issues = [ValidationIssue(severity="warning", code="import_note", message=w) for w in imported.warnings]
    label = {"roomplan": "Read an Apple RoomPlan export.", "touchspace": "Read a TouchSpace map file."}[imported.format]
    steps = [label, *result.steps]
    return _map_response(store, saved, steps, import_issues + result.issues)


@app.get("/api/health")
def health(voice: CartesiaVoice = Depends(get_voice), interpreter: GeminiInterpreter = Depends(get_interpreter)) -> dict:
    return {
        "status": "ok",
        "version": VERSION,
        "features": {
            "gemini": interpreter.enabled,
            "cartesia": voice.config.enabled,
        },
    }


@app.post("/api/tts", response_class=Response)
def text_to_speech(body: SpeakRequest, voice: CartesiaVoice = Depends(get_voice)) -> Response:
    """Speak text with Cartesia. 503 means: use the browser's own speech instead."""
    try:
        audio = voice.synthesize(body.text, speed=body.speed)
    except VoiceUnavailable as exc:
        raise ApiError(503, "voice_unavailable", str(exc)) from None
    except ValueError as exc:
        raise ApiError(422, "invalid_text", str(exc)) from None
    return Response(content=audio, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})


@app.post("/api/stt", response_model=TranscriptResponse)
def speech_to_text(file: UploadFile = File(...), voice: CartesiaVoice = Depends(get_voice)) -> TranscriptResponse:
    """Transcribe a short recording with Cartesia. 503 means: use browser speech recognition or typing."""
    # Sync handler on purpose: FastAPI runs it in a worker thread, so the blocking Cartesia call
    # does not stall other requests.
    audio = file.file.read()
    try:
        text = voice.transcribe(audio, file.filename or "speech.webm", file.content_type)
    except VoiceUnavailable as exc:
        raise ApiError(503, "voice_unavailable", str(exc)) from None
    except ValueError as exc:
        raise ApiError(422, "invalid_audio", str(exc)) from None
    return TranscriptResponse(text=text)


@app.post("/api/scans", status_code=201, response_model=MapResponse)
async def upload_scan(file: UploadFile = File(...), name: str | None = Form(None),
                      store: MapStore = Depends(get_store)) -> MapResponse:
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ApiError(413, "file_too_large", f"Scan files must be under {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    if not raw.strip():
        raise ApiError(400, "empty_file", "The uploaded file is empty.")
    try:
        data = json.loads(raw)
    except UnicodeDecodeError:
        raise ApiError(400, "invalid_json", "The file is not text. Upload the JSON file exported by the scanner.") from None
    except json.JSONDecodeError as exc:
        raise ApiError(400, "invalid_json", f"The file is not valid JSON (line {exc.lineno}, column {exc.colno}: {exc.msg}).") from None
    stem = Path(file.filename or "scan").stem.replace("_", " ").replace("-", " ").strip()
    default_name = name or (data.get("name") if isinstance(data, dict) else None) or stem.title() or "Uploaded scan"
    return _ingest(store, data, map_id=new_map_id("scan"), name=default_name)


@app.post("/api/demo", status_code=201, response_model=MapResponse)
def create_demo(store: MapStore = Depends(get_store)) -> MapResponse:
    """Create a fresh, editable copy of the synthetic demo building."""
    path = get_settings().demo_path
    if not path.is_file():
        raise ApiError(500, "demo_missing", "The demo map file is missing from sample-data/.")
    return _ingest(store, json.loads(path.read_text()), map_id=new_map_id("demo"), name=None)


@app.post("/api/samples/roomplan", status_code=201, response_model=MapResponse)
def create_roomplan_sample(store: MapStore = Depends(get_store)) -> MapResponse:
    """Import the checked-in public RoomPlan export (see sample-data/third-party/README.md).

    Ported from PR #1. It goes through the same import path as an uploaded scan.
    """
    path = get_settings().roomplan_sample_path
    if not path.is_file():
        raise ApiError(500, "sample_missing", "The RoomPlan sample file is missing from sample-data/third-party/.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise ApiError(500, "sample_invalid", "The checked-in RoomPlan sample file could not be read.") from None
    return _ingest(store, data, map_id=new_map_id("roomplan"), name="Public RoomPlan sample")


@app.get("/api/maps", response_model=list[MapSummary])
def list_maps(store: MapStore = Depends(get_store)) -> list[MapSummary]:
    return [
        MapSummary(id=m.id, name=m.name, synthetic=m.source.synthetic, updated_at=m.updated_at,
                   walls=len(m.walls), landmarks=len(m.landmarks),
                   model_status=_model_status(store, m, include_report=False).status)
        for m in store.list()
    ]


@app.get("/api/maps/{map_id}", response_model=MapResponse)
def get_map(map_id: str, store: MapStore = Depends(get_store)) -> MapResponse:
    return _map_response(store, _load(store, map_id))


@app.put("/api/maps/{map_id}", response_model=MapResponse)
def update_map(map_id: str, fmap: FloorMap, store: MapStore = Depends(get_store)) -> MapResponse:
    """Replace the editable map. Saved even when it has validation errors; those block generation."""
    existing = _load(store, map_id)
    if fmap.id != map_id:
        raise ApiError(400, "id_mismatch", "The map id in the body does not match the URL.")
    # Provenance is not editable: an edited scan is still a scan, and synthetic data stays synthetic.
    fmap.source = SourceInfo.model_validate(existing.source.model_dump())
    fmap.created_at = existing.created_at
    return _map_response(store, store.save(fmap))


@app.post("/api/maps/{map_id}/generate", response_model=ModelStatus)
def generate(map_id: str, body: GenerateRequest | None = None, store: MapStore = Depends(get_store)) -> ModelStatus:
    fmap = _load(store, map_id)
    if body is not None and body.settings is not None:
        fmap.tactile = body.settings
        fmap = store.save(fmap)
    try:
        mesh, report = generate_tactile_model(fmap)
    except TactileGenerationError as exc:
        checks = [c.model_dump() for c in exc.checks] if exc.checks else None
        raise ApiError(422, "generation_failed", str(exc), checks) from None
    stored = store.save_model(fmap, export_stl(mesh), report, stl_filename(fmap))
    return ModelStatus(status="ready", generated_at=stored.generated_at, filename=stored.filename, report=report)


@app.post("/api/maps/{map_id}/route", response_model=RouteResponse)
def route(map_id: str, body: RouteRequest, store: MapStore = Depends(get_store)) -> RouteResponse:
    """Shortest walkable route over the map's recorded paths. `found: false` explains why there is none."""
    fmap = _load(store, map_id)
    try:
        r = plan_route(fmap, body.origin, body.destination, avoid_stairs=body.avoid_stairs)
    except RoutingError as exc:
        raise ApiError(422, "unroutable", str(exc)) from None
    data = r.model_dump(exclude={"spoken"})
    return RouteResponse(**data, safety_note=SAFETY_NOTE if r.found else None)


@app.post("/api/maps/{map_id}/ask", response_model=AskResult)
def ask(map_id: str, body: AskRequest, store: MapStore = Depends(get_store),
        interpreter: GeminiInterpreter = Depends(get_interpreter)) -> AskResult:
    """Answer a spatial question using only facts from this map (Gemini, if configured, only helps parse it)."""
    return answer(_load(store, map_id), body.question, body.context, interpreter=interpreter)


@app.get("/api/maps/{map_id}/model", response_model=ModelStatus)
def get_model(map_id: str, store: MapStore = Depends(get_store)) -> ModelStatus:
    return _model_status(store, _load(store, map_id))


@app.get("/api/maps/{map_id}/stl")
def download_stl(map_id: str, store: MapStore = Depends(get_store)) -> FileResponse:
    fmap = _load(store, map_id)
    status = _model_status(store, fmap, include_report=False)
    if status.status == "none":
        raise ApiError(404, "model_not_generated", "No tactile model has been generated for this map yet.")
    return FileResponse(
        store.stl_path(map_id),
        media_type="model/stl",
        filename=status.filename,
        headers={"X-Model-Stale": "true" if status.status == "stale" else "false", "Cache-Control": "no-store"},
    )
