"""Export mounted or free camera bodies from the project's mesh-based URDFs.

Mass properties, geometry and geometric frame sites come from the URDF. This
does not define imaging sensors or optical calibration. Compilation requires
MuJoCo with mesh shell-inertia support; export itself uses only stdlib.
"""
from pathlib import Path
import argparse
import json
import math
import os
import re
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def read_catalog():
    cameras = json.loads((ROOT / "catalog/cameras.json").read_text())["cameras"]
    ids = [camera["id"] for camera in cameras]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate catalog model IDs")
    for model_id in ids:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", model_id):
            raise ValueError(f"Unsafe model ID: {model_id}")
    return cameras


def local_file(model_dir, reference, anchor=None):
    """Resolve a relative reference without permitting model-directory escape."""
    if not reference or Path(reference).is_absolute() or "://" in reference:
        raise ValueError(f"Expected a local relative file: {reference!r}")
    candidate = ((anchor or model_dir) / reference).resolve()
    if not candidate.is_relative_to(model_dir.resolve()):
        raise ValueError(f"Reference escapes model directory: {reference}")
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate


def numbers(value, count):
    result = tuple(float(component) for component in value.split())
    if len(result) != count or not all(math.isfinite(n) for n in result):
        raise ValueError(f"Expected {count} finite values: {value!r}")
    return result


def formatted(values):
    return " ".join(f"{value:.12g}" for value in values)


def rpy_quaternion(rpy):
    r, p, y = (angle / 2 for angle in rpy)
    cr, sr, cp, sp, cy, sy = math.cos(r), math.sin(r), math.cos(p), math.sin(p), math.cos(y), math.sin(y)
    return (cr*cp*cy+sr*sp*sy, sr*cp*cy-cr*sp*sy,
            cr*sp*cy+sr*cp*sy, cr*cp*sy-sr*sp*cy)


