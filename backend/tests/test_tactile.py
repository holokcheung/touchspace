from __future__ import annotations

import io
import struct

import pytest
import trimesh
from shapely.geometry import Point

from app.models import LandmarkType, TactileSettings
from app.services.floorplan import process_map
from app.services.symbols import SYMBOL_ORDER, symbol_footprint
from app.services.tactile import (
    TactileGenerationError,
    build_layers,
    export_stl,
    generate_tactile_model,
    stl_filename,
)
from tests.conftest import rect_room, section_at


def _wall_mid_z(s: TactileSettings) -> float:
    return s.base_thickness_mm + s.wall_height_mm / 2


def test_demo_model_is_printable(demo_map):
    mesh, report = generate_tactile_model(demo_map)
    assert all(c.passed for c in report.checks), report.checks
    assert mesh.is_watertight and mesh.is_volume
    assert len(mesh.split(only_watertight=False)) == 1
    assert report.width_mm <= 180 and report.depth_mm <= 180
    s = demo_map.tactile
    assert report.height_mm == pytest.approx(s.base_thickness_mm + s.wall_height_mm, abs=0.01)
    assert mesh.bounds[0][2] == pytest.approx(0, abs=1e-6)  # sits flat on the bed


def test_model_dimensions_and_proportions():
    s = TactileSettings(include_legend=False, orientation_marker=False)
    fmap = rect_room(10, 5, landmarks=False)
    mesh, report = generate_tactile_model(fmap, s)
    # The long side fills the print width exactly.
    assert report.width_mm == pytest.approx(s.max_width_mm, abs=0.01)
    inner_w = report.width_mm - 2 * s.margin_mm - s.wall_width_mm
    inner_d = report.depth_mm - 2 * s.margin_mm - s.wall_width_mm
    assert inner_w / inner_d == pytest.approx(2.0, rel=1e-4)
    assert report.scale_mm_per_m == pytest.approx(inner_w / 10, rel=1e-4)


def test_print_size_setting_is_respected():
    fmap = rect_room(10, 5)
    _, small = generate_tactile_model(fmap, TactileSettings(max_width_mm=120, max_depth_mm=120))
    _, large = generate_tactile_model(fmap, TactileSettings())
    assert small.width_mm <= 120 and small.width_mm < large.width_mm


def test_door_opening_stays_open():
    fmap = process_map(rect_room(6, 4)).map
    mesh, report = generate_tactile_model(fmap)
    door = next(f for f in report.features if f.kind == "door_gap")
    x, y = door.center_mm
    cut = section_at(mesh, _wall_mid_z(fmap.tactile))
    assert not cut.contains(Point(x, y)), "door center should be empty at wall height"
    # ...while the same wall 2 m away from the door is solid.
    solid_x = x + 2.0 * report.scale_mm_per_m
    assert cut.contains(Point(solid_x, y))


def test_all_demo_doorways_stay_open(demo_map):
    mesh, report = generate_tactile_model(demo_map)
    cut = section_at(mesh, _wall_mid_z(demo_map.tactile))
    gaps = [f for f in report.features if f.kind == "door_gap"]
    assert len(gaps) == len(demo_map.doors) + len(demo_map.openings)
    for g in gaps:
        assert not cut.contains(Point(*g.center_mm)), f"{g.element_id} is blocked"


def test_narrow_doors_are_widened_to_the_minimum_gap():
    fmap = rect_room(30, 8)  # large room -> small scale, 1 m door is ~5.6 mm
    s = TactileSettings(min_door_gap_mm=8.0)
    _, report = generate_tactile_model(fmap, s)
    assert any("widened" in w for w in report.warnings)


def test_landmarks_do_not_block_walls_or_doorways(demo_map):
    warnings: list[str] = []
    _, layers = build_layers(demo_map, demo_map.tactile, warnings)
    assert len(layers.symbols) == 6
    doorways = [rect for _, _, rect in layers.gap_cuts]
    for lm, shape, _, _ in layers.symbols:
        assert not shape.intersects(layers.walls), lm.name
        assert not any(shape.intersects(d) for d in doorways), lm.name


def test_landmark_sitting_on_a_wall_is_moved_clear():
    fmap = rect_room(6, 4)
    fmap.landmarks[0].position.y = 0.0  # exactly on the south wall, in the doorway
    mesh, report = generate_tactile_model(fmap)
    entrance = next(f for f in report.features if f.element_id == "lm_in")
    assert entrance.displaced_mm > 0
    cut = section_at(mesh, _wall_mid_z(fmap.tactile))
    door = next(f for f in report.features if f.kind == "door_gap")
    assert not cut.contains(Point(*door.center_mm))


def test_features_stay_on_base(demo_map):
    demo_map.tactile.include_paths = True
    mesh, report = generate_tactile_model(demo_map)
    for f in report.features:
        if f.center_mm is not None and f.kind != "orientation_marker":
            x, y = f.center_mm
            assert 0 <= x <= report.width_mm and 0 <= y <= report.depth_mm, f.label
    assert next(c for c in report.checks if c.name == "features_on_base").passed


def test_symbols_are_distinguishable():
    def signature(t: LandmarkType):
        g = symbol_footprint(t, 0, 0, 7.0)
        parts = list(getattr(g, "geoms", [g]))
        holes = sum(len(p.interiors) for p in parts)
        vertices = len(parts[0].exterior.coords) - 1
        outline = "curved" if vertices > 16 else f"{vertices} corners"
        return (len(parts), holes, outline)
    sigs = [signature(t) for t in SYMBOL_ORDER]
    assert len(set(sigs)) == len(sigs), sigs


def test_stl_export_is_real_binary_stl(demo_map):
    mesh, _ = generate_tactile_model(demo_map)
    data = export_stl(mesh)
    (count,) = struct.unpack("<I", data[80:84])
    assert count == len(mesh.faces) > 100
    assert len(data) == 84 + 50 * count
    loaded = trimesh.load(io.BytesIO(data), file_type="stl")
    assert loaded.is_watertight
    assert loaded.volume == pytest.approx(mesh.volume, rel=1e-4)
    assert loaded.extents == pytest.approx(mesh.extents, abs=1e-3)


def test_legend_adds_depth_only():
    fmap = rect_room(10, 5)
    _, with_legend = generate_tactile_model(fmap, TactileSettings(include_legend=True))
    _, without = generate_tactile_model(fmap, TactileSettings(include_legend=False))
    assert with_legend.width_mm == pytest.approx(without.width_mm, abs=0.01)
    assert with_legend.depth_mm > without.depth_mm


def test_map_with_errors_is_refused(demo_map):
    demo_map.navigation.edges[0].a = "n_missing"
    with pytest.raises(TactileGenerationError, match="missing location"):
        generate_tactile_model(demo_map)


def test_summary_describes_the_model(demo_map):
    _, report = generate_tactile_model(demo_map)
    text = " ".join(report.summary)
    assert "synthetic" in text
    assert "Restroom: solid circle" in text
    assert "Legend" in text


def test_filename(demo_map):
    assert stl_filename(demo_map) == "touchspace-demo-building-synthetic-map.stl"
