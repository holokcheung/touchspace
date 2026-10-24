"""Step 3: 2D floor plan -> 3D mesh -> STL."""
import trimesh
from shapely.geometry import Polygon, MultiPolygon
import config


def _extrude(geom, height, z0):
    """Extrude a Polygon or MultiPolygon upward from z0."""
    polys = [geom] if isinstance(geom, Polygon) else list(getattr(geom, "geoms", []))
    meshes = []
    for p in polys:
        if p.is_empty or p.area < 1e-6:
            continue
        mesh = trimesh.creation.extrude_polygon(p, height)
        mesh.apply_translation([0, 0, z0])
        meshes.append(mesh)
    return meshes


def build_mesh(plan):
    b = config.BASE_THICKNESS_MM
    overlap = 0.05  # raised parts sink slightly into the base so the slicer fuses them
    parts = _extrude(plan.base, b, 0.0)
    parts += _extrude(plan.walls, config.WALL_HEIGHT_MM + overlap, b - overlap)
    if plan.objects is not None:
        parts += _extrude(plan.objects, config.OBJECT_HEIGHT_MM + overlap, b - overlap)
    # Plain concatenation, no 3D boolean union: robust and slicers handle it fine.
    return trimesh.util.concatenate(parts)


def export_stl(mesh, path):
    mesh.export(path)
    x, y, z = mesh.extents
    print(f"Saved {path}  size {x:.1f} x {y:.1f} x {z:.1f} mm")
    if max(x, y) > config.BED_SIZE_MM:
        import math
        usable = config.BED_SIZE_MM - 2 * config.MARGIN_MM - config.WALL_THICKNESS_MM
        drawn = max(x, y) - 2 * config.MARGIN_MM - config.WALL_THICKNESS_MM
        need = math.ceil(config.SCALE * drawn / usable)
        print(f"WARNING: {max(x, y):.0f} mm is larger than the {config.BED_SIZE_MM:.0f} mm bed. "
              f"Try: python main.py <scan>.json --scale {need}")


# ---------- Optional: colour-ready export (used only with  main.py --parts) ----------
# STL cannot store colour, so each part is saved as its own STL (pick a colour per file in
# the slicer), plus one GLB that keeps the colours for web previews.
PART_COLORS = {"base": [235, 235, 235, 255], "walls": [40, 40, 40, 255], "objects": [74, 144, 217, 255]}


def build_parts(plan):
    """Same geometry as build_mesh, but kept as separate named parts."""
    b = config.BASE_THICKNESS_MM
    overlap = 0.05
    parts = {"base": _extrude(plan.base, b, 0.0),
             "walls": _extrude(plan.walls, config.WALL_HEIGHT_MM + overlap, b - overlap)}
    if plan.objects is not None:
        parts["objects"] = _extrude(plan.objects, config.OBJECT_HEIGHT_MM + overlap, b - overlap)
    return {k: trimesh.util.concatenate(v) for k, v in parts.items() if v}


def export_parts(plan, base_path):
    """Write <base>_base.stl, <base>_walls.stl, <base>_objects.stl and <base>.glb."""
    parts = build_parts(plan)
    scene = trimesh.Scene()
    for name, mesh in parts.items():
        mesh.export(f"{base_path}_{name}.stl")
        coloured = mesh.copy()
        # Colour the vertices directly. Colouring faces would make trimesh convert
        # face colours to vertex colours, which needs the extra library scipy.
        coloured.visual.vertex_colors = PART_COLORS[name]
        scene.add_geometry(coloured, node_name=name)
    scene.export(f"{base_path}.glb")
    print(f"Saved {', '.join(f'{base_path}_{n}.stl' for n in parts)} and {base_path}.glb")