def multiply(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (aw*bw-ax*bx-ay*by-az*bz, aw*bx+ax*bw+ay*bz-az*by,
            aw*by-ax*bz+ay*bw+az*bx, aw*bz+ax*by-ay*bx+az*bw)


def rotate(q, vector):
    return multiply(multiply(q, (0, *vector)), (q[0], -q[1], -q[2], -q[3]))[1:]


def origin(node):
    element = node.find("origin")
    if element is None:
        return (0., 0., 0.), (1., 0., 0., 0.)
    return (numbers(element.get("xyz", "0 0 0"), 3),
            rpy_quaternion(numbers(element.get("rpy", "0 0 0"), 3)))


def geometric_frames(robot, root_name):
    """Accumulate fixed link transforms into root-relative geometric sites."""
    links = {link.attrib["name"] for link in robot.findall("link")}
    transforms = {root_name: ((0., 0., 0.), (1., 0., 0., 0.))}
    pending = list(robot.findall("joint"))
    while pending:
        progressed = False
        for joint in pending[:]:
            if joint.get("type") != "fixed":
                raise ValueError("Camera export supports fixed frame joints only")
            parent = joint.find("parent").attrib["link"]
            child = joint.find("child").attrib["link"]
            if parent not in links or child not in links:
                raise ValueError("Joint references an unknown link")
            if parent not in transforms:
                continue
            if child in transforms:
                raise ValueError(f"Repeated or cyclic child link: {child}")
            parent_pos, parent_quat = transforms[parent]
            pos, quat = origin(joint)
            rotated_pos = rotate(parent_quat, pos)
            transforms[child] = (tuple(a+b for a, b in zip(parent_pos, rotated_pos)),
                                 multiply(parent_quat, quat))
            pending.remove(joint)
            progressed = True
        if not progressed:
            raise ValueError("Disconnected or cyclic fixed-frame graph")
    if transforms.keys() != links:
        raise ValueError("Disconnected URDF links")
    return {name: transform for name, transform in transforms.items() if name != root_name}


def export_model(model_id, free=False):
    if not re.fullmatch(r"[a-z][a-z0-9_]*", model_id):
        raise ValueError(f"Unsafe model ID: {model_id}")
    model_dir = ROOT / "models" / model_id
    if not model_dir.resolve().is_relative_to((ROOT / "models").resolve()):
        raise ValueError("Model directory escapes project models")
    metadata_path = local_file(model_dir, "model.json")
    metadata = json.loads(metadata_path.read_text())
    config = json.loads(local_file(model_dir, metadata["config"]).read_text())
    urdf_path = local_file(model_dir, metadata["urdf"])
    robot = ET.parse(urdf_path).getroot()
    links = {link.attrib["name"]: link for link in robot.findall("link")}
    child_names = {joint.find("child").attrib["link"] for joint in robot.findall("joint")}
    roots = set(links) - child_names
    if len(roots) != 1:
        raise ValueError("Expected one URDF root link")
    root_name = roots.pop()
    if metadata.get("root_link", root_name) != root_name:
        raise ValueError("Metadata root_link disagrees with URDF")
    for name, link in links.items():
        if name != root_name and any(link.find(tag) is not None for tag in ("inertial", "visual", "collision")):
            raise ValueError("Only the root camera link may have geometry or mass")
    root_link = links[root_name]
    inertial = root_link.find("inertial")
    if inertial is None:
        raise ValueError("Missing camera inertia")
    mass = float(inertial.find("mass").attrib["value"])
    if not math.isfinite(mass) or mass <= 0 or not math.isclose(mass, config["mass_kg"], rel_tol=1e-9):
        raise ValueError("Invalid URDF mass or disagreement with model config")
    inertia = inertial.find("inertia").attrib
    values = tuple(float(inertia[key]) for key in ("ixx", "iyy", "izz", "ixy", "ixz", "iyz"))
    if not all(math.isfinite(value) for value in values) or min(values[:3]) <= 0:
        raise ValueError("Invalid URDF inertia")
    com, inertia_quat = origin(inertial)
    output_dir = model_dir / "mjcf"
    if not output_dir.resolve().is_relative_to(model_dir.resolve()):
        raise ValueError("MJCF output directory escapes model directory")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"insta360_{model_id}.xml"
    if not output_path.resolve().is_relative_to(model_dir.resolve()):
        raise ValueError("MJCF output file escapes model directory")
    mjcf = ET.Element("mujoco", model=f"insta360_{model_id}")
    mjcf.append(ET.Comment("Independent approximate geometry; fixed sites are geometric references, not calibrated optical frames."))
    ET.SubElement(mjcf, "compiler", angle="radian", inertiafromgeom="false", strippath="false")
    ET.SubElement(mjcf, "option", timestep="0.002", gravity="0 0 -9.81")
    asset = ET.SubElement(mjcf, "asset")
    world = ET.SubElement(mjcf, "worldbody")
    body = ET.SubElement(world, "body", name=root_name)
    if free:
        ET.SubElement(body, "freejoint", name=f"{model_id}_free")
    attributes = dict(pos=formatted(com), mass=f"{mass:.12g}")
    if all(value == 0 for value in values[3:]):
        attributes.update(diaginertia=formatted(values[:3]), quat=formatted(inertia_quat))
    else:
        # fullinertia is expressed in the body frame; rotate the URDF tensor.
        matrix = [[values[0], values[3], values[4]], [values[3], values[1], values[5]], [values[4], values[5], values[2]]]
        columns = [rotate(inertia_quat, vector) for vector in ((1, 0, 0), (0, 1, 0), (0, 0, 1))]
        rotated = [[sum(columns[a][i]*matrix[a][b]*columns[b][j] for a in range(3) for b in range(3)) for j in range(3)] for i in range(3)]
        attributes["fullinertia"] = formatted((rotated[0][0], rotated[1][1], rotated[2][2], rotated[0][1], rotated[0][2], rotated[1][2]))
    ET.SubElement(body, "inertial", **attributes)
    mesh_names = {}
    for category in ("visual", "collision"):
        parts = root_link.findall(category)
        if not parts:
            raise ValueError(f"No {category} geometry in URDF")
        for index, part in enumerate(parts):
            mesh = part.find("geometry/mesh")
            if mesh is None:
                raise ValueError("Camera export expects mesh-based geometry")
            source = local_file(model_dir, mesh.attrib["filename"], urdf_path.parent)
            if source.suffix.lower() not in (".obj", ".stl"):
                raise ValueError(f"Unsupported MuJoCo mesh format: {source.suffix}")
            scale = numbers(mesh.get("scale", "1 1 1"), 3)
            if min(scale) <= 0:
                raise ValueError("Mesh scale must be positive")
            mesh_key = (source, scale, category)
            if mesh_key not in mesh_names:
                name = f"{model_id}_{category}_mesh_{index}"
                mesh_names[mesh_key] = name
                ET.SubElement(asset, "mesh", name=name,
                              file=Path(os.path.relpath(source, output_dir)).as_posix(),
                              scale=formatted(scale), inertia="shell" if category == "visual" else "convex")
            pos, quat = origin(part)
            geom = dict(name=f"{model_id}_{category}_{index}", type="mesh", mesh=mesh_names[mesh_key],
                        pos=formatted(pos), quat=formatted(quat), density="0")
            if category == "visual":
                color = part.find("material/color")
                rgba = numbers(color.get("rgba", "0.5 0.5 0.5 1"), 4) if color is not None else (.5, .5, .5, 1.)
                if not all(0 <= value <= 1 for value in rgba):
                    raise ValueError("Visual RGBA must be in [0,1]")
                geom.update(group="2", contype="0", conaffinity="0", rgba=formatted(rgba))
            else:
                geom.update(group="3", contype="1", conaffinity="1", rgba="0 0 0 0")
            ET.SubElement(body, "geom", **geom)
    for name, (pos, quat) in geometric_frames(robot, root_name).items():
        ET.SubElement(body, "site", name=name, pos=formatted(pos), quat=formatted(quat),
                      type="sphere", size="0.001", group="4", rgba="0 0 0 0")
    ET.indent(mjcf, space="  ")
    # Publish a complete artifact atomically. Opening a cloud placeholder for
    # overwrite can first hydrate an obsolete file, and errors must not leave a
    # truncated simulator description at the public path.
    with tempfile.NamedTemporaryFile(dir=output_dir, suffix=".tmp", delete=False) as temporary:
        temporary_path = Path(temporary.name)
        ET.ElementTree(mjcf).write(temporary, encoding="utf-8", xml_declaration=True)
    temporary_path.replace(output_path)
    # Re-read before merging so builder-owned metadata keys survive export.
    metadata = json.loads(metadata_path.read_text())
    metadata["mjcf"] = output_path.relative_to(model_dir).as_posix()
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=model_dir, suffix=".tmp", delete=False) as temporary:
        temporary_path = Path(temporary.name)
        temporary.write(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    temporary_path.replace(metadata_path)
    return output_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="x5", help="Catalog ID or all")
    parser.add_argument("--list", action="store_true", help="List catalog models")
    parser.add_argument("--free", action="store_true", help="Export a free root body; default is a fixed mounted body")
    args = parser.parse_args()
    cameras = read_catalog()
    if args.list:
        for camera in cameras:
            print(f"{camera['id']:24} {camera['name']}")
        return
    ids = [camera["id"] for camera in cameras]
    if args.model != "all" and args.model not in ids:
        parser.error(f"Unknown model {args.model!r}; use --list")
    for model_id in ids if args.model == "all" else [args.model]:
        print(export_model(model_id, free=args.free).relative_to(ROOT))


if __name__ == "__main__":
    main()
