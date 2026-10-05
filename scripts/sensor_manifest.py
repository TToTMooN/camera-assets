"""Inventory missing imaging parameters; never invent calibration values.

--write-template creates only missing manifests. --check validates structure and
geometry references. --require-calibrated additionally requires optical data;
it does not certify a simulator backend or reproduce a device's image pipeline.
"""
from pathlib import Path
import argparse
import json
import math
import xml.etree.ElementTree as ET

from export_mjcf import geometric_frames, local_file, read_catalog

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "catalog/sensor_manifest.schema.json"
RGBD = {"realsense_d435i", "realsense_d455", "oak_d"}


def geometry_context(folder):
    metadata = json.loads(local_file(folder, "model.json").read_text())
    robot = ET.parse(local_file(folder, metadata["urdf"])).getroot()
    root = metadata["root_link"]
    frames = geometric_frames(robot, root)
    return metadata, root, frames


def make_template(camera, folder):
    metadata, root, frames = geometry_context(folder)
    ident = camera["id"]
    accessory = camera["family"] == "accessory"
    kind = ("accessory_none" if accessory else "dual_fisheye_360" if camera['family'] in ('360','modular_360')
            else "stereo_rgbd" if ident in RGBD else "stereo_rgb" if ident == "zed2i"
            else "monocular")
    references = [name for name in frames if "lens_surface" in name]
    projector = [name for name in references if "projector" in name]
    image_references = [name for name in references if name not in projector]
    expected_count = {'accessory_none':0, 'dual_fisheye_360':2, 'monocular':1,
                      'stereo_rgbd':3, 'stereo_rgb':2}[kind]
    if len(image_references) != expected_count:
        raise ValueError(f"{ident}: geometric lens count does not match sensor topology")
    if kind in ("stereo_rgbd", "stereo_rgb"):
        stereo = [name for name in image_references if "_left_" in name or "_right_" in name]
        stereo_role = "mono" if ident == "oak_d" else "infrared" if kind == "stereo_rgbd" else "color"
        roles = [("left", f"{stereo_role}_left", stereo),
                 ("right", f"{stereo_role}_right", stereo)]
        if kind == "stereo_rgbd":
            roles.append(("color", "color", [name for name in image_references if "_rgb_" in name]))
    else:
        roles = [(f"image_{i}", "fisheye" if kind == "dual_fisheye_360" else "color", [name])
                 for i, name in enumerate(image_references)]
    imagers = []
    for name, role, candidates in roles:
        imagers.append(dict(
            id=name, semantic_role=role, geometry_frame_candidates=candidates,
            geometry_mapping_status="unverified", optical_frame=None,
            T_body_optical=dict(translation_m=None, quaternion_xyzw=None),
            modes=[dict(mode_id="unconfigured", image_state=None, projection_model=None,
                        resolution_px=None, rate_hz=None, K_px=None, distortion_model=None,
                        distortion_coefficients=None, crop=None, stabilization=None,
                        shutter=None, clipping_range_m=None, encoding=None,
                        calibration_source=None)]))
    outputs = []
    if kind == "dual_fisheye_360":
        outputs.append(dict(id="panorama", kind="panorama", inputs=[i["id"] for i in imagers],
                            projection=None, resolution_px=None, rate_hz=None, encoding=None,
                            algorithm=None, synchronization=None))
    elif kind in ("stereo_rgbd", "stereo_rgb"):
        outputs.append(dict(id="depth", kind="depth", inputs=["left", "right"],
                            depth_semantics=None, units=None, invalid_value=None,
                            registration=None, valid_range_m=None, encoding=None,
                            algorithm=None, synchronization=None, rectification=None,
                            disparity_parameters=None, noise_model=None))
    return dict(
        schema_version=1, model_id=ident, sensor_class=kind,
        status="not_applicable" if accessory else "uncalibrated", root_frame=root,
        conventions=dict(length="meters", intrinsics="pixels", quaternion="xyzw",
                         optical_axes="+X right, +Y down, +Z forward",
                         transform="p_body = R_body_optical * p_optical + t_body_optical"),
        geometry_frames=[dict(name=name, translation_m=list(pos),
                              quaternion_xyzw=[*quat[1:], quat[0]],
                              source="reference_geometry", usage="placement_only")
                         for name, (pos, quat) in frames.items()],
        T_robot_body=dict(parent_frame=None, translation_m=None, quaternion_xyzw=None),
        imagers=imagers,
        emitters=[dict(id="infrared_projector", geometry_frame_candidates=projector,
                       pattern=None, wavelength_nm=None) ] if projector else [],
        derived_outputs=outputs,
        calibration=dict(device_serial=None, firmware=None, source=None, date=None, quality=None),
        backends={name: dict(version=None, configuration_status="missing", validation_status="not_run")
                  for name in ("isaac_sim", "mujoco", "gazebo")},
        notes=["Null means unknown, not zero or an ideal sensor.",
               "Surface frames are geometric references, not calibrated optical centers.",
               "Left/right geometry candidates need physical stream mapping verification.",
               "Calibrated optics do not certify stitching, depth algorithms or simulator integration."])


