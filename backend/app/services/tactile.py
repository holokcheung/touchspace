"""Turn a normalized floor map into a printable tactile STL model.

Pipeline (all 2D work in millimeters with Shapely, 3D with Trimesh/Manifold):

  1. Fit the plan onto the print bed: uniform scale, margins, optional legend strip.
  2. Walls: buffer each centerline to a fixed tactile width, union, then cut
     door and opening gaps (widened to a minimum the finger can find).
  3. Objects the user kept: low blocks, kept clear of walls and doorways.
  4. Landmarks: standard symbols, nudged off walls/doorways/other symbols,
     preferring to stay inside their own room.
  5. Optional raised dot paths along navigation edges.
  6. Legend strip and a cut corner on the base for orientation.
  7. Extrude every layer, fuse everything to the base into one solid, and
     verify the mesh before it is handed out.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

import numpy as np
import shapely
import trimesh
from shapely import affinity
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.prepared import prep

from app.models.map import FloorMap, Landmark, LandmarkType, Point2D
from app.models.tactile import MeshCheck, TactileFeature, TactileReport, TactileSettings
from app.services.floorplan import compute_bounds, validate_map
from app.services.symbols import SYMBOL_NAMES, SYMBOL_ORDER, has_symbol, symbol_footprint

# Raised parts start this far below the base's top face so the boolean union
# fuses them into the base instead of leaving coplanar touching faces.
EMBED_MM = 0.2
MIN_PART_AREA_MM2 = 1.0
PRINT_GRID_MM = 0.001
WALL_CLEARANCE_MM = 1.2
SYMBOL_SPACING_MM = 1.5
LEGEND_GAP_MM = 3.0
LEGEND_DIVIDER_MM = 1.0
# Wider space above the divider so it is not mistaken for the building's outer wall.
LEGEND_ABOVE_DIVIDER_MM = 7.0
LEGEND_ITEM_GAP_MM = 6.0
ORIENTATION_CORNER_MM = 6.0


class TactileGenerationError(RuntimeError):
    def __init__(self, message: str, checks: list[MeshCheck] | None = None):
        super().__init__(message)
        self.checks = checks or []


# --------------------------------------------------------------------------- layout


@dataclass
class PrintLayout:
    scale: float  # mm per meter
    offset_x: float
    offset_y: float
    base_w: float
    base_d: float
    legend_band: float
    content: Polygon  # area available to map features, in mm

    def xy(self, x: float, y: float) -> tuple[float, float]:
        return (x * self.scale + self.offset_x, y * self.scale + self.offset_y)

    def pt(self, p: Point2D) -> tuple[float, float]:
        return self.xy(p.x, p.y)


def _legend_band(settings: TactileSettings) -> float:
    return settings.landmark_size_mm + LEGEND_GAP_MM + LEGEND_DIVIDER_MM + LEGEND_ABOVE_DIVIDER_MM


def compute_layout(fmap: FloorMap, settings: TactileSettings, with_legend: bool) -> PrintLayout:
    b = compute_bounds(fmap)
    xs, ys = [b.min_x, b.max_x], [b.min_y, b.max_y]
    for lm in fmap.landmarks:
        if lm.show_on_tactile:
            xs.append(lm.position.x)
            ys.append(lm.position.y)
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
    plan_w = max(max_x - min_x, 0.5)
    plan_d = max(max_y - min_y, 0.5)

    band = _legend_band(settings) if with_legend else 0.0
    ww = settings.wall_width_mm
    avail_w = settings.max_width_mm - 2 * settings.margin_mm - ww
    avail_d = settings.max_depth_mm - 2 * settings.margin_mm - ww - band
    if avail_w <= 0 or avail_d <= 0:
        raise TactileGenerationError("Print size is too small for the chosen margins and legend.")
    scale = min(avail_w / plan_w, avail_d / plan_d)

    base_w = plan_w * scale + 2 * settings.margin_mm + ww
    base_d = plan_d * scale + 2 * settings.margin_mm + ww + band
    offset_x = settings.margin_mm + ww / 2 - min_x * scale
    offset_y = settings.margin_mm + band + ww / 2 - min_y * scale
    content = box(settings.margin_mm, settings.margin_mm + band, base_w - settings.margin_mm, base_d - settings.margin_mm)
    return PrintLayout(scale, offset_x, offset_y, base_w, base_d, band, content)


# --------------------------------------------------------------------------- 2D layers


@dataclass
class Layers:
    base: Polygon
    walls: BaseGeometry
    gap_cuts: list[tuple[str, str, Polygon]] = field(default_factory=list)  # (gap id, kind, rect)
    objects: list[tuple[str, str, BaseGeometry]] = field(default_factory=list)
    symbols: list[tuple[Landmark, BaseGeometry, tuple[float, float], float]] = field(default_factory=list)
    paths: list[BaseGeometry] = field(default_factory=list)
    legend: list[tuple[LandmarkType, BaseGeometry]] = field(default_factory=list)
    divider: BaseGeometry | None = None


def _polygons(geom: BaseGeometry) -> list[Polygon]:
    if geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom] if geom.area >= MIN_PART_AREA_MM2 else []
    return [p for g in getattr(geom, "geoms", []) for p in _polygons(g)]


def _clean(geom: BaseGeometry) -> BaseGeometry:
    parts = _polygons(geom.buffer(0))
    return MultiPolygon(parts) if len(parts) != 1 else parts[0]


def _oriented_rect(cx: float, cy: float, length: float, width: float, angle: float) -> Polygon:
    rect = box(-length / 2, -width / 2, length / 2, width / 2)
    return affinity.translate(affinity.rotate(rect, angle, origin=(0, 0), use_radians=True), cx, cy)


def _base_outline(layout: PrintLayout, settings: TactileSettings) -> Polygon:
    w, d = layout.base_w, layout.base_d
    if not settings.orientation_marker:
        return box(0, 0, w, d)
    c = min(ORIENTATION_CORNER_MM, settings.margin_mm * 0.75)
    return Polygon([(0, 0), (w, 0), (w, d), (c, d), (0, d - c)])


def _build_walls(fmap: FloorMap, layout: PrintLayout, settings: TactileSettings, warnings: list[str]) -> tuple[BaseGeometry, list]:
    ww = settings.wall_width_mm
    bodies = []
    for wall in fmap.walls:
        a, b = layout.pt(wall.start), layout.pt(wall.end)
        if math.dist(a, b) < 1e-6:
            continue
        bodies.append(LineString([a, b]).buffer(ww / 2, cap_style="square", join_style="mitre"))
    walls = unary_union(bodies)

    walls_by_id = {w.id: w for w in fmap.walls}
    cuts: list[tuple[str, str, Polygon]] = []
    for gap in fmap.gaps:
        wall = walls_by_id.get(gap.wall_id or "")
        if wall is None:
            warnings.append(f"{gap.kind.capitalize()} '{gap.id}' is not attached to a wall and was skipped.")
            continue
        wall_len_mm = wall.length * layout.scale
        true_mm = gap.width * layout.scale
        gap_mm = min(max(true_mm, settings.min_door_gap_mm), max(wall_len_mm - ww, 0.0))
        if gap_mm <= 0:
            warnings.append(f"{gap.kind.capitalize()} '{gap.id}' does not fit on its wall and was skipped.")
            continue
        if gap_mm > true_mm + 0.05:
            warnings.append(f"{gap.kind.capitalize()} '{gap.id}' was widened from {true_mm:.1f} mm to {gap_mm:.1f} mm so it can be felt.")
        cx, cy = layout.pt(gap.position)
        cuts.append((gap.id, gap.kind, _oriented_rect(cx, cy, gap_mm, ww * 1.5, wall.angle)))

    if cuts:
        walls = walls.difference(unary_union([c[2] for c in cuts]))
    return _clean(walls), cuts


def _build_objects(fmap: FloorMap, layout: PrintLayout, settings: TactileSettings, keepout: BaseGeometry) -> list:
    out = []
    if not settings.include_objects:
        return out
    for obj in fmap.objects:
        if not obj.include_in_tactile or obj.hidden:
            continue
        cx, cy = layout.pt(obj.position)
        rect = _oriented_rect(cx, cy, obj.width * layout.scale, obj.depth * layout.scale, obj.rotation)
        shape = _clean(rect.difference(keepout).intersection(layout.content))
        if not shape.is_empty:
            out.append((obj.id, obj.label or obj.category, shape))
    return out


def _room_polygon_mm(fmap: FloorMap, layout: PrintLayout, x: float, y: float) -> Polygon | None:
    for room in fmap.rooms:
        poly = Polygon([layout.pt(p) for p in room.polygon])
        if poly.is_valid and poly.contains(Point(x, y)):
            return poly
    return None


def _place_symbol(lm: Landmark, layout: PrintLayout, settings: TactileSettings, obstacles: BaseGeometry,
                  room: Polygon | None) -> tuple[BaseGeometry, tuple[float, float], float] | None:
    """Find the closest spot to the landmark where its symbol touches nothing else."""
    size = settings.landmark_size_mm
    ox, oy = layout.pt(lm.position)
    blocked = prep(obstacles) if not obstacles.is_empty else None
    content = prep(layout.content)
    room_p = prep(room) if room is not None else None
    fallback = None
    max_r = size * 3
    for r in np.arange(0.0, max_r + 1e-9, 0.5):
        angles = [0.0] if r == 0 else np.linspace(0, 2 * math.pi, 24, endpoint=False)
        for a in angles:
            cx, cy = ox + r * math.cos(a), oy + r * math.sin(a)
            shape = symbol_footprint(lm.type, cx, cy, size)
            hull = shape.convex_hull
            if not content.contains(hull) or (blocked is not None and blocked.intersects(hull)):
                continue
            if room_p is None or room_p.contains(hull):
                return shape, (cx, cy), float(r)
            if fallback is None:
                fallback = (shape, (cx, cy), float(r))
    return fallback


def _build_paths(fmap: FloorMap, layout: PrintLayout, settings: TactileSettings, keepout: BaseGeometry) -> list:
    nodes = {n.id: n for n in fmap.navigation.nodes}
    blocked = prep(keepout)
    r = settings.path_dot_diameter_mm / 2
    dots = []
    taken: list[tuple[float, float]] = []
    for edge in fmap.navigation.edges:
        if not edge.traversable or edge.a not in nodes or edge.b not in nodes:
            continue
        line = LineString([layout.pt(nodes[edge.a].position), layout.pt(nodes[edge.b].position)])
        d = settings.path_dot_spacing_mm / 2
        while d < line.length:
            p = line.interpolate(d)
            dot = p.buffer(r, quad_segs=4)
            too_close = any(math.dist((p.x, p.y), t) < settings.path_dot_spacing_mm * 0.6 for t in taken)
            if not too_close and not blocked.intersects(dot) and layout.content.contains(dot):
                dots.append(dot)
                taken.append((p.x, p.y))
            d += settings.path_dot_spacing_mm
    return dots


def build_layers(fmap: FloorMap, settings: TactileSettings, warnings: list[str]) -> tuple[PrintLayout, Layers]:
    shown = [lm for lm in fmap.landmarks if settings.include_landmarks and lm.show_on_tactile]
    legend_types = [t for t in SYMBOL_ORDER if any(lm.type == t for lm in shown)]
    want_legend = settings.include_legend and bool(legend_types)

    layout = compute_layout(fmap, settings, with_legend=want_legend)
    if want_legend:
        size = settings.landmark_size_mm
        needed = len(legend_types) * size + (len(legend_types) - 1) * LEGEND_ITEM_GAP_MM
        if needed > layout.base_w - 2 * settings.margin_mm:
            warnings.append("The legend does not fit across this print width and was left off.")
            want_legend = False
            layout = compute_layout(fmap, settings, with_legend=False)

    base = _base_outline(layout, settings)
    walls, cuts = _build_walls(fmap, layout, settings, warnings)
    layers = Layers(base=base, walls=walls, gap_cuts=cuts)

    doorways = unary_union([c[2] for c in cuts]) if cuts else Polygon()
    keepout = unary_union([walls.buffer(1.0), doorways.buffer(0.5)])
    layers.objects = _build_objects(fmap, layout, settings, keepout)

    obstacles = unary_union([
        walls.buffer(WALL_CLEARANCE_MM), doorways.buffer(0.5),
        *[shape.buffer(1.0) for _, _, shape in layers.objects],
    ])
    for lm in shown:
        if not has_symbol(lm.type):
            continue
        ox, oy = layout.pt(lm.position)
        placed = _place_symbol(lm, layout, settings, obstacles, _room_polygon_mm(fmap, layout, ox, oy))
        if placed is None:
            warnings.append(f"No clear spot was found for the '{lm.name}' symbol, so it was left off the model.")
            continue
        shape, center, moved = placed
        layers.symbols.append((lm, shape, center, moved))
        obstacles = obstacles.union(shape.buffer(SYMBOL_SPACING_MM))
        if moved > settings.landmark_size_mm:
            warnings.append(f"The '{lm.name}' symbol was moved {moved:.1f} mm to keep it clear of walls and doorways.")

    if settings.include_paths:
        layers.paths = _build_paths(fmap, layout, settings, obstacles)

    if want_legend:
        size = settings.landmark_size_mm
        y = settings.margin_mm + size / 2
        for i, t in enumerate(legend_types):
            x = settings.margin_mm + size / 2 + i * (size + LEGEND_ITEM_GAP_MM)
            layers.legend.append((t, symbol_footprint(t, x, y, size)))
        dy = settings.margin_mm + size + LEGEND_GAP_MM
        layers.divider = box(settings.margin_mm, dy, layout.base_w - settings.margin_mm, dy + LEGEND_DIVIDER_MM)

    return layout, layers


# --------------------------------------------------------------------------- 3D


def _printable(geom: BaseGeometry) -> list[Polygon]:
    """Snap to a 1 µm grid and drop redundant vertices.

    Scan coordinates carry float noise; vertices a few nanometers apart
    triangulate into degenerate faces and break the boolean union.
    """
    snapped = shapely.set_precision(geom, PRINT_GRID_MM).simplify(PRINT_GRID_MM, preserve_topology=True)
    return _polygons(snapped.buffer(0))


def _extrude(geom: BaseGeometry, z0: float, height: float) -> list[trimesh.Trimesh]:
    meshes = []
    for poly in _printable(geom):
        m = trimesh.creation.extrude_polygon(poly, height)
        if not m.is_volume:
            raise TactileGenerationError(f"A {poly.area:.1f} mm² part could not be turned into a printable solid.")
        m.apply_translation([0, 0, z0])
        meshes.append(m)
    return meshes


def _raised(geom: BaseGeometry, settings: TactileSettings, height: float) -> list[trimesh.Trimesh]:
    return _extrude(geom, settings.base_thickness_mm - EMBED_MM, height + EMBED_MM)


def build_mesh(layers: Layers, settings: TactileSettings) -> trimesh.Trimesh:
    parts = _extrude(layers.base, 0.0, settings.base_thickness_mm)
    parts += _raised(layers.walls, settings, settings.wall_height_mm)
    for _, _, shape in layers.objects:
        parts += _raised(shape, settings, settings.object_height_mm)
    for _, shape, _, _ in layers.symbols:
        parts += _raised(shape, settings, settings.landmark_height_mm)
    for dot in layers.paths:
        parts += _raised(dot, settings, settings.path_dot_height_mm)
    for _, shape in layers.legend:
        parts += _raised(shape, settings, settings.landmark_height_mm)
    if layers.divider is not None:
        parts += _raised(layers.divider, settings, LEGEND_DIVIDER_MM)
    if len(parts) == 1:
        return parts[0]
    return trimesh.boolean.union(parts, engine="manifold")


def _max_feature_height(layers: Layers, settings: TactileSettings) -> float:
    heights = [settings.wall_height_mm] if not layers.walls.is_empty else [0.0]
    if layers.objects:
        heights.append(settings.object_height_mm)
    if layers.symbols or layers.legend:
        heights.append(settings.landmark_height_mm)
    if layers.paths:
        heights.append(settings.path_dot_height_mm)
    if layers.divider is not None:
        heights.append(LEGEND_DIVIDER_MM)
    return max(heights)


def check_mesh(mesh: trimesh.Trimesh, layers: Layers, layout: PrintLayout, settings: TactileSettings) -> list[MeshCheck]:
    checks: list[MeshCheck] = []
    ext = mesh.extents if len(mesh.faces) else np.zeros(3)
    checks.append(MeshCheck(name="not_empty", passed=len(mesh.faces) > 0 and mesh.volume > 0,
                            detail=f"{len(mesh.faces)} triangles, volume {mesh.volume:.0f} mm³"))
    checks.append(MeshCheck(name="watertight", passed=bool(mesh.is_watertight),
                            detail="Every edge is shared by exactly two faces." if mesh.is_watertight else "Mesh has open edges."))
    checks.append(MeshCheck(name="is_volume", passed=bool(mesh.is_volume),
                            detail="Consistent winding and positive volume." if mesh.is_volume else "Mesh does not enclose a valid volume."))
    bodies = len(mesh.split(only_watertight=False)) if len(mesh.faces) else 0
    checks.append(MeshCheck(name="single_body", passed=bodies == 1,
                            detail=f"{bodies} connected part(s); everything should be fused to the base."))
    fits = ext[0] <= settings.max_width_mm + 1e-6 and ext[1] <= settings.max_depth_mm + 1e-6
    checks.append(MeshCheck(name="fits_print_area", passed=bool(fits),
                            detail=f"{ext[0]:.1f} × {ext[1]:.1f} mm within {settings.max_width_mm:.0f} × {settings.max_depth_mm:.0f} mm"))
    base_area = layers.base.buffer(1e-6)
    features = [layers.walls, *[s for _, _, s in layers.objects], *[s for _, s, _, _ in layers.symbols],
                *layers.paths, *[s for _, s in layers.legend]]
    if layers.divider is not None:
        features.append(layers.divider)
    outside = sum(1 for f in features if not f.is_empty and not base_area.contains(f))
    checks.append(MeshCheck(name="features_on_base", passed=outside == 0,
                            detail="All raised features lie on the base." if outside == 0 else f"{outside} feature(s) extend past the base."))
    expected_h = settings.base_thickness_mm + _max_feature_height(layers, settings)
    checks.append(MeshCheck(name="height", passed=abs(ext[2] - expected_h) < 0.05,
                            detail=f"{ext[2]:.2f} mm tall, expected {expected_h:.2f} mm"))
    return checks


# --------------------------------------------------------------------------- description


def _region(x: float, y: float, layout: PrintLayout) -> str:
    minx, miny, maxx, maxy = layout.content.bounds
    fx = (x - minx) / max(maxx - minx, 1e-9)
    fy = (y - miny) / max(maxy - miny, 1e-9)
    col = "left" if fx < 1 / 3 else "right" if fx > 2 / 3 else "middle"
    row = "bottom" if fy < 1 / 3 else "top" if fy > 2 / 3 else "middle"
    if row == "middle" and col == "middle":
        return "center"
    if row == "middle":
        return f"middle of the {col} side"
    if col == "middle":
        return f"middle of the {row} edge"
    return f"{row} {col}"


def _summary(fmap: FloorMap, layout: PrintLayout, layers: Layers, settings: TactileSettings, height: float) -> list[str]:
    lines = [
        f"Tactile map of {fmap.name}: {layout.base_w:.0f} by {layout.base_d:.0f} millimeters, "
        f"{height:.1f} millimeters tall at the highest point.",
        f"Scale: 1 meter of floor equals {layout.scale:.1f} millimeters on the map (about 1:{round(1000 / layout.scale)}).",
    ]
    if fmap.source.synthetic:
        lines.append("This model is generated from a synthetic demo layout, not a scan of a real place.")
    if settings.orientation_marker:
        lines.append("The top-left corner of the base is cut off at an angle. Keep that corner at the top left to read the map upright.")
    n_doors = sum(1 for _, kind, _ in layers.gap_cuts if kind == "door")
    n_open = sum(1 for _, kind, _ in layers.gap_cuts if kind == "opening")
    lines.append(f"Walls are raised {settings.wall_height_mm:g} mm and {settings.wall_width_mm:g} mm wide. "
                 f"There are {n_doors} door gap(s) and {n_open} wider opening(s) in the walls.")
    for lm, _, center, _ in layers.symbols:
        lines.append(f"{lm.name}: {SYMBOL_NAMES[lm.type]}, {_region(*center, layout)}.")
    if layers.objects:
        lines.append("Low raised blocks show: " + ", ".join(label for _, label, _ in layers.objects) + ".")
    if layers.paths:
        lines.append("Rows of small dots trace the walkable routes recorded on the map.")
    if layers.legend:
        key = ", ".join(f"{SYMBOL_NAMES[t]} means {t.value}" for t, _ in layers.legend)
        lines.append(f"Legend along the bottom edge, below a raised line, from left to right: {key}.")
    return lines


# --------------------------------------------------------------------------- public API


def generate_tactile_model(fmap: FloorMap, settings: TactileSettings | None = None) -> tuple[trimesh.Trimesh, TactileReport]:
    """Generate and verify the tactile mesh for a map. Raises TactileGenerationError on failure."""
    settings = settings or fmap.tactile
    errors = [i for i in validate_map(fmap) if i.severity == "error"]
    if errors:
        raise TactileGenerationError("Fix these map problems first: " + "; ".join(e.message for e in errors))

    warnings: list[str] = []
    layout, layers = build_layers(fmap, settings, warnings)
    if layers.walls.is_empty:
        raise TactileGenerationError("No wall geometry was left after processing; nothing to print.")

    mesh = build_mesh(layers, settings)
    checks = check_mesh(mesh, layers, layout, settings)
    failed = [c for c in checks if not c.passed]
    if failed:
        raise TactileGenerationError("The generated model failed checks: " + "; ".join(f"{c.name} ({c.detail})" for c in failed), checks)

    features: list[TactileFeature] = [
        TactileFeature(kind="base", label="Base plate", size_mm=(layout.base_w, layout.base_d), height_mm=settings.base_thickness_mm),
        TactileFeature(kind="wall", label=f"{len(fmap.walls)} wall segments", height_mm=settings.wall_height_mm),
    ]
    for gap_id, kind, rect in layers.gap_cuts:
        c = rect.centroid
        features.append(TactileFeature(kind="door_gap", label=f"{kind} gap", element_id=gap_id, center_mm=(c.x, c.y)))
    for obj_id, label, shape in layers.objects:
        c = shape.centroid
        minx, miny, maxx, maxy = shape.bounds
        features.append(TactileFeature(kind="object", label=label, element_id=obj_id, center_mm=(c.x, c.y),
                                       size_mm=(maxx - minx, maxy - miny), height_mm=settings.object_height_mm))
    for lm, _, center, moved in layers.symbols:
        features.append(TactileFeature(kind="landmark", label=lm.name, element_id=lm.id, symbol=SYMBOL_NAMES[lm.type],
                                       center_mm=center, size_mm=(settings.landmark_size_mm,) * 2,
                                       height_mm=settings.landmark_height_mm, displaced_mm=round(moved, 2)))
    for t, shape in layers.legend:
        c = shape.centroid
        features.append(TactileFeature(kind="legend", label=f"Legend: {t.value}", symbol=SYMBOL_NAMES[t], center_mm=(c.x, c.y)))
    if layers.paths:
        features.append(TactileFeature(kind="path", label=f"{len(layers.paths)} path dots", height_mm=settings.path_dot_height_mm))
    if settings.orientation_marker:
        features.append(TactileFeature(kind="orientation_marker", label="Cut top-left corner", center_mm=(0.0, layout.base_d)))
    for lm in fmap.landmarks:
        if settings.include_landmarks and lm.show_on_tactile and not has_symbol(lm.type):
            pos = layout.pt(lm.position)
            features.append(TactileFeature(kind="landmark", label=lm.name, element_id=lm.id, center_mm=pos,
                                           note="Named area with no tactile symbol; described by voice only."))

    height = float(mesh.extents[2])
    report = TactileReport(
        map_id=fmap.id,
        width_mm=round(float(mesh.extents[0]), 2),
        depth_mm=round(float(mesh.extents[1]), 2),
        height_mm=round(height, 2),
        scale_mm_per_m=round(layout.scale, 3),
        scale_ratio=f"1:{round(1000 / layout.scale)}",
        triangle_count=len(mesh.faces),
        volume_mm3=round(float(mesh.volume), 1),
        watertight=bool(mesh.is_watertight),
        body_count=1,
        checks=checks,
        features=features,
        warnings=warnings,
        summary=_summary(fmap, layout, layers, settings, height),
        settings=settings,
    )
    return mesh, report


def export_stl(mesh: trimesh.Trimesh) -> bytes:
    """Binary STL in millimeters."""
    data = mesh.export(file_type="stl")
    return data if isinstance(data, bytes) else data.encode()


def stl_filename(fmap: FloorMap) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", fmap.name.lower()).strip("-")
    slug = re.sub(r"^touchspace-?", "", slug) or "room"
    return f"touchspace-{slug}-map.stl"
