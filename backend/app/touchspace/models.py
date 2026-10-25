"""Portable iOS map contract. Metres, ARKit X/Z plane, heading clockwise from -Z."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel


class Model(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid", allow_inf_nan=False)


class Point(Model):
    x: float = Field(ge=-1000, le=1000)
    z: float = Field(ge=-1000, le=1000)


class Transform(Model):
    x: float = 0
    z: float = 0
    yaw: float = 0
    y: float = 0


class Room(Model):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=120)
    polygon: list[Point] = Field(min_length=3, max_length=2000)


class Wall(Model):
    id: str = Field(min_length=1, max_length=100)
    start: Point
    end: Point
    thickness: float = Field(default=0.15, ge=0.02, le=2)


class Obstacle(Model):
    id: str = Field(min_length=1, max_length=100)
    polygon: list[Point] = Field(min_length=3, max_length=100)


class Geometry(Model):
    rooms: list[Room] = Field(min_length=1, max_length=100)
    walls: list[Wall] = Field(max_length=4000)
    obstacles: list[Obstacle] = Field(max_length=2000)
    floor_y: float = Field(ge=-100, le=100)
    map_to_world: Transform = Field(default_factory=Transform)


class Landmark(Model):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=120)
    room_id: str = Field(min_length=1, max_length=100)
    position: Point
    kind: str = Field(default="destination", max_length=80)


class Landmarks(Model):
    landmarks: list[Landmark] = Field(max_length=1000)


class Door(Model):
    id: str = Field(min_length=1, max_length=100)
    wall_id: str = Field(min_length=1, max_length=100)
    room_ids: list[str] = Field(min_length=1, max_length=2)
    start: Point
    end: Point
    traversability: Literal["unknown", "confirmed", "blocked"] = "unknown"


class Node(Model):
    id: str = Field(min_length=1, max_length=100)
    position: Point
    room_id: str = Field(min_length=1, max_length=100)


class Edge(Model):
    source: str = Field(min_length=1, max_length=100)
    target: str = Field(min_length=1, max_length=100)
    confirmed: bool = False
    clearance: float = Field(default=0, ge=0, le=5)


class Navigation(Model):
    resolution: float = Field(default=0.1, ge=0.1, le=0.1)
    clearance: float = Field(default=0.3, ge=0.2, le=0.8)
    doors: list[Door] = Field(default_factory=list, max_length=1000)
    nodes: list[Node] = Field(default_factory=list, max_length=5000)
    edges: list[Edge] = Field(default_factory=list, max_length=10000)


class Manifest(Model):
    schema_version: Literal["1.0"] = "1.0"
    id: UUID
    venue: str = Field(min_length=1, max_length=120)
    floor: str = Field(min_length=1, max_length=80)
    coverage: Literal["partial", "contiguous-zone"] = "partial"
    contributor: str = Field(min_length=1, max_length=120)
    verification: Literal["volunteer-reviewed", "unverified"] = "unverified"
    created_at: datetime
    coordinate_frame_id: UUID
    frame_anchor_id: UUID
    provenance: Literal["roomplan-same-session", "synthetic-fixture"] = "roomplan-same-session"
    checksums: dict[str, str]

    @property
    def is_synthetic(self) -> bool:
        return self.provenance == "synthetic-fixture"

    @field_validator("created_at")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None:
            raise ValueError("createdAt requires a timezone")
        return value


class MapPackage(Model):
    manifest: Manifest
    geometry: Geometry
    landmarks: Landmarks
    navigation: Navigation

    @model_validator(mode="after")
    def references(self):
        from shapely.geometry import Polygon, Point as ShapePoint, LineString
        if self.manifest.is_synthetic and self.manifest.verification != "unverified":
            raise ValueError("Synthetic fixtures must remain unverified")
        rooms = {r.id: r for r in self.geometry.rooms}
        walls = {w.id: w for w in self.geometry.walls}
        nodes = {n.id: n for n in self.navigation.nodes}
        groups = [self.geometry.rooms, self.geometry.walls, self.geometry.obstacles,
                  self.landmarks.landmarks, self.navigation.doors, self.navigation.nodes]
        if any(len({item.id for item in group}) != len(group) for group in groups):
            raise ValueError("Duplicate stable IDs")
        for room in self.geometry.rooms:
            polygon = Polygon([(p.x, p.z) for p in room.polygon])
            if not polygon.is_valid or polygon.area < 0.5 or polygon.area > 10000:
                raise ValueError("Invalid scanned polygon")
        for item in self.geometry.obstacles:
            polygon = Polygon([(p.x, p.z) for p in item.polygon])
            if not polygon.is_valid or polygon.area <= 0:
                raise ValueError("Invalid obstacle polygon")
        for item in [*self.landmarks.landmarks, *self.navigation.nodes]:
            if item.room_id not in rooms:
                raise ValueError("Unknown room association")
            polygon = Polygon([(p.x, p.z) for p in rooms[item.room_id].polygon])
            if not polygon.covers(ShapePoint(item.position.x, item.position.z)):
                raise ValueError("Place outside associated scanned room")
        for door in self.navigation.doors:
            if len(set(door.room_ids)) != len(door.room_ids) or math.hypot(door.start.x-door.end.x,door.start.z-door.end.z) <= 0.1:
                raise ValueError("Invalid doorway extent or room associations")
            if door.wall_id not in walls or any(r not in rooms for r in door.room_ids):
                raise ValueError("Door references unknown geometry")
            wall = walls[door.wall_id]
            line = LineString([(wall.start.x, wall.start.z), (wall.end.x, wall.end.z)])
            if any(line.distance(ShapePoint(p.x, p.z)) > 0.15 for p in [door.start, door.end]):
                raise ValueError("Door must lie on its associated wall")
        for edge in self.navigation.edges:
            if edge.source not in nodes or edge.target not in nodes:
                raise ValueError("Unknown graph node")
        return self


class Pose(Model):
    position: Point
    heading: float = Field(ge=-math.pi, le=math.pi)
    coordinate_frame_id: UUID
    observed_at: datetime
    verified: bool

    def fresh(self, frame: UUID, now: datetime | None = None) -> bool:
        if self.observed_at.tzinfo is None:
            return False
        age = ((now or datetime.now(timezone.utc)) - self.observed_at).total_seconds()
        return self.verified and self.coordinate_frame_id == frame and -1 <= age <= 3


class ChatRequest(Model):
    map_id: UUID
    session_id: UUID
    message: str = Field(min_length=1, max_length=1500)
    pose: Pose | None = None


class NavigationAction(Model):
    type: Literal["navigate"] = "navigate"
    destination_id: str


class ChatResponse(Model):
    answer: str
    actions: list[NavigationAction] = Field(default_factory=list)
    provider_used: bool = False
    requires_localization: bool = False
