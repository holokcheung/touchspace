"""One immutable package catalog. Private entries are visible only to their owner."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .models import MapPackage
from .package import ValidatedPackage


class Catalog:
    def __init__(self, root: Path):
        self.root = root / "touchspace"
        self.root.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS maps (
                id TEXT PRIMARY KEY, venue TEXT NOT NULL, visibility TEXT NOT NULL,
                owner TEXT NOT NULL, metadata TEXT NOT NULL, package TEXT NOT NULL)""")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.root / "catalog.sqlite3", timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def save(self, package: ValidatedPackage, owner: str, visibility: str):
        manifest = package.map.manifest
        map_id = str(manifest.id)
        filename = f"{map_id}-{uuid4()}.touchspacemap"
        path = self.root / filename
        temp = path.with_suffix(".tmp")
        temp.write_bytes(package.raw)
        os.replace(temp, path)
        try:
            with self.connect() as db:
                db.execute("INSERT INTO maps VALUES (?,?,?,?,?,?)", (map_id, manifest.venue, visibility, owner,
                           package.map.model_dump_json(by_alias=True), filename))
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return package.map

    def search(self, query: str):
        # instr treats %, _ and quotes as text, rather than SQL wildcards.
        with self.connect() as db:
            return [self.summary(row) for row in db.execute(
                "SELECT * FROM maps WHERE visibility='public' AND instr(lower(venue),lower(?))>0 ORDER BY rowid DESC LIMIT 100", (query,))]

    def load(self, map_id: str, owner: str | None = None):
        with self.connect() as db:
            row = db.execute("SELECT * FROM maps WHERE id=? AND (visibility='public' OR owner=?)", (map_id, owner)).fetchone()
        if row is None:
            raise KeyError(map_id)
        return MapPackage.model_validate_json(row["metadata"]), self.root / row["package"], row["visibility"]

    @staticmethod
    def summary(row):
        package = MapPackage.model_validate_json(row["metadata"])
        return {"manifest": package.manifest.model_dump(mode="json", by_alias=True), "visibility": row["visibility"]}