def check_manifest(document, camera, folder, require_calibrated=False):
    from jsonschema import Draft202012Validator
    schema = json.loads(SCHEMA.read_text())
    errors = sorted(Draft202012Validator(schema).iter_errors(document), key=lambda e: str(list(e.path)))
    if errors:
        error = errors[0]
        raise ValueError(f"{'.'.join(map(str,error.path)) or 'manifest'}: {error.message}")
    if document["model_id"] != camera["id"]:
        raise ValueError("Manifest model_id disagrees with catalog")
    expected = make_template(camera, folder)
    if document["sensor_class"] != expected["sensor_class"] or document["root_frame"] != expected["root_frame"]:
        raise ValueError("Sensor class or root frame disagrees with model")
    actual_frames = {frame["name"]: frame for frame in document["geometry_frames"]}
    wanted_frames = {frame["name"]: frame for frame in expected["geometry_frames"]}
    if len(actual_frames) != len(document["geometry_frames"]) or actual_frames != wanted_frames:
        raise ValueError("Geometry references are stale or disagree with URDF")
    imager_ids = [imager["id"] for imager in document["imagers"]]
    if len(set(imager_ids)) != len(imager_ids) or set(imager_ids) != {i["id"] for i in expected["imagers"]}:
        raise ValueError("Missing, duplicate or unexpected imaging unit")
    verified_references = set()
    optical_frames = set()
    for imager in document["imagers"]:
        expected_imager = next(i for i in expected['imagers'] if i['id'] == imager['id'])
        candidates = imager['geometry_frame_candidates']
        if imager['semantic_role'] != expected_imager['semantic_role'] or not set(candidates).issubset(expected_imager['geometry_frame_candidates']):
            raise ValueError(f"{imager['id']}: role or geometry candidates disagree with device topology")
        if imager['geometry_mapping_status'] == 'verified':
            if len(candidates) != 1:
                raise ValueError(f"{imager['id']}: verified mapping needs one selected geometry reference")
            if candidates[0] in verified_references:
                raise ValueError(f"{imager['id']}: duplicate verified geometry reference")
            verified_references.add(candidates[0])
        optical_frame = imager['optical_frame']
        if optical_frame is not None:
            if optical_frame in optical_frames:
                raise ValueError(f"{imager['id']}: duplicate optical frame")
            optical_frames.add(optical_frame)
        for candidate in imager["geometry_frame_candidates"]:
            if candidate not in wanted_frames or "lens_surface" not in candidate or "projector" in candidate:
                raise ValueError("Imager references an unknown frame or an emitter")
        pose = imager["T_body_optical"]
        q = pose["quaternion_xyzw"]
        if q is not None and not math.isclose(sum(v*v for v in q), 1., abs_tol=1e-6):
            raise ValueError(f"{imager['id']}: optical quaternion must be normalized")
        mode_ids = [mode["mode_id"] for mode in imager["modes"]]
        if len(mode_ids) != len(set(mode_ids)):
            raise ValueError(f"{imager['id']}: duplicate mode IDs")
        for mode in imager["modes"]:
            k = mode["K_px"]
            if k is not None and (k[0][0] <= 0 or k[1][1] <= 0 or abs(k[1][0]) > 1e-12 or k[2] != [0, 0, 1]):
                raise ValueError(f"{imager['id']}: invalid camera intrinsic matrix")
            clip = mode["clipping_range_m"]
            if clip is not None and not 0 < clip[0] < clip[1]:
                raise ValueError(f"{imager['id']}: invalid clipping range")
    emitter_ids = [e['id'] for e in document['emitters']]
    if len(set(emitter_ids)) != len(emitter_ids) or set(emitter_ids) != {e['id'] for e in expected['emitters']}:
        raise ValueError("Missing or unexpected emitter")
    for emitter in document['emitters']:
        if not emitter['geometry_frame_candidates'] or any(
                frame not in wanted_frames or 'projector' not in frame
                for frame in emitter['geometry_frame_candidates']):
            raise ValueError("Emitter must reference its projector surface")
    robot_quaternion = document['T_robot_body']['quaternion_xyzw']
    if robot_quaternion is not None and not math.isclose(sum(v*v for v in robot_quaternion), 1., abs_tol=1e-6):
        raise ValueError("Robot mounting quaternion must be normalized")
    for output in document["derived_outputs"]:
        if not set(output["inputs"]).issubset(imager_ids):
            raise ValueError("Derived output references an unknown imager")
    # jsonschema permits IEEE NaN/Infinity as Python numbers; reject explicitly.
    def finite(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Calibration contains a nonfinite number")
        if isinstance(value, dict):
            for child in value.values(): finite(child)
        elif isinstance(value, list):
            for child in value: finite(child)
    finite(document)
    missing = []
    if document["sensor_class"] == "accessory_none":
        if document["status"] != "not_applicable" or document["imagers"] or document["emitters"] or document["derived_outputs"]:
            raise ValueError("Accessory must not claim imaging units or outputs")
        return missing
    if document['status'] == 'not_applicable':
        raise ValueError("An imaging device cannot claim calibration is not applicable")
    for key in ("device_serial", "firmware", "source", "date"):
        if document["calibration"][key] is None: missing.append(f"calibration.{key}")
    for imager in document["imagers"]:
        prefix = imager["id"]
        if imager["geometry_mapping_status"] != "verified": missing.append(f"{prefix}.geometry_mapping")
        if not imager["optical_frame"]: missing.append(f"{prefix}.optical_frame")
        for key in ("translation_m", "quaternion_xyzw"):
            if imager["T_body_optical"][key] is None: missing.append(f"{prefix}.T_body_optical.{key}")
        if not imager["modes"]: missing.append(f"{prefix}.modes")
        for mode in imager["modes"]:
            for key in ("image_state", "projection_model", "resolution_px", "rate_hz", "K_px",
                        "distortion_model", "distortion_coefficients", "encoding", "calibration_source"):
                if mode[key] is None: missing.append(f"{prefix}.{mode['mode_id']}.{key}")
    if document["status"] == "calibrated" and missing:
        raise ValueError("Manifest claims calibrated but lacks: " + ", ".join(missing))
    if require_calibrated and (document["status"] != "calibrated" or missing):
        raise ValueError("Optical calibration missing: " + ", ".join(missing))
    return missing


def ensure_template(camera, folder):
    target = folder / "config/sensors.json"
    if not target.exists():
        template = make_template(camera, folder)
        # Exclusive creation protects existing device calibration from rebuilds.
        with target.open("x") as output:
            json.dump(template, output, indent=2, ensure_ascii=False, allow_nan=False)
            output.write("\n")
    metadata_path = folder / "model.json"
    metadata = json.loads(metadata_path.read_text())
    metadata["sensor_manifest"] = "config/sensors.json"
    temporary = metadata_path.with_name(".model.json.tmp")
    temporary.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(metadata_path)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="all")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--write-template", action="store_true", help="Create only missing files; never overwrite calibration")
    action.add_argument("--check", action="store_true", help="Validate schema and current geometry references")
    parser.add_argument("--require-calibrated", action="store_true", help="Fail for incomplete optical data; does not certify a backend")
    args = parser.parse_args()
    if args.require_calibrated and not args.check:
        parser.error("--require-calibrated requires --check")
    cameras = read_catalog()
    if args.model != "all" and args.model not in {camera["id"] for camera in cameras}:
        parser.error(f"Unknown model: {args.model}")
    failed = 0
    for camera in cameras:
        if args.model not in ("all", camera["id"]): continue
        folder = ROOT / "models" / camera["id"]
        try:
            if args.write_template:
                path = ensure_template(camera, folder)
                print(f"{camera['id']}: {path.relative_to(ROOT)}", flush=True)
            else:
                metadata = json.loads(local_file(folder, "model.json").read_text())
                path = local_file(folder, metadata["sensor_manifest"])
                doc = json.loads(path.read_text())
                missing = check_manifest(doc, camera, folder, args.require_calibrated)
                print(f"{camera['id']}: structure PASS; {doc['status']}; {len(missing)} optical fields pending", flush=True)
        except (ValueError, OSError, KeyError) as error:
            failed += 1
            print(f"{camera['id']}: FAIL: {error}", flush=True)
    raise SystemExit(bool(failed))


if __name__ == "__main__":
    main()
