"""Bounded, non-extracting ZIP validation. Metadata is data, never instructions."""
from __future__ import annotations

import hashlib
import io
import plistlib
import stat
import zipfile
import zlib
from dataclasses import dataclass

from pydantic import ValidationError
from shapely.geometry import Point as ShapePoint, Polygon

from .models import Geometry, Landmarks, Manifest, Navigation
from .spatial import SpatialEngine, distance

MAX_BYTES = 64 * 1024 * 1024
MAX_JSON_BYTES = 8 * 1024 * 1024
JSON_FILES = {"manifest.json", "geometry.json", "landmarks.json", "navigation.json"}
ALLOWED_FILES = JSON_FILES | {"worldmap.archive"}


class PackageError(ValueError):
    pass


@dataclass
class MapPackage:
    manifest: Manifest
    geometry: Geometry
    landmarks: Landmarks
    navigation: Navigation
    world_data: bytes | None
    checksum: str
    warnings: list[str]

    def engine(self) -> SpatialEngine:
        return SpatialEngine(self.manifest, self.geometry, self.landmarks, self.navigation)


def unique(values, label):
    ids = [v.id for v in values]
    if len(ids) != len(set(ids)):
        raise PackageError(f"Duplicate {label} IDs.")


def validate_graph(manifest, geometry, landmarks, navigation) -> list[str]:
    if any(d.coordinateFrameId != manifest.coordinateFrameId for d in (geometry, landmarks, navigation)):
        raise PackageError("All documents must share the saved coordinate frame.")
    for values, name in [(geometry.rooms, "room"), (geometry.walls, "wall"), (geometry.obstacles, "obstacle"), (landmarks.landmarks, "landmark"), (navigation.nodes, "node"), (navigation.doors, "door")]:
        unique(values, name)
    for r in [*geometry.rooms, *geometry.obstacles]:
        poly = Polygon([(p.x, p.z) for p in r.polygon])
        if not poly.is_valid or poly.area < 0.01:
            raise PackageError("Invalid or degenerate polygon.")
    nodes = {n.id: n for n in navigation.nodes}
    rooms = {r.id: r for r in geometry.rooms}
    doors = {d.id: d for d in navigation.doors}
    for n in navigation.nodes:
        if n.roomId not in rooms or not Polygon([(p.x, p.z) for p in rooms[n.roomId].polygon]).covers(ShapePoint(n.position.x, n.position.z)):
            raise PackageError("Node is outside its scanned room.")
    for d in navigation.doors:
        if len(set(d.rooms)) != len(d.rooms) or any(r not in rooms for r in d.rooms):
            raise PackageError("Door references unknown/duplicate rooms.")
    for lm in landmarks.landmarks:
        if lm.roomId not in rooms or not Polygon([(p.x, p.z) for p in rooms[lm.roomId].polygon]).covers(ShapePoint(lm.position.x, lm.position.z)):
            raise PackageError("Landmark is outside its room.")
        if lm.nodeId is not None and (lm.nodeId not in nodes or nodes[lm.nodeId].roomId != lm.roomId or distance(lm.position, nodes[lm.nodeId].position) > 1.5):
            raise PackageError("Landmark route node is invalid or too far away.")
    seen = set()
    for e in navigation.edges:
        key = tuple(sorted((e.a, e.b)))
        if e.a not in nodes or e.b not in nodes or e.a == e.b or key in seen:
            raise PackageError("Invalid or duplicate graph edge.")
        seen.add(key)
        if e.doorId is not None and e.doorId not in doors:
            raise PackageError("Unknown doorway.")
        if nodes[e.a].roomId != nodes[e.b].roomId:
            if e.doorId is None or set(doors[e.doorId].rooms) != {nodes[e.a].roomId, nodes[e.b].roomId}:
                raise PackageError("Cross-room edges require an explicit connecting doorway.")
        if e.doorId and (distance(nodes[e.a].position, doors[e.doorId].position) + distance(nodes[e.b].position, doors[e.doorId].position) > distance(nodes[e.a].position, nodes[e.b].position) + 0.2):
            raise PackageError("Doorway does not lie on the graph transition.")
    engine = SpatialEngine(manifest, geometry, landmarks, navigation)
    if any(not engine.segment_valid(n.position, n.position) for n in navigation.nodes):
        raise PackageError("Navigation node violates obstacle clearance.")
    if any(not engine.segment_valid(nodes[e.a].position, nodes[e.b].position) for e in navigation.edges):
        raise PackageError("Graph edge crosses a wall, obstacle, or unscanned space.")
    if any(e.doorId and doors[e.doorId].width < 2 * navigation.clearance for e in navigation.edges):
        raise PackageError("Doorway is narrower than required clearance.")
    components = engine.components()
    return [f"The navigation graph contains {components} disconnected areas; some destinations are unreachable."] if components > 1 else []


def validate_package(raw: bytes) -> MapPackage:
    if not raw or len(raw) > MAX_BYTES:
        raise PackageError("Packages must be nonempty and at most 64 MiB.")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            names = [e.filename for e in entries]
            if len(names) != len(set(names)) or not JSON_FILES.issubset(names) or not set(names).issubset(ALLOWED_FILES):
                raise PackageError("Unexpected, duplicate, or missing archive files. Use flat canonical filenames.")
            if sum(e.file_size for e in entries) > MAX_BYTES:
                raise PackageError("Expanded archive exceeds 64 MiB.")
            for e in entries:
                if e.file_size == 0:
                    raise PackageError("Archive entries must not be empty; omit world data for a draft.")
                if e.flag_bits & 1 or stat.S_ISLNK(e.external_attr >> 16) or e.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    raise PackageError("Encrypted, linked, or unsupported ZIP entries.")
                if e.filename in JSON_FILES and e.file_size > MAX_JSON_BYTES:
                    raise PackageError("JSON document exceeds 8 MiB.")
            documents = {name: archive.read(name) for name in JSON_FILES}
            manifest = Manifest.model_validate_json(documents["manifest.json"])
            geometry = Geometry.model_validate_json(documents["geometry.json"])
            landmarks = Landmarks.model_validate_json(documents["landmarks.json"])
            navigation = Navigation.model_validate_json(documents["navigation.json"])
            world = archive.read("worldmap.archive") if "worldmap.archive" in names else None
        if manifest.worldMapIncluded != bool(world):
            raise PackageError("World map declaration does not match archive contents.")
        if world:
            # This is a structural check only. iOS must securely unarchive ARWorldMap and verify its anchor.
            plist = plistlib.loads(world)
            objects = plist.get("$objects", [])
            if plist.get("$archiver") != "NSKeyedArchiver" or not any(isinstance(o, dict) and o.get("$classname") == "ARWorldMap" for o in objects):
                raise PackageError("World data is not an ARWorldMap keyed archive.")
            if f"touchspace-frame:{manifest.coordinateFrameId}" not in objects:
                raise PackageError("World archive is missing the coordinate-frame anchor name.")
        warnings = validate_graph(manifest, geometry, landmarks, navigation)
        if not world:
            warnings.append("Map-only draft: no restorable world data. Live positioning is unavailable.")
        return MapPackage(manifest, geometry, landmarks, navigation, world, hashlib.sha256(raw).hexdigest(), warnings)
    except PackageError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, ValidationError, zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError, NotImplementedError, EOFError, OSError, zlib.error) as exc:
        raise PackageError(f"Invalid map package: {str(exc)[:400]}") from None
