# Use camera assets in another project

The `camera-assets` Python package provides versioned downloads and offline paths.
It has no runtime dependencies and supports Python 3.10 or later. Model geometry
is distributed separately, one archive per camera or accessory.

## Install

Install the lightweight wheel from the pinned GitHub release:

```bash
python -m pip install https://github.com/TToTMooN/camera-assets/releases/download/v0.1.0/camera_assets-0.1.0-py3-none-any.whl
```

Use that same URL in a project's requirements file to pin the resolver version.
The asset version is selected separately in each download or lookup. This package
is distributed through GitHub Releases; the command above does not require a
PyPI publication.

## Download once, resolve offline

```bash
camera-assets list
camera-assets fetch go3s --version v0.1.0
camera-assets path go3s --version v0.1.0 --format urdf
```

Or use Python:

```python
from camera_assets import fetch, get_model

# Explicit network operation, usually performed during environment setup.
fetch("go3s", version="v0.1.0")

# Offline lookup for application startup and simulation jobs.
camera = get_model("go3s", version="v0.1.0")
print(camera.urdf)
print(camera.mjcf)
print(camera.visual)
print(camera.sensor_manifest)
```

`get_model` never downloads. If the selected version is missing, it reports how to
fetch it. Versions must be explicit; `latest` is not accepted. `list_models()` and
`camera-assets list` use the catalog bundled with the installed resolver.

The model object provides its `id`, asset `version`, `directory`, and `metadata`
dictionary in addition to the file paths above. Paths are `pathlib.Path` objects.
URDF/MJCF retain their relative mesh references, so keep the entire downloaded
model directory intact. Visual GLBs contain their material and texture data.

For MuJoCo, the application can load the resolved MJCF directly:

```python
import mujoco
from camera_assets import get_model

camera = get_model("go3s", version="v0.1.0")
model = mujoco.MjModel.from_xml_path(str(camera.mjcf))
```

For Isaac Sim or another URDF importer, pass `str(camera.urdf)` to the import API
for the installed simulator version. Imaging sensors still require their own
optical poses, calibration, and backend configuration. See the
[simulation guide](https://github.com/TToTMooN/camera-assets/blob/main/docs/SIMULATION.md).

## Cache and local models

The default cache is shared across virtual environments on the same machine.
Set `CAMERA_ASSETS_CACHE` to a project-controlled cache directory, or pass
`cache_dir=` / `--cache-dir` explicitly. Pre-fetch models into that directory
when preparing an offline machine or container image.

```python
fetch("x6", version="v0.1.0", cache_dir="/data/camera-assets")
camera = get_model("x6", version="v0.1.0", cache_dir="/data/camera-assets")
```

Use an existing checkout or extracted library root without downloading:

```python
camera = get_model("go3s", root="/path/to/camera-assets")
```

```bash
camera-assets path go3s --root /path/to/camera-assets --format glb
```

The local root contains `models/<id>/`. An unversioned checkout returns
`camera.version is None`; it does not claim to be a published asset release.
`python -m camera_assets` provides the same CLI when the console executable is
not on `PATH`.

## Integrity and calibration

Release downloads verify archive size, SHA256, and the hashes and sizes of the
extracted files. Archives preserve runtime metadata, sensor templates, geometry,
URDF/MJCF, validation results, and the MIT license. Previews, Blender authoring
files, and standalone authoring textures are omitted from runtime archives.

Successful downloads publish atomically into a version-specific cache. A valid
cached model is reused; an existing corrupt or modified cache is reported and
is never overwritten automatically. Keep downloaded release files unchanged.
Checksums establish consistency with the selected release manifest; they are
not a separate cryptographic signature by the manufacturers.

Store device-specific calibration in the consuming project, keyed by the model
ID and asset version or source hash. Read `camera.sensor_manifest` as a template
and copy it before editing. The resolver does not merge or overwrite calibration.
Nominal dimensions, unmeasured geometry, and optical calibration retain the
[library's documented limits](https://github.com/TToTMooN/camera-assets/blob/main/docs/SOURCES.md).

## Publish a new release

From a clean checkout, update the package version in `pyproject.toml` and
`src/camera_assets/__init__.py`. After changing the model catalog, run
`python scripts/sync_package_catalog.py` and commit the updated snapshot.

The release workflow runs all asset and package tests, builds the lightweight
wheel/source distribution, creates deterministic per-model archives, and consumes
every archive through the SDK before publishing `manifest.json` and `SHA256SUMS`.
Push a matching `vX.Y.Z` tag to publish:

```bash
git tag v0.1.0
git push origin v0.1.0
```

Use a new version for any changed release contents. Existing release assets and
tags should stay unchanged so downstream projects can reproduce their inputs.
To build the same artifacts locally without publishing:

```bash
python -m pip install -r requirements-build.txt
python -m build
python scripts/verify_package.py dist --version v0.1.0
python scripts/package_release.py --version v0.1.0 --output /tmp/camera-assets-v0.1.0 --sdk-dist dist
python scripts/verify_release.py /tmp/camera-assets-v0.1.0 --version v0.1.0
```

The package builder requires a clean source checkout. `manifest.json` records the
source commit and each model's archive/file hashes. SDK versions and asset
versions are pinned independently by consuming projects.
