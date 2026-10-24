"""Local file storage for maps and generated models.

Layout, one folder per map:

    <data_dir>/maps/<map_id>/map.json      normalized FloorMap
    <data_dir>/maps/<map_id>/model.stl     last generated tactile model
    <data_dir>/maps/<map_id>/report.json   generation report + the map revision it was built from
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from app.models.map import FloorMap
from app.models.tactile import TactileReport

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")


class StoredReport(BaseModel):
    generated_at: str
    map_revision: str
    filename: str
    report: TactileReport


class MapNotFound(KeyError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_map_id(prefix: str = "map") -> str:
    return f"{prefix}-{secrets.token_hex(4)}"


def map_revision(fmap: FloorMap) -> str:
    """Content hash of everything that affects the tactile model."""
    data = fmap.model_dump(mode="json", exclude={"created_at", "updated_at"})
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class MapStore:
    def __init__(self, data_dir: Path):
        self.root = Path(data_dir) / "maps"
        self.root.mkdir(parents=True, exist_ok=True)

    def _dir(self, map_id: str) -> Path:
        if not _ID_RE.match(map_id):
            raise MapNotFound(map_id)
        return self.root / map_id

    def exists(self, map_id: str) -> bool:
        try:
            return (self._dir(map_id) / "map.json").is_file()
        except MapNotFound:
            return False

    def save(self, fmap: FloorMap) -> FloorMap:
        fmap = fmap.model_copy(update={"updated_at": now_iso(), "created_at": fmap.created_at or now_iso()})
        _atomic_write(self._dir(fmap.id) / "map.json", fmap.model_dump_json(indent=2).encode())
        return fmap

    def load(self, map_id: str) -> FloorMap:
        path = self._dir(map_id) / "map.json"
        if not path.is_file():
            raise MapNotFound(map_id)
        return FloorMap.model_validate_json(path.read_bytes())

    def list(self) -> list[FloorMap]:
        maps = []
        for path in self.root.glob("*/map.json"):
            try:
                maps.append(FloorMap.model_validate_json(path.read_bytes()))
            except ValueError:
                continue  # skip corrupt entries rather than failing the whole listing
        return sorted(maps, key=lambda m: m.updated_at or "", reverse=True)

    def save_model(self, fmap: FloorMap, stl: bytes, report: TactileReport, filename: str) -> StoredReport:
        d = self._dir(fmap.id)
        _atomic_write(d / "model.stl", stl)
        stored = StoredReport(generated_at=now_iso(), map_revision=map_revision(fmap), filename=filename, report=report)
        _atomic_write(d / "report.json", stored.model_dump_json(indent=2).encode())
        return stored

    def load_report(self, map_id: str) -> StoredReport | None:
        path = self._dir(map_id) / "report.json"
        if not path.is_file() or not (self._dir(map_id) / "model.stl").is_file():
            return None
        return StoredReport.model_validate_json(path.read_bytes())

    def stl_path(self, map_id: str) -> Path:
        return self._dir(map_id) / "model.stl"
