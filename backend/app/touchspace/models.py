from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

ID = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}$")]
Label = Annotated[str, StringConstraints(min_length=1, max_length=200, pattern=r"\S")]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Point(Model):
    x: float = Field(ge=-10000, le=10000)
    z: float = Field(ge=-10000, le=10000)


class Manifest(Model):
    schemaVersion: Literal[1]
    mapId: ID
    title: Label
    floor: Label
    coverage: Label
    contributor: Label
    createdAt: datetime
    updatedAt: datetime
    verification: Literal["unverified", "volunteer-reviewed"]
    units: Literal["meters"]
    coordinateFrameId: UUID
    frameAnchorId: UUID
    worldMapIncluded: bool
    synthetic: bool = False

    @model_validator(mode="after")
    def dates(self):
        if self.createdAt.tzinfo is None or self.updatedAt.tzinfo is None or self.updatedAt < self.createdAt:
            raise ValueError("Timestamps must be timezone-aware and ordered.")
        if self.synthetic and self.worldMapIncluded:
            raise ValueError("Synthetic maps cannot claim real world data.")
        return self


class Room(Model):
    id: ID
    name: Label
    polygon: list[Point] = Field(min_length=3, max_length=512)


class Wall(Model):
    id: ID
    a: Point
    b: Point


class Obstacle(Model):
    id: ID
    polygon: list[Point] = Field(min_length=3, max_length=128)


class Geometry(Model):
    coordinateFrameId: UUID
    # Column-major 4x4 transform. v1 documents are already in the saved session frame.
    transform: list[float] = Field(min_length=16, max_length=16)
    rooms: list[Room] = Field(min_length=1, max_length=100)
    walls: list[Wall] = Field(max_length=2000)
    obstacles: list[Obstacle] = Field(max_length=2000)
    capturedRoom: dict | None = None

    @model_validator(mode="after")
    def identity(self):
        if self.transform != [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]:
            raise ValueError("v1 requires geometry in the saved session frame (identity root transform).")
        return self


class Landmark(Model):
    id: ID
    name: Label
    type: Literal["entrance", "exit", "information", "restroom", "object", "stairs", "elevator", "other"]
    position: Point
    roomId: ID
    nodeId: ID | None = None
    provenance: Literal["volunteer", "scan"]


class Landmarks(Model):
    coordinateFrameId: UUID
    landmarks: list[Landmark] = Field(max_length=2000)


class Node(Model):
    id: ID
    position: Point
    roomId: ID


class Door(Model):
    id: ID
    name: Label
    rooms: list[ID] = Field(min_length=1, max_length=2)
    position: Point
    width: float = Field(gt=0, le=20)
    # Explicit volunteer confirmation, never inferred from a RoomPlan doorway.
    traversable: bool = False


class Edge(Model):
    a: ID
    b: ID
    doorId: ID | None = None


class Navigation(Model):
    coordinateFrameId: UUID
    clearance: float = Field(ge=0.25, le=2)
    nodes: list[Node] = Field(min_length=1, max_length=20000)
    edges: list[Edge] = Field(max_length=80000)
    doors: list[Door] = Field(max_length=1000)


class Pose(Model):
    coordinateFrameId: UUID
    position: Point
    # radians; 0 faces ARKit -Z, positive turns toward +X (phone-facing).
    heading: float = Field(ge=-3.141593, le=3.141593)
    tracking: Literal["relocalizing", "localized", "limited", "failed"]
    frameVerified: bool
    timestamp: datetime


class ChatRequest(Model):
    mapId: ID
    sessionId: UUID
    message: str = Field(min_length=1, max_length=2000)
    pose: Pose | None = None


class ToolCall(Model):
    operation: Literal["get_pose", "list_rooms", "nearby_landmarks", "relative_direction", "room_connections", "get_route", "route_summary", "get_map_overview", "unknown"]
    targetId: ID | None = None
    direction: Literal["left", "right", "ahead", "behind"] | None = None


class CatalogResponse(Model):
    manifest: Manifest
    visibility: Literal['private', 'public']
    checksum: Annotated[str, StringConstraints(pattern=r'^[0-9a-f]{64}$')]
    byteSize: int
    warnings: list[str]
    worldDataStatus: Literal['present-unverified', 'absent-draft']


class DestinationAction(Model):
    type: Literal['destination']
    destinationId: ID


class ToolResult(Model):
    operation: str
    sourceIds: list[str]
    data: dict
    error: str | None


class ChatResponse(Model):
    sessionId: UUID
    reply: str
    sourceIds: list[str]
    action: DestinationAction | None
    interpreter: str
    toolResults: list[ToolResult]
    poseUsed: bool
