"""Tactile print settings and the report produced by the STL generator.

Default dimensions are prototype values chosen for FDM printing, not an
established accessibility standard. They are meant to be tuned from print
tests and feedback from tactile map readers.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class TactileSettings(BaseModel):
    max_width_mm: float = Field(180.0, ge=40, le=400)
    max_depth_mm: float = Field(180.0, ge=40, le=400)
    margin_mm: float = Field(8.0, ge=2, le=40)
    base_thickness_mm: float = Field(3.0, ge=1, le=10)

    wall_height_mm: float = Field(2.5, ge=0.5, le=10)
    wall_width_mm: float = Field(2.0, ge=0.8, le=8)
    min_door_gap_mm: float = Field(5.0, ge=0, le=30, description="Door gaps narrower than this are widened so a finger can find them")

    landmark_size_mm: float = Field(7.0, ge=3, le=20)
    landmark_height_mm: float = Field(2.0, ge=0.5, le=10)
    object_height_mm: float = Field(1.0, ge=0.3, le=10)

    path_dot_diameter_mm: float = Field(1.6, ge=0.8, le=5)
    path_dot_height_mm: float = Field(0.8, ge=0.3, le=5)
    path_dot_spacing_mm: float = Field(4.0, ge=2, le=20)

    include_landmarks: bool = True
    include_objects: bool = True
    include_paths: bool = False
    include_legend: bool = True
    orientation_marker: bool = Field(True, description="Cut the top-left corner of the base so the reader can find 'up'")

    @model_validator(mode="after")
    def _check_fits(self) -> "TactileSettings":
        usable = min(self.max_width_mm, self.max_depth_mm) - 2 * self.margin_mm
        if usable < 20:
            raise ValueError("margins leave less than 20 mm of printable area")
        return self


FeatureKind = Literal["base", "wall", "door_gap", "landmark", "object", "path", "legend", "orientation_marker"]


class TactileFeature(BaseModel):
    kind: FeatureKind
    label: str
    element_id: str | None = None
    symbol: str | None = None
    center_mm: tuple[float, float] | None = None
    size_mm: tuple[float, float] | None = None
    height_mm: float | None = None
    displaced_mm: float = 0.0
    note: str = ""


class MeshCheck(BaseModel):
    name: str
    passed: bool
    detail: str = ""


class TactileReport(BaseModel):
    map_id: str
    width_mm: float
    depth_mm: float
    height_mm: float
    scale_mm_per_m: float
    scale_ratio: str
    triangle_count: int
    volume_mm3: float
    watertight: bool
    body_count: int
    checks: list[MeshCheck]
    features: list[TactileFeature]
    warnings: list[str]
    summary: list[str] = Field(description="Plain-language description of the model, for screen readers")
    settings: TactileSettings
