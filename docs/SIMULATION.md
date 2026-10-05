# Simulation integration

These assets support camera placement, collision, occlusion, and payload studies.
URDF and MJCF provide geometry, nominal mass, estimated inertia, and fixed reference
frames. Imaging requires separate calibration, sensor configuration, and validation.

## Use the geometry

Run commands from the repository root after installing the dependencies in the
[README](../README.md):

```bash
python scripts/viewer.py --list
python scripts/viewer.py --model go3s
python scripts/validate.py --model all
```

Copy the entire `models/<id>/` directory into your project. Use the URDF and MJCF
paths in `model.json`, preserving relative mesh paths and directory structure.
Confirm the imported scale, orientation, collision geometry, and reference frames.

Camera bodies, Action Pods, and charging cases are separate configurations;
accessory mass excludes the camera. Pods and cases represent their documented
closed states, without a docked camera or articulated hinges. ONE R/RS models
represent complete, rigid lens/core/battery configurations. Add your actual mount,
cables, connectors, and assembly clearances to the scene.

## Sensor manifests

Each model has `config/sensors.json`, defined by
[sensor_manifest.schema.json](../catalog/sensor_manifest.schema.json).

| Field | Purpose |
| --- | --- |
| `sensor_class`, `status` | Physical sensor topology and optical calibration status |
| `geometry_frames` | Existing placement references from the URDF |
| `T_robot_body` | Camera body pose relative to the robot or mount |
| `imagers` | Physical imaging units, optical poses, and per-mode parameters |
| `emitters` | Projectors and other emitting units |
| `derived_outputs` | Computed depth or stitched panorama outputs |
| `calibration` | Device, firmware, source, date, and quality records |
| `backends` | Simulator versions, configuration, and validation status |

Create only missing templates, preserving existing calibration files:

```bash
python scripts/sensor_manifest.py --model all --write-template
```

Check schema, geometry references, and sensor topology:

```bash
python scripts/sensor_manifest.py --model all --check
```

Require the optical calibration fields for every imaging device:

```bash
python scripts/sensor_manifest.py --model all --check --require-calibrated
```

Replace `all` with a model ID to work on one configuration. Supplied imaging
manifests are `uncalibrated`, so the last command intentionally fails until their
required fields are supplied and status is `calibrated`. Accessories are
`not_applicable`. Catalog `status: ready` describes generated geometry.

A completeness check does not establish calibration accuracy, completed depth or
panorama processing, or a working simulator backend. Record backend validation
separately. Keep unknown values `null`; they do not mean zero distortion, an ideal
sensor, or a default mode. Obtain calibration for the specific device and mode
rather than using sample intrinsics, advertised FOV, or mesh dimensions.

## Coordinates and units

URDF/MJCF lengths are meters and masses are kilograms. Catalog mechanical
dimensions are millimeters. The body origin is a bottom placement reference;
confirm the actual mounting interface before treating it as a measured datum.
GLB is Y-up; check the simulator's imported transform independently of the viewer.

| Frame | Axes |
| --- | --- |
| Library body | X depth, Y width, Z height |
| ROS optical | +X image right, +Y image down, +Z forward |
| USD / MuJoCo camera | +X image right, +Y image up, −Z forward |

`*_lens_surface` frames have local +Z pointing outward from the surface. Their
origins are geometric references, not calibrated optical centers. Verify the SDK
left/right mapping before selecting a reference for each physical imager.
RealSense `*_projector_lens_surface` belongs to an emitter, not an imaging unit.

The manifest uses `quaternion_xyzw` and this transform direction:

```text
p_body = R_body_optical * p_optical + t_body_optical
```

