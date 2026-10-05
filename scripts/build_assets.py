"""Build source-grounded camera envelope assets without Blender.

New exteriors are independent approximations, not reconstructed scans. The
existing detailed X5 asset is retained; rebuild it with x5/build_model.py.
Authoring is mm, export is m: X depth/front, Y width, Z up, bottom origin.
"""
from pathlib import Path
import argparse
import json
import math
import re
import xml.etree.ElementTree as ET
from types import SimpleNamespace

import numpy as np
import trimesh
import export_mjcf
from appearance.common import rounded_panel, revolved

ROOT = Path(__file__).resolve().parents[1]


def read_catalog():
    data = json.loads((ROOT / "catalog/cameras.json").read_text())
    cameras = data["cameras"]
    ids = [p["id"] for p in cameras]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate camera IDs in catalog")
    for p in cameras:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", p["id"]):
            raise ValueError(f"Unsafe camera ID: {p['id']}")
        for key in ("width_mm", "height_mm", "overall_depth_mm", "mass_kg"):
            if not math.isfinite(p[key]) or p[key] <= 0:
                raise ValueError(f"{p['id']}: invalid {key}")
        if p["profile"] not in {"detailed_x5", "dual_lens", "modular_dual", "wearable_capsule",
                                 "wearable_square", "action", "modular_action", "pod", "case",
                                 "stereo_bar", "stereo_box"}:
            raise ValueError(f"{p['id']}: unknown geometry profile {p['profile']}")
    return cameras


def srgb_to_linear(color):
    c = np.asarray(color[:3], dtype=float)
    return np.where(c <= .04045, c / 12.92, ((c + .055) / 1.055) ** 2.4)


def obj_file(path, parts, mtl=None):
    """Portable indexed OBJ, with explicit normals and high meter precision."""
    with path.open("w") as out:
        out.write("# Independent procedural camera geometry; meters; Z up\n")
        if mtl:
            out.write(f"mtllib {mtl}\n")
        offset = 1
        for name, mesh, material, _ in parts:
            out.write(f"o {name}\n")
            for v in mesh.vertices:
                out.write("v " + " ".join(f"{c:.10f}" for c in v) + "\n")
            for v in mesh.vertex_normals:
                out.write("vn " + " ".join(f"{c:.8f}" for c in v) + "\n")
            if mtl:
                out.write(f"usemtl {material}\n")
            for face in mesh.faces:
                out.write("f " + " ".join(f"{int(i)+offset}//{int(i)+offset}" for i in face) + "\n")
            offset += len(mesh.vertices)


def write_urdf(model_dir, config, manifest, collisions, surfaces):
    model_id = model_dir.name
    robot = ET.Element("robot", name=model_id)
    link = ET.SubElement(robot, "link", name=f"{model_id}_link")
    inertial = ET.SubElement(link, "inertial")
    ET.SubElement(inertial, "origin", xyz=f"0 0 {config['com_height_mm']*.001:.12g}", rpy="0 0 0")
    mass = config["mass_kg"]
    x, y, z = [config[k] * .001 for k in ("overall_depth_mm", "width_mm", "height_mm")]
    diagonal = [mass*(y*y+z*z)/12, mass*(x*x+z*z)/12, mass*(x*x+y*y)/12]
    ET.SubElement(inertial, "mass", value=str(mass))
    ET.SubElement(inertial, "inertia", ixx=f"{diagonal[0]:.12g}", iyy=f"{diagonal[1]:.12g}",
                  izz=f"{diagonal[2]:.12g}", ixy="0", ixz="0", iyz="0")
    for part in manifest:
        visual = ET.SubElement(link, "visual", name=part["name"])
        geo = ET.SubElement(visual, "geometry")
        ET.SubElement(geo, "mesh", filename=part["file"], scale="1 1 1")
        mat = ET.SubElement(visual, "material", name=part["name"])
        c = np.asarray(part["rgba"][:3])
        c = np.where(c <= .0031308, c*12.92, 1.055*c**(1/2.4)-.055)
        ET.SubElement(mat, "color", rgba=" ".join(f"{v:.6f}" for v in [*c, 1]))
    for name in collisions:
        co = ET.SubElement(link, "collision", name=name)
        geo = ET.SubElement(co, "geometry")
        ET.SubElement(geo, "mesh", filename=f"../assets/meshes/collision/{name}.stl", scale="1 1 1")
    markers = [(f"{model_id}_mount", [0, 0, 0], [0, 0, 0])]
    for name, pos, sign in surfaces:
        markers.append((name, pos, [-math.pi/2, 0, -sign*math.pi/2]))
    for name, pos, rpy in markers:
        ET.SubElement(robot, "link", name=name)
        joint = ET.SubElement(robot, "joint", name=f"{name}_fixed", type="fixed")
        ET.SubElement(joint, "parent", link=f"{model_id}_link")
        ET.SubElement(joint, "child", link=name)
        ET.SubElement(joint, "origin", xyz=" ".join(f"{v:.12g}" for v in pos), rpy=" ".join(f"{v:.12g}" for v in rpy))
    ET.indent(robot, space="  ")
    ET.ElementTree(robot).write(model_dir / f"urdf/{model_id}.urdf", encoding="utf-8", xml_declaration=True)


