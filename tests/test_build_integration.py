"""Exercise builder/export integration using small temporary camera packages."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import importlib
import json
import math
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import numpy as np
import trimesh

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
builder = importlib.import_module("build_assets")
exporter = importlib.import_module("export_mjcf")


class BuilderIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.builder_root = patch.object(builder, "ROOT", self.root)
        self.exporter_root = patch.object(exporter, "ROOT", self.root)
        self.builder_root.start()
        self.exporter_root.start()
        self.addCleanup(self.builder_root.stop)
        self.addCleanup(self.exporter_root.stop)
        self.addCleanup(self.temporary.cleanup)

    def build(self, camera):
        with redirect_stdout(StringIO()):
            builder.build(camera)
        directory = self.root / "models" / camera["id"]
        metadata = json.loads((directory / "model.json").read_text())
        return directory, metadata, ET.parse(directory / metadata["mjcf"])

    def test_rebuild_refreshes_mjcf_metadata_and_replaces_free_export(self):
        camera = dict(id="fixturecam", name="Fixture camera", family="360", profile="dual_lens",
                      width_mm=46, height_mm=100, overall_depth_mm=38.2, body_depth_mm=26.2,
                      mass_kg=.2, accuracy_notes="Unmeasured test geometry", sources=[])
        directory, metadata, exported = self.build(camera)
        self.assertIsNone(exported.find("worldbody/body/freejoint"))
        initial_inertia = exported.find("worldbody/body/inertial").get("diaginertia")
        exporter.export_model("fixturecam", free=True)
        self.assertIsNotNone(ET.parse(directory / metadata["mjcf"]).find("worldbody/body/freejoint"))
        camera["height_mm"] = 110
        directory, metadata, exported = self.build(camera)
        self.assertEqual(metadata["mjcf"], "mjcf/fixturecam.xml")
        self.assertIsNone(exported.find("worldbody/body/freejoint"), "Rebuild must refresh the default mounted export")
        self.assertNotEqual(exported.find("worldbody/body/inertial").get("diaginertia"), initial_inertia)
        source = ET.parse(directory / metadata["urdf"]).find("link/inertial/inertia")
        expected = [float(source.get(axis)) for axis in ("ixx", "iyy", "izz")]
        actual = np.fromstring(exported.find("worldbody/body/inertial").get("diaginertia"), sep=" ")
        np.testing.assert_allclose(actual, expected, atol=1e-12, rtol=0)

    def test_x5_retention_aligns_surface_frames_without_changing_visual(self):
        directory = self.root / "models/x5"
        for subdirectory in ("assets/meshes/collision", "config", "urdf"):
            (directory / subdirectory).mkdir(parents=True, exist_ok=True)
        visual = b"retained visual bytes"
        (directory / "assets/meshes/x5_visual.glb").write_bytes(visual)
        mesh = trimesh.creation.box(extents=[.0382, .046, .1245])
        mesh.apply_translation([0, 0, .06225])
        mesh.export(directory / "assets/meshes/x5_visual.obj")
        mesh.export(directory / "assets/meshes/collision/body.stl")
        (directory / "config/x5.json").write_text(json.dumps(dict(mass_kg=.2)))
        metadata = dict(urdf="urdf/x5.urdf", config="config/x5.json", visual="assets/meshes/x5_visual.glb")
        (directory / "model.json").write_text(json.dumps(metadata))
        urdf = '''<robot name="x5">
  <link name="x5_link"><inertial><mass value="0.2"/><inertia ixx="0.0001" iyy="0.0001" izz="0.0001" ixy="0" ixz="0" iyz="0"/></inertial>
    <visual><geometry><mesh filename="../assets/meshes/x5_visual.obj"/></geometry></visual>
    <collision><geometry><mesh filename="../assets/meshes/collision/body.stl"/></geometry></collision>
  </link>
  <link name="x5_mount"/><link name="x5_front_lens_surface"/><link name="x5_rear_lens_surface"/>
  <joint name="mount" type="fixed"><parent link="x5_link"/><child link="x5_mount"/><origin xyz="0 0 0" rpy="0 0 0"/></joint>
  <joint name="front" type="fixed"><parent link="x5_link"/><child link="x5_front_lens_surface"/><origin xyz="0.0191 0 0.104" rpy="0 0 0"/></joint>
  <joint name="rear" type="fixed"><parent link="x5_link"/><child link="x5_rear_lens_surface"/><origin xyz="-0.0191 0 0.104" rpy="0 0 0"/></joint>
</robot>'''
        (directory / metadata["urdf"]).write_text(urdf)
        _, metadata, exported = self.build(dict(id="x5", family="360", accuracy_notes="Uncalibrated geometry", sources=[]))
        self.assertEqual((directory / "assets/meshes/x5_visual.glb").read_bytes(), visual)
        self.assertEqual(metadata["lens_surface_frames"], ["x5_front_lens_surface", "x5_rear_lens_surface"])
        self.assertIsNone(exported.find("worldbody/body/freejoint"))
        joints = {joint.find("child").get("link"): joint for joint in ET.parse(directory / metadata["urdf"]).findall("joint")}
        sites = {site.get("name"): site for site in exported.findall("worldbody/body/site")}
        for name, sign in (("x5_front_lens_surface", 1), ("x5_rear_lens_surface", -1)):
            with self.subTest(frame=name):
                roll, pitch, yaw = np.fromstring(joints[name].find("origin").get("rpy"), sep=" ")
                np.testing.assert_allclose([roll, pitch, yaw], [-math.pi/2, 0, -sign*math.pi/2], atol=1e-10)
                quaternion = tuple(np.fromstring(sites[name].get("quat"), sep=" "))
                np.testing.assert_allclose(exporter.rotate(quaternion, (0, 0, 1)), (sign, 0, 0), atol=1e-10)

    def test_x5_urdf_source_builder_uses_package_root_and_canonical_filename(self):
        directory = self.root / "models/x5"
        for subdirectory in ("assets/meshes/visual", "config", "urdf"):
            (directory / subdirectory).mkdir(parents=True, exist_ok=True)
        config = dict(width_mm=46, height_mm=124.5, body_depth_mm=26.2,
                      overall_depth_mm=38.2, mass_kg=.2, com_height_mm=62.25,
                      lens_center_height_mm=104)
        (directory / "config/x5.json").write_text(json.dumps(config))
        body = trimesh.creation.box(extents=[.0262, .046, .1245])
        body.apply_translation([0, 0, .06225])
        body.export(directory / "assets/meshes/x5_visual.obj")
        body.export(directory / "assets/meshes/visual/body.obj")
        (directory / "assets/visual_manifest.json").write_text(json.dumps([
            dict(name="body", file="../assets/meshes/visual/body.obj", rgba=[.2, .2, .2, 1])]))
        scripts = self.root / "scripts/x5"
        scripts.mkdir(parents=True)
        script = scripts / "build_urdf.py"
        script.write_text((SCRIPTS / "x5/build_urdf.py").read_text())
        result = subprocess.run([sys.executable, str(script)], cwd=self.root,
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        path = directory / "urdf/x5.urdf"
        robot = ET.parse(path)
        self.assertEqual(robot.getroot().get("name"), "x5")
        self.assertEqual([p.name for p in (directory / "urdf").glob("*.urdf")], ["x5.urdf"])
        frames = exporter.geometric_frames(robot.getroot(), "x5_link")
        for name, sign in (("x5_front_lens_surface", 1), ("x5_rear_lens_surface", -1)):
            np.testing.assert_allclose(exporter.rotate(frames[name][1], (0, 0, 1)), (sign, 0, 0), atol=1e-10)


if __name__ == "__main__":
    unittest.main()
