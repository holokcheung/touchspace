"""Normalized spatial model shared by every TouchSpace component.

All plan coordinates are in meters on the 2D floor plane:
  * +x points right on the plan, +y points up on the plan.
  * For RoomPlan imports, plan x = world X and plan y = -world Z
    (RoomPlan's Y axis is vertical, so it is dropped after projection).

Nothing downstream (floor-plan processing, tactile generation, routing,
voice) reads Apple's raw export format; importers convert into this model.
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0"

Confidence = Literal["low", "medium", "high"]


class Point2D(BaseModel):
    x: float
    y: float

    def as_tuple(self) -> tuple[float, float]:
        return (self.x, self.y)


class Bounds(BaseModel):
    min_x: float
    min_y: float
    max_x: float
    max_y: float

    @property
    def width(self) -> float:
        return self.max_x - self.min_x

    @property
    def depth(self) -> float:
        return self.max_y - self.min_y


class SourceInfo(BaseModel):
    kind: Literal["synthetic", "roomplan", "manual"]
    description: str = ""
    importer_version: str | None = None
    captured_at: str | None = None

    @property
    def synthetic(self) -> bool:
        return self.kind == "synthetic"


class Wall(BaseModel):
    id: str
    start: Point2D
    end: Point2D
    thickness: float = Field(0.15, gt=0, le=2.0, description="Real wall thickness in meters")
    height: float | None = Field(None, gt=0, description="Real wall height in meters, if known")
    confidence: Confidence | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def length(self) -> float:
        return math.dist(self.start.as_tuple(), self.end.as_tuple())

    @property
    def angle(self) -> float:
        """Direction of the wall in radians, measured CCW from +x."""
        return math.atan2(self.end.y - self.start.y, self.end.x - self.start.x)


class WallGap(BaseModel):
    """Shared shape of anything positioned along a wall (doors, openings, windows)."""

    id: str
    position: Point2D = Field(description="Center of the gap, on the wall centerline")
    width: float = Field(gt=0, le=20.0, description="Width along the wall in meters")
    wall_id: str | None = None
    confidence: Confidence | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Door(WallGap):
    kind: Literal["door"] = "door"
    is_open: bool | None = None


class Opening(WallGap):
    kind: Literal["opening"] = "opening"


class Window(WallGap):
    kind: Literal["window"] = "window"


class MapObject(BaseModel):
    """A detected or hand-placed object (furniture, fixtures, stairs...)."""

    id: str
    category: str = Field(description="RoomPlan category such as 'table' or 'toilet'; not guaranteed accurate")
    position: Point2D
    width: float = Field(gt=0, description="Footprint size along the object's local x axis, meters")
    depth: float = Field(gt=0, description="Footprint size along the object's local y axis, meters")
    height: float | None = Field(None, gt=0)
    rotation: float = Field(0.0, description="Plan rotation in radians, CCW")
    label: str | None = None
    confidence: Confidence | None = None
    include_in_tactile: bool = False
    hidden: bool = Field(False, description="Hide in the 2D editor and descriptions")
    metadata: dict[str, Any] = Field(default_factory=dict)


class LandmarkType(str, Enum):
    entrance = "entrance"
    exit = "exit"
    restroom = "restroom"
    stairs = "stairs"
    elevator = "elevator"
    information = "information"
    room = "room"
    hallway = "hallway"
    other = "other"


class Landmark(BaseModel):
    id: str
    name: str = Field(min_length=1, max_length=120)
    type: LandmarkType
    position: Point2D
    description: str = ""
    show_on_tactile: bool = True
    nav_node_id: str | None = None
    source: Literal["manual", "detected", "synthetic"] = "manual"


class Room(BaseModel):
    id: str
    name: str = Field(min_length=1, max_length=120)
    polygon: list[Point2D] = Field(min_length=3)
    description: str = ""


class NavNode(BaseModel):
    id: str
    position: Point2D
    label: str | None = None
    kind: Literal["place", "door", "junction"] = "place"
    landmark_id: str | None = None
    room_id: str | None = None


class NavEdge(BaseModel):
    """A walkable connection between two nodes.

    Edges only exist where someone (a person or a trusted import step)
    confirmed the connection. Accessibility stays "unknown" unless the data
    supports a stronger claim.
    """

    id: str
    a: str
    b: str
    traversable: bool = True
    accessibility: Literal["unknown", "step_free", "has_steps"] = "unknown"
    source: Literal["manual", "synthetic", "derived"] = "manual"
    notes: str = ""


class NavigationGraph(BaseModel):
    nodes: list[NavNode] = Field(default_factory=list)
    edges: list[NavEdge] = Field(default_factory=list)


class ValidationIssue(BaseModel):
    severity: Literal["error", "warning", "info"]
    code: str
    message: str
    element_id: str | None = None


# Imported late to avoid a cycle: tactile settings are part of a map.
from app.models.tactile import TactileSettings  # noqa: E402


class FloorMap(BaseModel):
    schema_version: str = SCHEMA_VERSION
    id: str
    name: str = Field(min_length=1, max_length=200)
    units: Literal["meters"] = "meters"
    source: SourceInfo
    floor_level: int | None = None
    bounds: Bounds | None = None
    walls: list[Wall] = Field(default_factory=list)
    doors: list[Door] = Field(default_factory=list)
    openings: list[Opening] = Field(default_factory=list)
    windows: list[Window] = Field(default_factory=list)
    objects: list[MapObject] = Field(default_factory=list)
    rooms: list[Room] = Field(default_factory=list)
    landmarks: list[Landmark] = Field(default_factory=list)
    navigation: NavigationGraph = Field(default_factory=NavigationGraph)
    start_landmark_id: str | None = None
    tactile: TactileSettings = Field(default_factory=TactileSettings)
    created_at: str | None = None
    updated_at: str | None = None

    def wall_by_id(self, wall_id: str) -> Wall | None:
        return next((w for w in self.walls if w.id == wall_id), None)

    def landmark_by_id(self, landmark_id: str) -> Landmark | None:
        return next((lm for lm in self.landmarks if lm.id == landmark_id), None)

    @property
    def gaps(self) -> list[Door | Opening]:
        """Doors and openings: the wall gaps that stay open on the tactile map."""
        return [*self.doors, *self.openings]
