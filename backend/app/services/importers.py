"""Detect the format of an uploaded scan and convert it to a FloorMap."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError

from app.models.map import FloorMap
from app.services.roomplan import RoomPlanImportError, import_roomplan, looks_like_roomplan


class ImportError_(ValueError):
    """Raised with a message that is safe to show to the user."""

    def __init__(self, message: str, details: list[str] | None = None):
        super().__init__(message)
        self.details = details or []


class ImportResult(BaseModel):
    map: FloorMap
    format: str
    warnings: list[str] = []


def detect_format(data: Any) -> str:
    if not isinstance(data, dict):
        return "unknown"
    walls = data.get("walls")
    if isinstance(walls, list) and walls and isinstance(walls[0], dict) and "start" in walls[0] and "end" in walls[0]:
        return "touchspace"
    if looks_like_roomplan(data):
        return "roomplan"
    if "schema_version" in data and "source" in data:
        return "touchspace"
    return "unknown"


def _format_validation_error(exc: ValidationError) -> list[str]:
    lines = []
    for err in exc.errors()[:10]:
        loc = ".".join(str(p) for p in err["loc"])
        lines.append(f"{loc}: {err['msg']}")
    if len(exc.errors()) > 10:
        lines.append(f"...and {len(exc.errors()) - 10} more problems")
    return lines


def import_scan(data: Any, *, name: str | None = None) -> ImportResult:
    fmt = detect_format(data)
    if fmt == "touchspace":
        try:
            fmap = FloorMap.model_validate(data)
        except ValidationError as exc:
            raise ImportError_("The file looks like a TouchSpace map but some fields are invalid.",
                               _format_validation_error(exc)) from exc
        if name:
            fmap.name = name
        return ImportResult(map=fmap, format=fmt)
    if fmt == "roomplan":
        try:
            fmap, warnings = import_roomplan(data, name=name)
        except RoomPlanImportError as exc:
            raise ImportError_(str(exc), exc.details) from exc
        return ImportResult(map=fmap, format=fmt, warnings=warnings)
    raise ImportError_(
        "Unrecognized file. Upload a RoomPlan CapturedRoom JSON export or a TouchSpace map JSON.",
        ["Expected a JSON object with a 'walls' list."],
    )
