from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from app.services.storage import _atomic_write, now_iso

from .package import MapPackage, validate_package


class CatalogError(ValueError):
    pass


class Catalog:
    def __init__(self, root: Path):
        self.root = root
        self.packages = root / 'packages'
        self.packages.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript(Path(__file__).with_name('migrations.sql').read_text())

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.root / 'catalog.sqlite3', timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def response(row) -> dict:
        return dict(manifest=json.loads(row['manifest_json']), visibility=row['visibility'], checksum=row['checksum'],
                    byteSize=row['byte_size'], warnings=json.loads(row['warnings_json']),
                    worldDataStatus='present-unverified' if json.loads(row['manifest_json'])['worldMapIncluded'] else 'absent-draft')

    def save(self, package: MapPackage, raw: bytes, *, owner: str, visibility: str) -> dict:
        key = package.checksum + '.touchspacemap'
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT * FROM touchspace_maps WHERE map_id = ?', (package.manifest.mapId,)).fetchone()
            if existing and (existing['owner'] != owner or existing['checksum'] != package.checksum):
                raise CatalogError('A different package already uses this map ID. Export a new ID for a revised scan.')
            if not existing:
                _atomic_write(self.packages / key, raw)
                db.execute('INSERT INTO touchspace_maps VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                           (package.manifest.mapId, owner, visibility, 1, package.manifest.model_dump_json(), package.checksum,
                            len(raw), key, now_iso(), now_iso() if visibility == 'public' else None, json.dumps(package.warnings)))
            else:
                db.execute('UPDATE touchspace_maps SET visibility = ?, published_at = ? WHERE map_id = ?',
                           (visibility, now_iso() if visibility == 'public' else None, package.manifest.mapId))
            return self.response(db.execute('SELECT * FROM touchspace_maps WHERE map_id = ?', (package.manifest.mapId,)).fetchone())

    def lookup(self, map_id: str, owner: str | None):
        with self.connection() as db:
            row = db.execute("SELECT * FROM touchspace_maps WHERE map_id = ? AND (visibility = 'public' OR owner = ?)", (map_id, owner)).fetchone()
        if row is None:
            raise KeyError(map_id)
        return row

    def search(self, query: str) -> list[dict]:
        # Search public metadata only. LIKE metacharacters are treated as literal search text.
        escaped = query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        with self.connection() as db:
            rows = db.execute("SELECT * FROM touchspace_maps WHERE visibility = 'public' AND (json_extract(manifest_json, '$.title') LIKE ? ESCAPE '\\' OR json_extract(manifest_json, '$.coverage') LIKE ? ESCAPE '\\') ORDER BY created_at DESC LIMIT 100", (f'%{escaped}%', f'%{escaped}%')).fetchall()
        return [self.response(r) for r in rows]

    def path(self, row) -> Path:
        path = self.packages / row['storage_key']
        if path.parent != self.packages or not path.is_file():
            raise CatalogError('Stored package is unavailable.')
        return path

    def load(self, map_id: str, owner: str | None) -> MapPackage:
        row = self.lookup(map_id, owner)
        raw = self.path(row).read_bytes()
        if hashlib.sha256(raw).hexdigest() != row['checksum']:
            raise CatalogError('Stored package checksum does not match the catalog.')
        return validate_package(raw)

    def target(self, scope: str, map_id: str, session_id: str) -> str | None:
        with self.connection() as db:
            row = db.execute('SELECT target_id FROM touchspace_sessions WHERE scope=? AND map_id=? AND session_id=? AND updated_at>?',
                             (scope, map_id, session_id, int(time.time())-1800)).fetchone()
        return row['target_id'] if row else None

    def remember(self, scope: str, map_id: str, session_id: str, target_id: str | None):
        with self.connection() as db:
            db.execute('DELETE FROM touchspace_sessions WHERE updated_at < ?', (int(time.time())-1800,))
            db.execute('INSERT INTO touchspace_sessions VALUES (?, ?, ?, ?, ?) ON CONFLICT(scope,map_id,session_id) DO UPDATE SET target_id=excluded.target_id, updated_at=excluded.updated_at',
                       (scope, map_id, session_id, target_id, int(time.time())))
