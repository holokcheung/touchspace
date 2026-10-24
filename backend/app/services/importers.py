"""Detect the format of an uploaded scan and convert it to a FloorMap."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.models.map import FloorMap


class ImportError_(ValueError):
    """Raised with a message that is safe to show to the user."""

    def __init__(self, message: str, details: list[str] | None = None):
        super().__init__(message)
        self.details = details or []


def detect_format(data: Any) -> str:
    if not isinstance(data, dict):
        return "unknown"
    walls = data.get("walls")
    if isinstance(walls, list) and walls and isinstance(walls[0], dict):
        if "start" in walls[0] and "end" in walls[0]:
            return "touchspace"
        if "transform" in walls[0] and "dimensions" in walls[0]:
            return "roomplan"
    if "schema_version" in data and "source" in data:
        return "touchspace"
    if any(k in data for k in ("sections", "floors", "openings", "doors")) and "identifier" in data:
        return "roomplan"
    return "unknown"


def _format_validation_error(exc: ValidationError) -> list[str]:
    lines = []
    for err in exc.errors()[:10]:
        loc = ".".join(str(p) for p in err["loc"])
        lines.append(f"{loc}: {err['msg']}")
    if len(exc.errors()) > 10:
        lines.append(f"...and {len(exc.errors()) - 10} more problems")
    return lines


def import_scan(data: Any, *, name: str | None = None) -> FloorMap:
    fmt = detect_format(data)
    if fmt == "touchspace":
        try:
            fmap = FloorMap.model_validate(data)
        except ValidationError as exc:
            raise ImportError_("The file looks like a TouchSpace map but some fields are invalid.",
                               _format_validation_error(exc)) from exc
        if name:
            fmap.name = name
        return fmap
    if fmt == "roomplan":
        raise ImportError_("Apple RoomPlan files are recognized, but RoomPlan import is not implemented yet.")
    raise ImportError_(
        "Unrecognized file. Upload a RoomPlan CapturedRoom JSON export or a TouchSpace map JSON.",
        ["Expected a JSON object with a 'walls' list."],
    )
