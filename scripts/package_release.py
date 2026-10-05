"""Create deterministic per-model runtime archives and a checksummed release.

The CLI packages a clean Git checkout. Explicit source_commit values are useful
for isolated build fixtures that do not have Git history. No simulator or SDK
imports are required.
"""
from pathlib import Path, PurePosixPath
import argparse
import ctypes
import email.parser
import errno
import hashlib
import json
import os
import re
import shlex
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "TToTMooN/camera-assets"
FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
TEMP_SUFFIXES = {".tmp", ".temp", ".bak", ".swp", ".swo", ".pyc", ".pyo", ".blend", ".blend1"}


def normalize_version(value):
    if not isinstance(value, str) or not re.fullmatch(r"v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value):
        raise ValueError("Version must be a stable vMAJOR.MINOR.PATCH without leading zeros")
    return "v" + value.removeprefix("v")


def validate_model_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", value):
        raise ValueError(f"Unsafe model ID: {value!r}")
    return value


def regular_file(path):
    if path.is_symlink():
        raise ValueError(f"Symlinks are not release inputs: {path}")
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def runtime_path(relative):
    """Select delivered runtime files, omitting authoring and temporary files."""
    parts = PurePosixPath(relative).parts
    if not parts or any(part.startswith(".") or part == "__pycache__" for part in parts):
        return False
    if parts[-1].endswith("~") or Path(parts[-1]).suffix.lower() in TEMP_SUFFIXES:
        return False
    if relative in ("model.json", "assets/visual_manifest.json", "docs/validation.json"):
        return True
    return parts[0] in ("config", "urdf", "mjcf") or parts[:2] == ("assets", "meshes")


def reference_file(model_dir, anchor, reference, included):
    """Allow URDF parent references only when they stay inside the model package."""
    if not isinstance(reference, str) or not reference or ":" in reference or "\\" in reference:
        raise ValueError(f"Unsafe asset reference: {reference!r}")
    if PurePosixPath(reference).is_absolute():
        raise ValueError(f"Absolute asset reference: {reference}")
    candidate = anchor / reference
    if candidate.is_symlink():
        raise ValueError(f"Symlink asset reference: {reference}")
    resolved = candidate.resolve()
    if not resolved.is_relative_to(model_dir):
        raise ValueError(f"Asset reference escapes model package: {reference}")
    regular_file(resolved)
    relative = resolved.relative_to(model_dir).as_posix()
    if relative not in included:
        raise ValueError(f"Referenced dependency excluded from runtime package: {relative}")
    return resolved


def validate_dependencies(model_dir, files):
    model_dir = Path(model_dir).resolve()
    metadata = json.loads(files["model.json"].read_text(encoding="utf-8"))
    if not isinstance(metadata, dict):
        raise ValueError("model.json must be an object")
    for key in ("visual", "config", "urdf", "mjcf", "sensor_manifest"):
        reference = metadata.get(key)
        if not isinstance(reference, str) or ".." in PurePosixPath(reference).parts:
            raise ValueError(f"Missing or unsafe model metadata target: {key}")
        reference_file(model_dir, model_dir, reference, files)
    for relative, path in files.items():
        suffix = path.suffix.lower()
        if relative.startswith("urdf/") and suffix == ".urdf":
            robot = ET.parse(path)
            for element in robot.iter():
                if element.tag in ("mesh", "texture") and "filename" in element.attrib:
                    reference_file(model_dir, path.parent, element.attrib["filename"], files)
        elif relative.startswith("mjcf/") and suffix == ".xml":
            model = ET.parse(path)
            compiler = model.find("compiler")
            if compiler is not None and compiler.get("strippath", "false") == "true":
                raise ValueError("MJCF strippath=true cannot preserve portable references")
            for element in model.iter():
                if "file" not in element.attrib:
                    continue
                directory = ""
                if compiler is not None and element.tag in ("mesh", "texture", "hfield"):
                    directory = compiler.get("meshdir" if element.tag == "mesh" else "texturedir", compiler.get("assetdir", ""))
                    if ":" in directory or "\\" in directory or PurePosixPath(directory).is_absolute():
                        raise ValueError(f"Unsafe MJCF asset directory: {directory}")
                reference_file(model_dir, path.parent / directory, element.attrib["file"], files)
        elif suffix == ".obj":
            with path.open(encoding="utf-8") as source:
                for line in source:
                    if line.lstrip().startswith("mtllib "):
                        for reference in shlex.split(line.strip()[7:]):
                            reference_file(model_dir, path.parent, reference, files)
        elif suffix == ".mtl":
            with path.open(encoding="utf-8") as source:
                for line in source:
                    words = shlex.split(line, comments=True)
                    if words and (words[0].startswith("map_") or words[0] in ("bump", "disp", "decal", "norm")):
                        if len(words) < 2:
                            raise ValueError(f"Missing material texture reference: {path}")
                        reference_file(model_dir, path.parent, words[-1], files)
        elif suffix == ".glb":
            with path.open("rb") as source:
                header = source.read(20)
                if len(header) != 20:
                    raise ValueError(f"Truncated GLB: {path}")
                magic, version, _, json_length, chunk_type = struct.unpack("<4sIIII", header)
                if magic != b"glTF" or version != 2 or chunk_type != 0x4e4f534a:
                    raise ValueError(f"Invalid GLB header: {path}")
                document = json.loads(source.read(json_length))
            for element in document.get("buffers", []) + document.get("images", []):
                if "uri" in element and not element["uri"].startswith("data:"):
                    reference_file(model_dir, path.parent, element["uri"], files)
    manifest = json.loads(files["assets/visual_manifest.json"].read_text(encoding="utf-8"))
    for part in manifest:
        reference_file(model_dir, model_dir / "urdf", part["file"], files)


def model_files(root, model_id):
    model_dir = root / "models" / model_id
    if model_dir.is_symlink() or not model_dir.is_dir():
        raise ValueError(f"Missing or symlink model directory: {model_id}")
    model_dir = model_dir.resolve()
    files = {}
    for path in model_dir.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Symlinks are not release inputs: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(model_dir).as_posix()
        if ":" in relative or "\\" in relative:
            raise ValueError(f"Unsafe runtime filename: {relative}")
        if runtime_path(relative):
            files[relative] = path
    for required in ("model.json", "assets/visual_manifest.json", "docs/validation.json"):
        if required not in files:
            raise FileNotFoundError(model_dir / required)
    validate_dependencies(model_dir, files)
    return dict(sorted(files.items()))


def clean_source_commit(root):
    def git(*arguments):
        return subprocess.check_output(["git", "-C", str(root), *arguments], text=True, stderr=subprocess.STDOUT).strip()
    try:
        if Path(git("rev-parse", "--show-toplevel")).resolve() != root:
            raise ValueError("Source must be the Git repository root")
        commit = git("rev-parse", "HEAD")
        dirty = git("status", "--porcelain=v1", "--untracked-files=all")
    except subprocess.CalledProcessError as error:
        raise ValueError("Release source must be a Git checkout with a commit") from error
    if dirty:
        raise ValueError("Release source has tracked changes or untracked files; commit or clean them first")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Expected a 40-character Git commit")
    return commit


def require_tracked_inputs(root, paths):
    """Ignored files must not silently enter a release attributed to Git HEAD."""
    try:
        names = subprocess.check_output(["git", "-C", str(root), "ls-files", "--cached", "-z"], stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as error:
        raise ValueError("Cannot inspect Git-tracked release inputs") from error
    tracked = {os.fsdecode(name) for name in names.split(b"\0") if name}
    required = {path.relative_to(root).as_posix() for path in paths}
    missing = sorted(required - tracked)
    if missing:
        raise ValueError("Release runtime inputs must be Git-tracked: " + ", ".join(missing))


def publish_no_replace(staging, output):
    """Atomically publish a directory without replacing any competing target."""
    if sys.platform == "win32":
        # Windows rename fails if the destination already exists.
        os.rename(staging, output)
        return
    if sys.platform not in ("linux", "darwin"):
        raise OSError(errno.ENOTSUP, "Atomic no-replace publication is unsupported on this platform", str(output))
    libc = ctypes.CDLL(None, use_errno=True)
    name = "renameat2" if sys.platform == "linux" else "renamex_np"
    native = getattr(libc, name, None)
    if native is None:
        raise OSError(errno.ENOTSUP, f"Atomic no-replace publication requires {name}", str(output))
    native.restype = ctypes.c_int
    source_bytes, output_bytes = os.fsencode(staging), os.fsencode(output)
    if sys.platform == "linux":
        native.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        # Linux UAPI: AT_FDCWD=-100, RENAME_NOREPLACE=1.
        result = native(-100, source_bytes, -100, output_bytes, 1)
    else:
        native.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        # Darwin sys/stdio.h: RENAME_EXCL=0x00000004.
        result = native(source_bytes, output_bytes, 4)
    if result != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(output))


def sdk_artifacts(directory, version):
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("SDK distribution directory must be a regular directory")
    numeric_version = version[1:]
    wheels = sorted(directory.glob("*.whl"))
    sources = sorted(directory.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sources) != 1:
        raise ValueError("SDK distribution must contain exactly one wheel and one source archive")
    wheel, source = wheels[0], sources[0]
    regular_file(wheel)
    regular_file(source)
    if not re.fullmatch(rf"camera_assets-{re.escape(numeric_version)}-[A-Za-z0-9_.]+-[A-Za-z0-9_.]+-[A-Za-z0-9_.]+\.whl", wheel.name):
        raise ValueError(f"SDK wheel filename does not match {version}: {wheel.name}")
    if source.name not in (f"camera_assets-{numeric_version}.tar.gz", f"camera-assets-{numeric_version}.tar.gz"):
        raise ValueError(f"SDK source filename does not match {version}: {source.name}")
    def check_metadata(data):
        metadata = email.parser.BytesParser().parsebytes(data)
        name = re.sub(r"[-_.]+", "-", metadata.get("Name", "")).lower()
        if name != "camera-assets" or metadata.get("Version") != numeric_version:
            raise ValueError("SDK package metadata name/version disagrees with requested release")
    with zipfile.ZipFile(wheel) as archive:
        names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(names) != 1:
            raise ValueError("SDK wheel must contain one distribution METADATA file")
        check_metadata(archive.read(names[0]))
    with tarfile.open(source, "r:gz") as archive:
        names = [member for member in archive.getmembers() if member.name.count("/") == 1 and member.name.endswith("/PKG-INFO")]
        if len(names) != 1 or not names[0].isfile():
            raise ValueError("SDK source must contain one root PKG-INFO file")
        check_metadata(archive.extractfile(names[0]).read())
    return [wheel, source]


def digest_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_release(root, output, version, model_ids=None, source_commit=None, sdk_dist=None):
    """Publish a fresh directory, with no partially written release on failure."""
    root = Path(root).resolve()
    output = Path(output)
    if output.is_symlink():
        raise ValueError("Release output cannot be a symlink")
    output = output.resolve()
    version = normalize_version(version)
    if output.is_relative_to((root / "models").resolve()):
        raise ValueError("Release output cannot be inside models")
    if output.exists():
        raise FileExistsError(f"Release output already exists: {output}")
    if (root / "models").is_symlink():
        raise ValueError("models cannot be a symlink")
    catalog_path = regular_file(root / "catalog/cameras.json")
    if (root / "catalog").is_symlink():
        raise ValueError("catalog cannot be a symlink")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))["cameras"]
    available = [validate_model_id(camera["id"]) for camera in catalog]
    if not available or len(available) != len(set(available)):
        raise ValueError("Catalog must contain unique model IDs")
    selected = available if model_ids is None or model_ids == "all" else ([model_ids] if isinstance(model_ids, str) else list(model_ids))
    for model_id in selected:
        validate_model_id(model_id)
        if model_id not in available:
            raise ValueError(f"Unknown model ID: {model_id}")
    if not selected or len(selected) != len(set(selected)):
        raise ValueError("Select at least one model, without duplicates")
    tracked_source = source_commit is None
    if tracked_source:
        source_commit = clean_source_commit(root)
    elif not isinstance(source_commit, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", source_commit):
        raise ValueError("source_commit must be a 40-character hexadecimal commit")
    source_commit = source_commit.lower()
    license_path = regular_file(root / "LICENSE")
    license_data = license_path.read_bytes()
    if not license_data:
        raise ValueError("Root LICENSE is empty")
    payloads = {model_id: model_files(root, model_id) for model_id in sorted(selected)}
    if tracked_source:
        require_tracked_inputs(root, [catalog_path, license_path, *(path for files in payloads.values() for path in files.values())])
    sdk_files = sdk_artifacts(sdk_dist, version) if sdk_dist is not None else []
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    manifest = dict(schema_version=1, version=version, repository=REPOSITORY, source_commit=source_commit, models={})
    try:
        for model_id, files in payloads.items():
            archive_name = f"{model_id}-{version}.zip"
            archive_path = staging / archive_name
            records = {}
            with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
                for relative in sorted([*files, "LICENSE"]):
                    data = license_data if relative == "LICENSE" else files[relative].read_bytes()
                    records[relative] = dict(sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data))
                    info = zipfile.ZipInfo(f"models/{model_id}/{relative}", date_time=FIXED_TIMESTAMP)
                    info.create_system = 3
                    info.external_attr = 0o100644 << 16
                    info.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
            manifest["models"][model_id] = dict(
                archive=archive_name, sha256=digest_file(archive_path), size_bytes=archive_path.stat().st_size,
                unpacked_size_bytes=sum(record["size_bytes"] for record in records.values()), files=records)
        (staging / "manifest.json").write_bytes((json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode())
        for source in sdk_files:
            shutil.copyfile(source, staging / source.name)
        checksums = "".join(f"{digest_file(path)}  {path.name}\n" for path in sorted(staging.iterdir(), key=lambda path: path.name))
        (staging / "SHA256SUMS").write_bytes(checksums.encode("ascii"))
        if output.exists():
            raise FileExistsError(f"Release output appeared during build: {output}")
        publish_no_replace(staging, output)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="Stable release tag, such as v0.1.0")
    parser.add_argument("--output", type=Path, required=True, help="Fresh output directory")
    parser.add_argument("--model", default="all", help="Catalog model ID or all")
    parser.add_argument("--sdk-dist", type=Path, help="Include matching SDK wheel and source archive")
    args = parser.parse_args()
    try:
        manifest = build_release(ROOT, args.output, args.version, model_ids=args.model, sdk_dist=args.sdk_dist)
    except (ValueError, OSError, KeyError, json.JSONDecodeError, ET.ParseError, zipfile.BadZipFile, tarfile.TarError) as error:
        parser.exit(1, f"Release packaging failed: {error}\n")
    print(f"Packaged {len(manifest['models'])} models for {manifest['version']} in {args.output}")


if __name__ == "__main__":
    main()