When placing a USD/MuJoCo camera from a ROS optical pose, use
`R_body_camera = R_body_optical * diag(1, -1, -1)` with the same translation.
Reorder quaternion components when an API expects `wxyz`. This axis conversion
cannot supply an unknown optical center. Keep the external `T_robot_body`
separate from each internal `T_body_optical`. Importers may merge fixed joints;
check the resulting node paths and transforms.
[ROS CameraInfo](https://github.com/ros2/common_interfaces/blob/rolling/sensor_msgs/msg/CameraInfo.msg),
[OpenUSD camera coordinates](https://openusd.org/dev/api/class_usd_geom_camera.html),
[MuJoCo camera coordinates](https://mujoco.readthedocs.io/en/stable/XMLreference.html#body-camera).

USD focal length and filmback/aperture use **tenths of a stage unit**; clipping
distances use scene units. With a centimeter stage, focal/aperture values are
numerically in millimeters. A meter stage requires conversion. Set and check
`metersPerUnit`, up axis, and all imported units.
[OpenUSD camera units](https://openusd.org/dev/api/class_usd_geom_camera.html#details).

## Calibrate the selected outputs

For each physical imager and mode, record resolution, rate, `K_px` (`fx`, `fy`,
`cx`, `cy`, and any skew), projection model, distortion model and coefficient
order, optical pose, encoding, and calibration source. Distinguish raw,
rectified, and processed images. Resizing, cropping, rotation, zoom, and electronic
stabilization can change the effective intrinsics; maximum resolution and maximum
frame rate may belong to different modes.

Preserve device serial, hardware/lens revision, firmware/SDK version, mode,
calibration tool/date, source files or hashes, and quality measures such as
reprojection error. Link supporting records through the calibration source.
Keep measured calibration distinct from deliberately chosen ideal simulation
parameters. Pinhole and fisheye coefficients are different models.
[OpenCV calibration reference](https://docs.opencv.org/doc/doxygen/html/d4/d93/group__calib.html).

| Camera type | Additional requirements |
| --- | --- |
| Monocular / wide-angle | Determine the projection from the actual output; a wide-angle lens does not uniquely determine a distortion model. For image matching, include exposure, shutter/readout timing, response, noise, compression, and image processing. |
| Dual-fisheye / 360° | Calibrate each lens and their complete relative pose. Record overlap, stitching/blending, exposure matching, stabilization, and panorama orientation. |
| Stereo / RGB-D | Calibrate each color, monochrome, or infrared imager separately. Record full relative pose, synchronization, rectification, and rectified projection matrices. Mechanical lens spacing is not calibrated baseline. |

A panorama belongs in `derived_outputs`: specify its projection, resolution, angular
orientation, seam, and stitching algorithm/version. An ideal cubemap panorama
does not reproduce a physical dual-fisheye stitching pipeline.

For depth, record input imagers, reference optical frame, encoding, scale/units,
invalid values, valid range, synchronization, processing, and noise/latency.
Distinguish axial `z_depth`, radial range, and disparity. If registered to RGB,
use the target image's frame and calibration. RealSense Z16 scale must be read
from the device. ZED raw and rectified calibration differ, and SDK
self-calibration can update the active values.
[RealSense projection and depth format](https://github.com/realsenseai/librealsense/wiki/Projection-in-RealSense-SDK-2.0),
[ZED calibration](https://www.stereolabs.com/docs/development/zed-sdk/modules/camera/camera-calibration).

Renderer depth is an ideal geometric output. Reproducing hardware depth requires
the corresponding processing and failure behavior. Active infrared projection
also needs projector, spectral, and material-response models. An IMU requires
its own extrinsics, axes, timing, bias, and noise calibration.

## Configure the simulator

Pin the installed simulator and relevant extensions, renderer, SDK, and bridge
versions. Use documentation for those versions and record the configuration in
`backends`.

### Isaac Sim

Import the mechanical asset, then create camera prims at the calibrated optical
centers with the appropriate projection and distortion. Configure render
products, resolution, sampling, and image/depth annotators. Add panorama or depth
processing as needed, then configure output frames, topics, simulation time, and
stream synchronization. A URDF import does not create these imaging pipelines.

Camera APIs differ between releases. For example, the 6.0 documentation uses
`RtxCamera` / `CameraSensor` in `isaacsim.sensors.experimental.rtx`; use the API
supported by your installed version.
[Isaac Sim camera reference (6.0)](https://docs.isaacsim.omniverse.nvidia.com/6.0.0/sensors/isaacsim_sensors_camera.html),
[URDF import guide](https://docs.isaacsim.omniverse.nvidia.com/latest/importer_exporter/import_urdf.html).

### MuJoCo

Export a fixed mounted body, or choose a free root body:

```bash
python scripts/export_mjcf.py --model go3s
python scripts/export_mjcf.py --model go3s --free
```

Asset builds refresh the fixed mounted MJCF; run the free export after rebuilding
if needed. Keep the whole model directory when moving it. Existing sites are
placement references. Add `<camera>` nodes with optical poses and map intrinsics
to the supported FOV or focal/principal-point/sensor-size parameters. Set the
actual render context dimensions and sampling rate; camera `resolution` metadata
does not replace runtime render dimensions.

Native MJCF projections are perspective/orthographic. Fisheye distortion,
stitching, and device-specific depth processing need a separate implementation.
Check the depth semantics of the renderer API you use.
[MuJoCo camera reference](https://mujoco.readthedocs.io/en/stable/XMLreference.html#body-camera).

### Gazebo / SDFormat

Add SDF sensor/camera definitions and the sensor system for the installed Gazebo
version. Configure pose, update rate, image size/format, clipping, intrinsics or
wide-angle projection, distortion, topics, and CameraInfo. Check support for the
chosen distortion model, multi-stream synchronization, registration, and bridge
behavior. Importing the supplied URDF does not add SDF sensors.
[SDFormat sensor/camera reference (1.12)](https://sdformat.org/spec/1.12/sensor/).

## Validate the result

Use known targets to check orientation, pixel projection and reprojection error,
left/right identity, rectification, RGB-D registration, depth units, and edge
occlusion. Measure output rates, timestamps, and synchronization. Record the
backend version and validation result only after testing the actual outputs.

The library's geometry and contact smoke tests do not validate image formation or
measured hardware dynamics. Center of mass and inertia are estimates; add mount
and cable loads or replace them with measured values for sensitive experiments.
PBR materials are appearance assets without measured spectral or infrared
response. Exposure, lighting, noise, and ISP behavior need separate matching.
See [SOURCES.md](SOURCES.md) for mechanical sources and configuration limits.
