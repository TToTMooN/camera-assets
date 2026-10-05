"""Validate portable camera assets: python scripts/validate.py --model all."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import shutil
import struct
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


class ValidationError(ValueError):
    """A delivery requirement failed, with an actionable description."""


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def available_models(root=ROOT):
    discovered = {p.name for p in (root / "models").iterdir()
                  if p.is_dir() and (p / "model.json").is_file()}
    catalog = root / "catalog/cameras.json"
    if catalog.is_file():
        discovered.update(p["id"] for p in json.loads(catalog.read_text())["cameras"])
    return sorted(discovered)


def local_file(base, filename, model_dir):
    """Resolve a portable reference and reject files outside its model package."""
    require(isinstance(filename, str) and filename, "Asset reference must be a nonempty string")
    require(not Path(filename).is_absolute() and ":" not in filename and "\\" not in filename,
            f"Use a portable relative asset reference: {filename}")
    target = (base / filename).resolve()
    require(target.is_relative_to(model_dir.resolve()), f"Asset reference escapes model package: {filename}")
    require(target.is_file(), f"Missing asset: {target}")
    return target


def glb_document(data):
    require(len(data) >= 20, "GLB is truncated")
    magic, version, length = struct.unpack_from("<4sII", data)
    require(magic == b"glTF" and version == 2 and length == len(data), "Invalid GLB 2.0 header or length")
    json_length, chunk_type = struct.unpack_from("<I4s", data, 12)
    require(chunk_type == b"JSON" and 20 + json_length <= len(data), "Missing or truncated GLB JSON chunk")
    try:
        return json.loads(data[20:20 + json_length])
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValidationError(f"Invalid GLB JSON: {error}") from error


def inertia_properties(inertia):
    import numpy as np
    try:
        ixx, iyy, izz, ixy, ixz, iyz = (float(inertia[k]) for k in ("ixx", "iyy", "izz", "ixy", "ixz", "iyz"))
    except (KeyError, ValueError) as error:
        raise ValidationError(f"Invalid inertia attributes: {error}") from error
    matrix = np.array([[ixx, ixy, ixz], [ixy, iyy, iyz], [ixz, iyz, izz]])
    require(np.all(np.isfinite(matrix)), "Inertia tensor contains nonfinite values")
    moments = np.linalg.eigvalsh(matrix)
    require(np.all(moments > 0), f"Inertia tensor is not positive definite: principal moments {moments.tolist()}")
    require(2 * moments.max() <= moments.sum() + 1e-12,
            f"Inertia principal moments violate the rigid-body triangle inequality: {moments.tolist()}")
    return matrix, moments


def validate_model(model_id, root=ROOT, write_report=True):
    import numpy as np
    import trimesh
    from scipy.spatial import ConvexHull
    from yourdfpy import URDF

    require(re.fullmatch(r"[a-z][a-z0-9_]*", model_id) is not None, f"Unsafe model ID: {model_id}")
    model_dir = root.resolve() / "models" / model_id
    meta = json.loads((model_dir / "model.json").read_text())
    path = local_file(model_dir, meta["urdf"], model_dir)
    config = json.loads(local_file(model_dir, meta["config"], model_dir).read_text())
    catalog_path = root / "catalog/cameras.json"
    if catalog_path.is_file():
        entries = [item for item in json.loads(catalog_path.read_text())["cameras"] if item["id"] == model_id]
        require(len(entries) == 1, f"Catalog must contain exactly one entry for {model_id}")
        for field in ("width_mm", "height_mm", "overall_depth_mm", "mass_kg"):
            require(np.isclose(config[field], entries[0][field], atol=1e-10, rtol=0),
                    f"Configured {field} differs from source catalog: {config[field]} vs {entries[0][field]}")
    glb_path = local_file(model_dir, meta["visual"], model_dir)
    obj_path = local_file(model_dir, meta.get("visual_obj", f"assets/meshes/{model_id}_visual.obj"), model_dir)
    tree = ET.parse(path)
    require(tree.getroot().tag == "robot", "URDF root must be <robot>")
    for node in tree.findall(".//mesh"):
        local_file(path.parent, node.attrib["filename"], model_dir)
        scale = np.fromstring(node.attrib.get("scale", "1 1 1"), sep=" ")
        require(scale.shape == (3,) and np.allclose(scale, 1), "URDF meshes must use meter units with scale='1 1 1'")
    links = tree.findall("link")
    joints = tree.findall("joint")
    link_names = [link.attrib["name"] for link in links]
    joint_names = [joint.attrib["name"] for joint in joints]
    require(len(set(link_names)) == len(link_names), "URDF has duplicate link names")
    require(len(set(joint_names)) == len(joint_names), "URDF has duplicate joint names")
    children = []
    descendants = {name: [] for name in link_names}
    for joint in joints:
        require(joint.attrib.get("type") == "fixed", "Standalone camera joints must be fixed")
        parent, child = joint.find("parent"), joint.find("child")
        require(parent is not None and child is not None, f"Joint {joint.attrib['name']} is missing parent or child")
        require(parent.attrib["link"] in link_names and child.attrib["link"] in link_names,
                f"Joint {joint.attrib['name']} references an unknown link")
        children.append(child.attrib["link"])
        descendants[parent.attrib["link"]].append(child.attrib["link"])
    require(len(children) == len(set(children)), "A URDF link has more than one parent")
    root_link = meta.get("root_link", f"{model_id}_link")
    mount_link = meta.get("mount_link", f"{model_id}_mount")
    require(set(link_names) - set(children) == {root_link} and len(joints) == len(links) - 1,
            f"URDF must have a single connected root named {root_link}")
    reached, pending = set(), [root_link]
    while pending:
        name = pending.pop()
        require(name not in reached, f"URDF graph contains a cycle at {name}")
        reached.add(name)
        pending.extend(descendants[name])
    require(reached == set(link_names), "URDF contains disconnected links or a disconnected joint cycle")
    robot = URDF.load(str(path), load_collision_meshes=True, build_collision_scene_graph=True,
                      force_collision_mesh=False)
    require(robot.base_link == root_link, f"Unexpected URDF root: {robot.base_link}")
    require(mount_link in link_names, f"Missing mount reference frame: {mount_link}")
    require(np.allclose(robot.get_transform(mount_link), np.eye(4)), "Mount reference must coincide with the root origin")
    for name in meta.get("lens_surface_frames", []):
        require(name in link_names, f"Missing declared lens surface frame: {name}")
    require(robot.scene is not None and robot.collision_scene is not None, "URDF needs visual and collision geometry")

    visual = trimesh.load_scene(obj_path).to_mesh()
    require(len(visual.vertices) > 0 and len(visual.faces) > 0, "OBJ visual has no triangles")
    require(np.all(np.isfinite(visual.vertices)), "OBJ visual contains nonfinite vertices")
    require(np.min(visual.area_faces) > 1e-16, "OBJ visual has degenerate triangles")
    expected = np.array([config["overall_depth_mm"], config["width_mm"], config["height_mm"]], dtype=float) * .001
    require(np.all(np.isfinite(expected)) and np.all(expected > 0), "Configured dimensions must be finite and positive")
    require(np.allclose(visual.extents, expected, atol=1e-7, rtol=0),
            f"Visual envelope {visual.extents.tolist()} m differs from configured depth/width/height {expected.tolist()} m")
    require(abs(visual.bounds[0, 2]) < 1e-8, f"Bottom reference origin must have Z=0; minimum Z is {visual.bounds[0, 2]:g} m")
    require(np.allclose(robot.scene.bounds, visual.bounds, atol=1e-7, rtol=0), "URDF visual bounds differ from OBJ")
    glb = trimesh.load_scene(glb_path)
    # glTF uses Y-up; all robotics geometry and reference frames use Z-up.
    glb.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))
    require(np.allclose(glb.bounds, visual.bounds, atol=1e-7, rtol=0), "GLB and OBJ bounds differ after Y-up to Z-up conversion")
    glb_mesh = glb.to_mesh()
    require(np.all(np.isfinite(glb_mesh.vertices)) and np.min(glb_mesh.area_faces) > 1e-16,
            "GLB has nonfinite vertices or degenerate triangles")
    data = glb_path.read_bytes()
    gltf = glb_document(data)
    require(all("uri" not in item for item in gltf.get("buffers", [])), "GLB has an external buffer")
    require(all("uri" not in item for item in gltf.get("images", [])), "GLB has an external image")
    manifest_path = model_dir / "assets/visual_manifest.json"
    if manifest_path.is_file():
        factors = {item.get("name"): item.get("pbrMetallicRoughness", {}).get("baseColorFactor", [1, 1, 1, 1])
                   for item in gltf.get("materials", [])}
        for material in json.loads(manifest_path.read_text()):
            require(material["name"] in factors, f"GLB is missing material {material['name']}")
            require(np.allclose(factors[material["name"]], material["rgba"], atol=1e-6, rtol=0),
                    f"GLB material {material['name']} must use the manifest's linear RGB factor")

    appearance_checks = None
    if model_id == "x5":
        require(len(links) == 4 and len(joints) == 3, "X5 must have mount and two lens surface frames")

        def component(name):
            require(name in glb.graph.nodes_geometry, f"X5 GLB is missing component: {name}")
            transform, geometry_name = glb.graph[name]
            result = glb.geometry[geometry_name].copy()
            result.apply_transform(transform)
            return result

        display = component("display_active_area")
        require(np.allclose(display.extents[1:], [.0339, .0537], atol=1e-7), "X5 active display dimensions differ from specification")
        require(component("side_key_panel").bounds[0, 1] > .022, "X5 side controls must be on screen-facing right (+Y)")
        require(component("usb_door").bounds[0, 1] > 0, "X5 USB door must be on +Y")
        require(component("battery_cover").bounds[1, 1] < -.022, "X5 battery cover must be on -Y")
        require(component("shutter_outline").bounds[1, 1] < 0, "X5 shutter outline must be on -Y")
        require(component("menu_front_rectangle").bounds[0, 1] > 0, "X5 menu outline must be on +Y")
        require(not any("front_button" in name or "record_symbol" in name for name in glb.geometry), "X5 has obsolete button/symbol geometry")
        require(len(gltf.get("images", [])) == 2, "X5 GLB must embed both surface textures")
        appearance_checks = {
            "active_display_size_mm": (display.extents[1:] * 1000).tolist(),
            "screen_facing_controls": "right (+Y)", "screen_facing_battery": "left (-Y)",
            "lower_front_controls": "outlined shutter at -Y; overlapping menu outlines at +Y",
            "basis": "Official X5 specification and product photograph; detail positions remain inferred",
        }

    collision, halfspaces = [], []
    for name in robot.collision_scene.graph.nodes_geometry:
        transform, geometry_name = robot.collision_scene.graph[name]
        mesh = robot.collision_scene.geometry[geometry_name].copy()
        mesh.apply_transform(transform)
        require(np.all(np.isfinite(mesh.vertices)), f"Collision {name} has nonfinite vertices")
        require(mesh.is_watertight and mesh.is_winding_consistent and mesh.is_convex,
                f"Collision {name} must be watertight, consistently wound and convex")
        require(mesh.volume > 0 and np.min(mesh.area_faces) > 1e-16, f"Collision {name} has nonpositive volume or degenerate faces")
        halfspaces.append(ConvexHull(mesh.vertices).equations)
        collision.append({"name": name, "triangles": len(mesh.faces), "watertight": True, "convex": True})
    require(collision, "URDF has no collision meshes")
    distance = np.full(len(visual.vertices), np.inf)
    for equations in halfspaces:
        for start in range(0, len(visual.vertices), 2000):
            end = start + 2000
            distance[start:end] = np.minimum(distance[start:end], np.max(
                visual.vertices[start:end] @ equations[:, :3].T + equations[:, 3], axis=1))
    tolerance_mm = float(config.get("collision_tolerance_mm", .2))
    require(np.isfinite(tolerance_mm) and tolerance_mm >= 0, "Collision tolerance must be finite and nonnegative")
    max_gap_mm = float(max(0, distance.max()) * 1000)
    require(max_gap_mm <= tolerance_mm + 1e-6,
            f"Collision coverage gap {max_gap_mm:.4f} mm exceeds tolerance {tolerance_mm:g} mm")
    total_mass, inertias = 0.0, []
    for link in links:
        inertial = link.find("inertial")
        if inertial is None:
            continue
        mass_node, inertia_node = inertial.find("mass"), inertial.find("inertia")
        require(mass_node is not None and inertia_node is not None,
                f"Link {link.attrib['name']} inertial needs mass and inertia elements")
        mass = float(mass_node.attrib["value"])
        require(np.isfinite(mass) and mass > 0, f"Link {link.attrib['name']} has invalid mass")
        matrix, moments = inertia_properties(inertia_node.attrib)
        total_mass += mass
        inertias.append({"link": link.attrib["name"], "matrix_kg_m2": matrix.tolist(), "principal_moments_kg_m2": moments.tolist()})
    require(np.isclose(total_mass, config["mass_kg"], atol=1e-10, rtol=0),
            f"URDF total mass {total_mass:g} kg differs from configured mass {config['mass_kg']:g} kg")
    require(inertias, "URDF has no inertial properties")
    # Copy delivery mesh directories to verify relative URDF references.
    with tempfile.TemporaryDirectory(prefix=f"{model_id}-portability-") as tmp:
        target = Path(tmp) / model_id
        shutil.copytree(model_dir / "urdf", target / "urdf")
        shutil.copytree(model_dir / "assets" / "meshes", target / "assets" / "meshes")
        relocated = target / path.relative_to(model_dir)
        copied = URDF.load(str(relocated), load_collision_meshes=True, build_collision_scene_graph=True,
                           force_collision_mesh=False)
        require(np.allclose(copied.scene.bounds, visual.bounds, atol=1e-7, rtol=0), "URDF bounds changed after relocation")
        require(np.allclose(copied.collision_scene.bounds, robot.collision_scene.bounds, atol=1e-7, rtol=0), "Collision bounds changed after relocation")
    report = {
        "model": model_id, "status": "PASS",
        "checks": ["URDF graph and portable local mesh references", "URDF load after relocation",
                   "meter dimensions and bottom reference origin", "OBJ and GLB nondegenerate triangles",
                   "self-contained GLB and matching visual bounds", "consistent linear RGB material factors",
                   "positive definite physically admissible nominal inertia",
                   "watertight convex URDF collision meshes", f"visual vertex coverage within {tolerance_mm:g} mm"],
        "visual_triangles": len(visual.faces), "visual_bounds_m": visual.bounds.tolist(),
        "dimension_order": "depth X, width Y, height Z", "visual_dimensions_m": visual.extents.tolist(),
        "materials": len(gltf.get("materials", [])), "embedded_texture_images": len(gltf.get("images", [])),
        "collision": collision, "collision_tolerance_mm": tolerance_mm,
        "max_visual_vertex_collision_halfspace_gap_mm": max_gap_mm,
        "mass_kg": total_mass, "inertia": inertias,
        "inertia_diagonal_kg_m2": np.diag(np.asarray(inertias[0]["matrix_kg_m2"])).tolist(),
        "inertia_basis": "Unmeasured nominal homogeneous-body-box approximation",
        "glb_sha256": hashlib.sha256(data).hexdigest(),
        "not_validated": ["dimensional agreement with a measured physical specimen", "optical calibration",
                          "mount interface fit", "mass distribution", "physics simulator-specific rendering and dynamics"],
    }
    if appearance_checks is not None:
        report["appearance_acceptance"] = appearance_checks
    if write_report:
        (model_dir / "docs").mkdir(exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=model_dir / "docs", suffix=".tmp", delete=False) as output:
            temporary_path = Path(output.name)
            output.write(json.dumps(report, indent=2) + "\n")
        temporary_path.replace(model_dir / "docs" / "validation.json")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    models = available_models()
    parser.add_argument("--model", choices=[*models, "all"], default="x5" if "x5" in models else "all")
    parser.add_argument("--list", action="store_true", help="List available model IDs and exit")
    parser.add_argument("--no-write", action="store_true", help="Validate without updating docs/validation.json")
    parser.add_argument("--json", action="store_true", help="Print full report JSON instead of a concise summary")
    args = parser.parse_args(argv)
    if args.list:
        print("\n".join(models))
        return 0
    reports, failures = [], []
    for model_id in models if args.model == "all" else [args.model]:
        try:
            reports.append(validate_model(model_id, write_report=not args.no_write))
        except Exception as error:
            failures.append({"model": model_id, "status": "FAIL", "error": f"{type(error).__name__}: {error}"})
            print(f"{model_id}: FAIL — {error}", file=sys.stderr)
    if args.json:
        print(json.dumps(reports[0] if len(reports) == 1 and not failures else {"reports": reports, "failures": failures}, indent=2))
    else:
        for report in reports:
            print(f"{report['model']}: PASS — {report['visual_triangles']:,} visual triangles; "
                  f"collision gap {report['max_visual_vertex_collision_halfspace_gap_mm']:.4f} mm")
        print(f"{len(reports)} passed, {len(failures)} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