def build(camera):
    model_id = camera["id"]
    model_dir = ROOT / "models" / model_id
    if model_id == "x5":
        if not (model_dir / "assets/meshes/x5_visual.glb").is_file():
            raise ValueError("Detailed X5 missing: run scripts/x5/build_model.py with bpy first")
        meta = json.loads((model_dir / "model.json").read_text())
        # These remain geometric surface references, not optical centers. Keep
        # the same local +Z-outward convention as the other camera families.
        surfaces = [("x5_front_lens_surface", 1), ("x5_rear_lens_surface", -1)]
        urdf_path = model_dir / meta["urdf"]
        robot = ET.parse(urdf_path)
        frame_joints = {joint.find("child").get("link"): joint for joint in robot.findall("joint")}
        for name, sign in surfaces:
            if name not in frame_joints:
                raise ValueError(f"X5 URDF is missing geometric surface frame: {name}")
            origin = frame_joints[name].find("origin")
            if origin is None:
                raise ValueError(f"X5 surface frame is missing its origin: {name}")
            origin.set("rpy", f"{-math.pi/2:.12g} 0 {-sign*math.pi/2:.12g}")
        ET.indent(robot, space="  ")
        robot.write(urdf_path, encoding="utf-8", xml_declaration=True)
        meta.update(family=camera["family"], fidelity="detailed_reference_exterior",
                    brand=camera.get("brand", "Insta360"), accuracy_notes=camera["accuracy_notes"],
                    root_link="x5_link", mount_link="x5_mount", sources=camera["sources"],
                    lens_surface_frames=[name for name, _ in surfaces],
                    origin_description="Bottom mount reference; interface and COM are unmeasured")
        (model_dir / "model.json").write_text(json.dumps(meta, indent=2) + "\n")
        from sensor_manifest import ensure_template
        ensure_template(camera, model_dir)
        export_mjcf.export_model(model_id)
        print("x5: retained detailed visual and URDF", flush=True)
        return
    for folder in ("config", "urdf", "docs", "preview", "assets/meshes/visual", "assets/meshes/collision"):
        (model_dir / folder).mkdir(parents=True, exist_ok=True)
    w, h, overall = [camera[k] for k in ("width_mm", "height_mm", "overall_depth_mm")]
    profile = camera["profile"]
    estimates = camera.get("estimated_geometry", {})
    dual = profile in ("dual_lens", "modular_dual")
    stereo = profile in ("stereo_bar", "stereo_box")
    accessory = camera["family"] == "accessory"
    d = camera.get("body_depth_mm") or estimates.get("body_depth_mm") or overall * (.68 if dual else .80)
    if accessory or stereo:
        d = overall
    if not 0 < d <= overall:
        raise ValueError(f"{model_id}: body depth exceeds envelope")
    # Center the *total* depth envelope. A single lens protrudes at +X only.
    body_x = 0 if dual or accessory else -(overall-d)/2
    body_front = body_x+d/2
    radius = estimates.get("corner_radius_mm", min(w*.14, h*.12, 8))
    if profile == "wearable_capsule":
        radius = min(w/2-.1, h/2-.1)
    colors = {
        "housing": camera.get("color", [.13, .145, .16, 1]),
        "rubber": [.065, .075, .085, 1], "seam": [.025, .03, .035, 1],
        "lens_ring": [.18, .20, .22, 1], "optical_glass": [.015, .045, .06, 1],
        "screen": [.018, .025, .032, 1], "status": [.04, .55, .60, 1],
        "modular_battery": [.75, .055, .06, 1],
    }
    parts = []
    collision_proxies = {}
    material_settings = {}
    def add(name, mesh, material="housing", collision=None):
        if collision is None:
            collision = "body_bar" if profile == "stereo_box" else "body"
        rgba = np.asarray(colors[material])
        mesh.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
            name=material, baseColorFactor=np.round(rgba*255).astype(np.uint8),
            metallicFactor=.65 if material == "lens_ring" else 0.,
            roughnessFactor=.12 if material in ("optical_glass", "screen") else .65))
        parts.append((name, mesh, material, collision))
    # Reserve shallow face recesses for panels; placing a display inside a solid
    # housing makes it invisible in depth-buffered renderers.
    front_inset = .05 if accessory else .20
    rear_screen = (profile not in ("wearable_capsule", "wearable_square", "case") and not dual and not stereo) or profile == "modular_dual"
    if profile == "stereo_box":
        # Original OAK-D enclosure: broad camera bar, narrower processing stem.
        # This two-hull layout preserves the free space beside the lower stem.
        for label, pw, ph, pz in [("bar", w, 24., h-12.), ("stem", 50., h-24.+1, (h-24.+1)/2)]:
            group = f"body_{label}"
            add(group, rounded_panel(pw, ph, d-.4, min(2, ph*.1), (body_x, 0, pz)), collision=group)
            for sign in (-1, 1):
                add(f"{label}_skin_{sign}", rounded_panel(pw-.2, ph-.2, .1, 1.8,
                    (body_x+sign*(d/2-(.20 if sign == 1 else .05)), 0, pz), (sign, 0, 0)), collision=group)
    else:
        add("body_shell", rounded_panel(w, h, d-.4, radius, (body_x, 0, h/2)))
        add("front_face_skin", rounded_panel(w-.2, h-.2, .10, max(.2, radius-.1),
            (body_front-front_inset, 0, h/2)))
        add("rear_face_skin", rounded_panel(w-.2, h-.2, .10, max(.2, radius-.1),
            (body_x-d/2+(.20 if rear_screen else .05), 0, h/2), (-1, 0, 0)))
    surfaces = []
    if stereo:
        sensor_h, sensor_z = (22., h-12.) if profile == "stereo_box" else (h*.78, h*.53)
        add("sensor_face", rounded_panel(w*.97, sensor_h, .08, min(2, h*.08),
             (body_front-.10, 0, sensor_z)), "seam")
        for label, offset in [("left", w*.34), ("right", -w*.34)] + ([("rgb", 0)] if profile == "stereo_box" or model_id.startswith("realsense") else []):
            r = min(sensor_h*.29, w*.065)
            center = (body_front, offset, sensor_z)
            add(label+"_window_ring", revolved([(r, -.13), (r, -.04)], center), "lens_ring")
            add(label+"_window_glass", revolved([(r*.80, -.035), (r*.80, 0)], center), "optical_glass")
            surfaces.append((f"{model_id}_{label}_lens_surface", [body_front*.001, offset*.001, sensor_z*.001], 1))
    elif not accessory:
        lens_r = estimates.get("lens_radius_mm", min(w * .31, h * .22))
        lens_z = estimates.get("lens_center_height_mm", h*.60 if profile == "modular_dual" else h-lens_r-3 if dual else h*(.72 if profile == "wearable_capsule" else .56))
        lens_y = estimates.get("lens_center_y_mm", w*.24 if profile == "modular_dual" else w*.20 if profile in ("action", "modular_action") else 0)
        lens_r = min(lens_r, w/2-abs(lens_y)-.6, lens_z-.6, h-lens_z-.6)
        # At least a small lens cap is available after the body-depth split.
        protrusion = overall/2-d/2 if dual else overall-d
        for sign in (1, -1) if dual else (1,):
            face = sign*d/2 if dual else body_front
            center = (face, lens_y, lens_z)
            group = "front_lens" if sign == 1 else "rear_lens"
            rim_profile = [(lens_r, 0), (lens_r, protrusion*.23), (lens_r*.91, protrusion*.35)]
            add(group+"_bezel", revolved(rim_profile, center, sign), "lens_ring", group)
            # Convex cap with exact outward extent and no duplicated pole.
            cap = [(lens_r*.86, protrusion*.27)]
            for t in np.linspace(0, 1, 12):
                cap.append((lens_r*.86*(1-t), protrusion*(.35+.65*math.sin(t*math.pi/2))))
            add(group+"_glass", revolved(cap, center, sign, 64), "optical_glass", group)
            # 24 angular samples keep the collider light while retaining the
            # outward cap profile. Validate the conservative 0.2 mm allowance.
            collision_proxies[group] = np.vstack([revolved(rim_profile, center, sign, 24).vertices,
                                                 revolved(cap, center, sign, 24).vertices])
            surfaces.append((f"{model_id}_{group}_surface", [sign*overall*.0005, lens_y*.001, lens_z*.001], sign))
    # Face controls and screens stay inside the published envelope. Their
    # locations and dimensions are design estimates, never calibration data.
    if profile == "modular_dual":
        add("core_display_border", rounded_panel(w*.38, h*.56, .14, 1.5, (-d/2+.09, -w*.24, h*.56), (-1, 0, 0)), "seam")
        add("core_display", rounded_panel(w*.32, h*.48, .08, .9, (-d/2+.03, -w*.24, h*.56), (-1, 0, 0)), "screen")
    elif dual:
        if model_id == "one_x2":
            add("circular_display_border", revolved([(13.5, -.13), (13.5, -.04)], (body_front, 0, h*.38)), "seam")
            add("circular_display", revolved([(13, -.03), (13, 0)], (body_front, 0, h*.38)), "screen")
        else:
            factor = .36 if model_id == "one_x" else 1
            add("display_border", rounded_panel(w*.76*factor, h*.43*factor, .14, 1.5, (body_front-.09, 0, h*.32)), "seam")
            add("display_active_area", rounded_panel(w*.66*factor, h*.37*factor, .08, .9, (body_front-.03, 0, h*.32)), "screen")
        for side in (-1, 1):
            add(f"side_panel_{side}", rounded_panel(d*.66, h*.38, .10, 2,
                 (body_x, side*(w/2-.07), h*.36), (0, side, 0)), "rubber")
    elif profile not in ("wearable_capsule", "wearable_square", "case", "stereo_bar", "stereo_box"):
        add("rear_display_border", rounded_panel(w*.87, h*.70, .15, 2.0, (body_x-d/2+.10, 0, h*.54), (-1, 0, 0)), "seam")
        add("rear_display", rounded_panel(w*.77, h*.59, .08, 1.3, (body_x-d/2+.04, 0, h*.54), (-1, 0, 0)), "screen")
    if camera["family"].startswith("modular"):
        add("battery_base", rounded_panel(w*.995, h*.17, d*.99, min(radius, h*.075),
             (body_x, 0, h*.086)), "housing" if model_id == "one_rs_1inch360" else "modular_battery")
        add("module_join", rounded_panel(.45, h*.67, .12, .1, (body_front-.07, -w*.12, h*.62)), "seam")
    if profile == "wearable_capsule":
        add("record_button", rounded_panel(w*.36, h*.16, .08, w*.15, (body_front-.05, 0, h*.27)), "rubber")
    add("status_light", rounded_panel(min(4, w*.15), .65, .04, .20, (body_front-.03, 0, h*.10)), "status",
        "body_stem" if profile == "stereo_box" else "body")
    # Each family supplies its actual component layout rather than decorating a
    # common envelope. All authoring dimensions remain millimeters.
    ctx = SimpleNamespace(camera=camera,w=w,h=h,d=d,overall=overall,body_x=body_x,
        body_front=body_front,estimates=estimates,parts=parts,colors=colors,
        materials=material_settings,surfaces=surfaces,collision_proxies=collision_proxies)
    def detail_add(name, mesh, material="housing", collision=False):
        add(name,mesh,material,"body" if collision is False or collision is None else collision)
    ctx.add = detail_add
    decorated = False
    for module_name in ("xseries","wearable","action","stereo"):
        module_path=ROOT/"scripts/appearance"/f"{module_name}.py"
        if module_path.exists():
            import importlib
            if importlib.import_module(f"appearance.{module_name}").decorate(ctx):
                decorated=True
                break
    if decorated:
        collision_proxies.clear()
    from appearance.materials import apply_materials
    apply_materials(parts,colors,material_settings)
    meshes = model_dir / "assets/meshes"
    # These two generated directories must exactly match the current manifest;
    # stale proxy meshes otherwise remain visible in collision previews.
    for stale in list((meshes/"visual").glob("*.obj"))+list((meshes/"collision").glob("*.stl")):
        stale.unlink()
    scene = trimesh.Scene()
    for name, mesh, _, _ in parts:
        scene.add_geometry(mesh, node_name=name, geom_name=name)
    # Standard glTF Y-up, transformed back +90deg X by robotics consumers.
    scene.apply_transform(trimesh.transformations.rotation_matrix(-math.pi/2, [1, 0, 0]))
    def material_factors(tree):
        # glTF baseColorFactor is linear RGB. Keep exact floating-point factors
        # instead of trimesh's intermediate 8-bit material color quantization.
        for item in tree.get("materials", []):
            color = colors[item["name"]]
            item["pbrMetallicRoughness"]["baseColorFactor"] = [*srgb_to_linear(color).tolist(), color[3]]
            if item["name"] in ("optical_glass", "screen", "glass", "screen_glass") or "glass" in item["name"]:
                item.setdefault("extensions",{})["KHR_materials_clearcoat"]={"clearcoatFactor":.8,"clearcoatRoughnessFactor":.05}
                if "KHR_materials_clearcoat" not in tree.setdefault("extensionsUsed",[]):
                    tree["extensionsUsed"].append("KHR_materials_clearcoat")
            if "normalTexture" in item:
                item["normalTexture"]["scale"]=.65 if "rubber" in item["name"] or "grip" in item["name"] else .55
    scene.export(meshes / f"{model_id}_visual.glb", tree_postprocessor=material_factors)
    obj_file(meshes / f"{model_id}_visual.obj", parts, f"{model_id}_visual.mtl")
    used = sorted(set(part[2] for part in parts))
    with (meshes / f"{model_id}_visual.mtl").open("w") as out:
        for index, name in enumerate(used):
            if index:
                out.write("\n")
            out.write(f"newmtl {name}\nKd " + " ".join(str(v) for v in colors[name][:3]) + "\nd 1\nillum 2\n")
    manifest = []
    for material in used:
        group = [part for part in parts if part[2] == material]
        obj_file(meshes / f"visual/{material}.obj", group)
        manifest.append(dict(name=material, file=f"../assets/meshes/visual/{material}.obj",
                             rgba=[*srgb_to_linear(colors[material]).tolist(), 1.],
                             triangles=sum(len(part[1].faces) for part in group)))
    (model_dir / "assets/visual_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    collisions = {}
    for name in sorted(set(part[3] for part in parts)):
        points = collision_proxies.get(name)
        if points is None:
            points = np.vstack([part[1].vertices for part in parts if part[3] == name])
        # Collision shells use conservative support planes independently of
        # visual tessellation. This keeps the detailed glass cheap to simulate.
        from appearance.materials import collision_hull
        hull = collision_hull(points)
        hull.export(meshes / f"collision/{name}.stl")
        collisions[name] = hull
    config = dict(units="millimeters for geometry, kilograms for mass", width_mm=w, height_mm=h,
                  body_depth_mm=d, overall_depth_mm=overall, mass_kg=camera["mass_kg"], com_height_mm=h/2,
                  corner_radius_mm=radius, collision_tolerance_mm=.2,
                  notes=camera["accuracy_notes"],
                  sources=camera["sources"])
    (model_dir / f"config/{model_id}.json").write_text(json.dumps(config, indent=2) + "\n")
    write_urdf(model_dir, config, manifest, collisions, surfaces)
    metadata = dict(name=camera["name"], family=camera["family"], brand=camera.get("brand", "Insta360"),
                    accuracy_notes=camera["accuracy_notes"], visual=f"assets/meshes/{model_id}_visual.glb",
                    urdf=f"urdf/{model_id}.urdf", config=f"config/{model_id}.json",
                    root_link=f"{model_id}_link", mount_link=f"{model_id}_mount",
                    status="Reference-informed detailed exterior; unmeasured component geometry",
                    fidelity="reference_detailed_exterior" if decorated else "envelope_proxy", origin_description="Bottom center of total envelope; nominal attachment reference, not a measured mount interface",
                    appearance_revision=2, component_count=len(parts),
                    lens_surface_frames=[s[0] for s in surfaces], sources=camera["sources"],
                    appearance_sources=camera.get("appearance_sources",[]))
    (model_dir / "model.json").write_text(json.dumps(metadata, indent=2) + "\n")
    # Refresh the mounted simulator artifact whenever its source URDF/meshes
    # change, and merge its metadata only after the builder has saved its keys.
    from sensor_manifest import ensure_template
    ensure_template(camera, model_dir)
    export_mjcf.export_model(model_id)
    print(f"{model_id}: {sum(len(p[1].faces) for p in parts):,} visual triangles, "
          f"{sum(len(m.faces) for m in collisions.values()):,} collision triangles", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="all", help="Catalog ID, or all (default)")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    cameras = read_catalog()
    if args.list:
        for camera in cameras:
            print(f"{camera['id']:24} {camera['name']}")
        return
    if args.model != "all" and args.model not in {p["id"] for p in cameras}:
        parser.error(f"Unknown camera: {args.model}; use --list")
    for camera in cameras:
        if args.model in ("all", camera["id"]):
            build(camera)


if __name__ == "__main__":
    main()
