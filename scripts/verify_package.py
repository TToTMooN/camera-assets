"""Check that built SDK artifacts are lightweight, consistent, and asset-free."""
import argparse
import ast
from email.parser import BytesParser
import json
from pathlib import Path
import re
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify(directory, version=None):
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"\s*$', project, re.MULTILINE)
    require(match is not None, "Project version missing")
    expected = match.group(1)
    if version is not None:
        require(re.fullmatch(r"v?\d+\.\d+\.\d+", version), "Use a fixed vX.Y.Z release version")
        require(version.removeprefix("v") == expected, "Tag and Python package versions differ")
    wheels = list(directory.glob("*.whl"))
    sources = list(directory.glob("*.tar.gz"))
    require(len(wheels) == len(sources) == 1, "Expected exactly one wheel and one source distribution")
    wheel, source = wheels[0], sources[0]
    require(wheel.name == f"camera_assets-{expected}-py3-none-any.whl", "Unexpected wheel name or platform")
    require(source.name == f"camera_assets-{expected}.tar.gz", "Unexpected source distribution name")
    require(wheel.stat().st_size < 1024 * 1024, "SDK wheel must remain smaller than 1 MiB")
    require(source.stat().st_size < 1024 * 1024, "SDK source distribution must remain smaller than 1 MiB")
    canonical = json.loads((ROOT / "catalog/cameras.json").read_text(encoding="utf-8"))
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), "Duplicate wheel members")
        prefix = f"camera_assets-{expected}.dist-info/"
        require(all(name.startswith(("camera_assets/", prefix)) for name in names), "Wheel contains unrelated files")
        require(all(not name.endswith((".glb", ".obj", ".stl", ".blend", ".png")) for name in names), "Wheel embeds model assets")
        metadata = BytesParser().parsebytes(archive.read(prefix + "METADATA"))
        require(metadata["Name"] == "camera-assets" and metadata["Version"] == expected, "Wheel metadata differs from project")
        require(not metadata.get_all("Requires-Dist"), "SDK must have no runtime dependencies")
        declarations = ast.parse(archive.read("camera_assets/__init__.py").decode())
        versions = [ast.literal_eval(node.value) for node in declarations.body
                    if isinstance(node, ast.Assign) and any(
                        isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets)]
        require(versions == [expected], "SDK runtime and package metadata versions differ")
        require(json.loads(archive.read("camera_assets/catalog.json")) == canonical, "Wheel catalog is stale")
        entries = archive.read(prefix + "entry_points.txt").decode()
        require("camera-assets = camera_assets.cli:main" in entries, "Missing SDK command-line entry point")
    with tarfile.open(source, "r:gz") as archive:
        members = archive.getmembers()
        require(sum(member.size for member in members) < 2 * 1024 * 1024, "SDK source expands beyond 2 MiB")
        require(all(not member.issym() and not member.islnk() for member in members), "Source distribution contains links")
        prefix = f"camera_assets-{expected}/"
        require(all(member.name.startswith(prefix) or member.name == prefix.rstrip("/") for member in members), "Unexpected source archive root")
        require(all(not member.name.startswith(tuple(prefix + part for part in ("models/", "references/", "catalog/"))) for member in members), "Source distribution embeds library assets")
        metadata_file = archive.extractfile(prefix + "PKG-INFO")
        require(metadata_file is not None, "Source metadata missing")
        metadata = BytesParser().parsebytes(metadata_file.read())
        require(metadata["Version"] == expected and not metadata.get_all("Requires-Dist"), "Source metadata differs from wheel")
    print(f"SDK {expected}: PASS; {wheel.stat().st_size:,}-byte wheel, no runtime dependencies or model meshes")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--version", help="Expected asset tag; must match the SDK version")
    args = parser.parse_args()
    try:
        verify(args.directory, args.version)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, tarfile.TarError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
