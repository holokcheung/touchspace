"""Strict, bounded ZIP import. Archives are inspected as data, never deserialized as code."""
from __future__ import annotations

import hashlib
import io
import json
import plistlib
import stat
import zipfile
import zlib
from dataclasses import dataclass
from uuid import UUID

from pydantic import ValidationError
from .models import MapPackage
from .spatial import SpatialEngine, SpatialError

MAX_PACKAGE = 64 * 1024 * 1024
MAX_JSON = 4 * 1024 * 1024
FILES = {"manifest.json", "geometry.json", "landmarks.json", "navigation.json", "worldmap.archive"}


class PackageError(ValueError):
    pass


@dataclass
class ValidatedPackage:
    map: MapPackage
    raw: bytes


def strict_json(raw: bytes):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise PackageError("Duplicate JSON key")
            result[key] = value
        return result
    def constant(_):
        raise PackageError("Nonfinite JSON number")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def check_synthetic_worldmap(raw: bytes, frame: UUID, anchor_id: UUID):
    """An explicit non-restorable placeholder, never a fabricated ARWorldMap."""
    expected = {"format": "touchspace.synthetic-worldmap", "version": 1,
                "coordinateFrameId": str(frame), "frameAnchorId": str(anchor_id), "relocalizable": False}
    try:
        value = plistlib.loads(raw)
        if value != expected or type(value.get("version")) is not int or value.get("relocalizable") is not False:
            raise PackageError("Invalid synthetic world-map placeholder")
    except PackageError:
        raise
    except (ValueError, TypeError, AttributeError, OverflowError, RecursionError) as exc:
        raise PackageError("Invalid synthetic world-map placeholder") from exc


def check_worldmap(raw: bytes, frame: UUID, anchor_id: UUID):
    try:
        archive = plistlib.loads(raw)
        objects = archive["$objects"]
        if archive["$archiver"] != "NSKeyedArchiver" or not isinstance(objects, list) or len(objects) > 300000:
            raise PackageError("Invalid secure world-map archive")
        def resolve(value):
            return objects[value.data] if isinstance(value, plistlib.UID) else value
        def class_name(obj):
            return resolve(obj.get("$class", {})).get("$classname", "") if isinstance(obj, dict) else ""
        root = resolve(archive["$top"].get("root"))
        if class_name(root) != "ARWorldMap":
            raise PackageError("Archive root must be ARWorldMap")
        expected = f"touchspace-frame:{str(frame).lower()}"
        # Visit only references reachable from the world-map root, with a bounded cycle guard.
        def values(obj, seen):
            if isinstance(obj, plistlib.UID):
                if obj.data in seen:
                    return
                seen.add(obj.data)
                yield from values(resolve(obj), seen)
            elif isinstance(obj, dict):
                for key, value in obj.items():
                    if key != "$class":
                        yield from values(value, seen)
            elif isinstance(obj, list):
                for value in obj:
                    yield from values(value, seen)
            else:
                yield obj
        reachable = set()
        def visit(obj):
            if isinstance(obj, plistlib.UID):
                if obj.data in reachable:
                    return
                reachable.add(obj.data)
                visit(resolve(obj))
            elif isinstance(obj, dict):
                for key, value in obj.items():
                    if key != "$class":
                        visit(value)
            elif isinstance(obj, list):
                for value in obj:
                    visit(value)
        visit(root)
        for index in reachable:
            obj = objects[index]
            if class_name(obj) != "ARAnchor":
                continue
            contents = list(values(obj, set()))
            has_name = any(isinstance(v, str) and v.lower() == expected for v in contents)
            has_id = any((isinstance(v, bytes) and v == anchor_id.bytes) or
                         (isinstance(v, str) and v.lower() == str(anchor_id)) for v in contents)
            if has_name and has_id:
                return
        raise PackageError("Expected named coordinate-frame anchor and identifier are missing")
    except PackageError:
        raise
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, RecursionError, OverflowError) as exc:
        raise PackageError("Malformed world-map archive") from exc


def validate_package(raw: bytes) -> ValidatedPackage:
    if len(raw) > MAX_PACKAGE:
        raise PackageError("Package exceeds 64 MB")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if len(entries) != 5 or {e.filename for e in entries} != FILES:
                raise PackageError("Package must contain exactly the five contract files, without paths or duplicates")
            if sum(e.file_size for e in entries) > MAX_PACKAGE:
                raise PackageError("Expanded package exceeds 64 MB")
            for entry in entries:
                if entry.flag_bits & 1 or stat.S_ISLNK(entry.external_attr >> 16):
                    raise PackageError("Encrypted entries and links are forbidden")
                if entry.filename.endswith(".json") and entry.file_size > MAX_JSON:
                    raise PackageError("JSON exceeds 4 MB")
            files = {e.filename: archive.read(e) for e in entries}
        data = {name[:-5]: strict_json(value) for name, value in files.items() if name.endswith(".json")}
        package = MapPackage.model_validate(data)
        expected = FILES - {"manifest.json"}
        if set(package.manifest.checksums) != expected:
            raise PackageError("Every payload must have a SHA-256 checksum")
        for name in expected:
            if hashlib.sha256(files[name]).hexdigest() != package.manifest.checksums[name]:
                raise PackageError(f"Checksum mismatch: {name}")
        check = check_synthetic_worldmap if package.manifest.is_synthetic else check_worldmap
        check(files["worldmap.archive"], package.manifest.coordinate_frame_id, package.manifest.frame_anchor_id)
        SpatialEngine(package)
        return ValidatedPackage(package, raw)
    except PackageError:
        raise
    except (zipfile.BadZipFile, RuntimeError, UnicodeError, ValueError, ValidationError, SpatialError,
            RecursionError, NotImplementedError, OverflowError, EOFError, zlib.error) as exc:
        raise PackageError("Invalid map package: " + str(exc)[:250]) from exc
