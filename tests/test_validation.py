"""Run with: .venv/bin/python -m unittest discover -s tests -v."""
from pathlib import Path
import importlib.util
import json
import struct
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate.py"
SPEC = importlib.util.spec_from_file_location("camera_validation", SCRIPT)
validation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validation)


class DeliveryRequirements(unittest.TestCase):
    def test_urdf_relative_parent_reference_resolves_inside_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "urdf").mkdir()
            (root / "assets").mkdir()
            mesh = root / "assets" / "mesh.obj"
            mesh.write_text("mesh")
            self.assertEqual(validation.local_file(root / "urdf", "../assets/mesh.obj", root), mesh.resolve())

    def test_external_and_missing_references_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "model"
            package.mkdir()
            (root / "external.obj").write_text("mesh")
            for reference in ("../external.obj", str(root / "external.obj"), "package://camera/mesh.obj", "missing.obj"):
                with self.subTest(reference=reference), self.assertRaises(validation.ValidationError):
                    validation.local_file(package, reference, package)

    def test_off_diagonal_inertia_can_invalidate_positive_diagonal(self):
        inertia = dict(ixx="1", iyy="1", izz="1", ixy="2", ixz="0", iyz="0")
        with self.assertRaisesRegex(validation.ValidationError, "positive definite"):
            validation.inertia_properties(inertia)

    def test_physically_impossible_principal_moments_fail(self):
        inertia = dict(ixx="1", iyy="1", izz="3", ixy="0", ixz="0", iyz="0")
        with self.assertRaisesRegex(validation.ValidationError, "triangle inequality"):
            validation.inertia_properties(inertia)

    def test_truncated_glb_and_false_length_fail(self):
        with self.assertRaisesRegex(validation.ValidationError, "truncated"):
            validation.glb_document(b"glTF")
        data = struct.pack("<4sIII4s", b"glTF", 2, 28, 4, b"JSON") + b"{}  "
        with self.assertRaisesRegex(validation.ValidationError, "length"):
            validation.glb_document(data)


class ModelIntegration(unittest.TestCase):
    def setUp(self):
        import numpy as np
        import trimesh

        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.model = self.root / "models" / "testcam"
        for directory in ("urdf", "config", "assets/meshes/collision"):
            (self.model / directory).mkdir(parents=True, exist_ok=True)
        mesh = trimesh.creation.box(extents=[.04, .05, .1])
        mesh.apply_translation([0, 0, .05])
        mesh.export(self.model / "assets/meshes/testcam_visual.obj")
        mesh.export(self.model / "assets/meshes/collision/body.stl")
        scene = trimesh.Scene(mesh)
        scene.apply_transform(trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0]))
        (self.model / "assets/meshes/testcam_visual.glb").write_bytes(scene.export(file_type="glb"))
        config = dict(width_mm=50, height_mm=100, overall_depth_mm=40, mass_kg=.1)
        (self.model / "config/testcam.json").write_text(json.dumps(config))
        meta = dict(name="Test camera", config="config/testcam.json", visual="assets/meshes/testcam_visual.glb",
                    urdf="urdf/testcam.urdf")
        (self.model / "model.json").write_text(json.dumps(meta))
        self.urdf = self.model / "urdf/testcam.urdf"
        self.urdf.write_text('''<robot name="testcam">
  <link name="testcam_link">
    <inertial><mass value="0.1"/><inertia ixx="0.0001" iyy="0.0001" izz="0.0001" ixy="0" ixz="0" iyz="0"/></inertial>
    <visual><geometry><mesh filename="../assets/meshes/testcam_visual.obj"/></geometry></visual>
    <collision><origin xyz="0 0 0"/><geometry><mesh filename="../assets/meshes/collision/body.stl"/></geometry></collision>
  </link>
  <link name="testcam_mount"/>
  <joint name="mount" type="fixed"><parent link="testcam_link"/><child link="testcam_mount"/></joint>
</robot>''')

    def tearDown(self):
        self.tmp.cleanup()

    def test_generic_textures_optional_and_two_link_accessory_validates(self):
        report = validation.validate_model("testcam", self.root, write_report=False)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["embedded_texture_images"], 0)
        self.assertFalse((self.model / "docs/validation.json").exists())

    def test_missing_catalog_model_is_listed_and_fails_all_validation(self):
        catalog = self.root / "catalog"
        catalog.mkdir()
        entry = dict(id="testcam", width_mm=50, height_mm=100, overall_depth_mm=40, mass_kg=.1)
        (catalog / "cameras.json").write_text(json.dumps({"cameras": [entry, dict(entry, id="missingcam")]}))
        self.assertEqual(validation.available_models(self.root), ["missingcam", "testcam"])
        scripts = self.root / "scripts"
        scripts.mkdir()
        (scripts / "validate.py").write_text(SCRIPT.read_text())
        result = subprocess.run([sys.executable, str(scripts / "validate.py"), "--model", "all", "--no-write", "--json"],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertTrue(result.stdout.strip(), result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual([item["model"] for item in report["failures"]], ["missingcam"])
        self.assertEqual([item["model"] for item in report["reports"]], ["testcam"])

    def test_configured_mass_and_envelope_must_match_source_catalog(self):
        catalog = self.root / "catalog"
        catalog.mkdir()
        path = catalog / "cameras.json"
        entry = dict(id="testcam", width_mm=50, height_mm=100, overall_depth_mm=40, mass_kg=.1)
        for field in ("width_mm", "height_mm", "overall_depth_mm", "mass_kg"):
            with self.subTest(field=field):
                source = dict(entry, **{field: entry[field] + 1})
                path.write_text(json.dumps({"cameras": [source]}))
                with self.assertRaisesRegex(validation.ValidationError, f"Configured {field} differs from source catalog"):
                    validation.validate_model("testcam", self.root, write_report=False)
        path.write_text(json.dumps({"cameras": [entry]}))
        self.assertEqual(validation.validate_model("testcam", self.root, write_report=False)["status"], "PASS")

    def test_collision_origin_is_used_for_coverage(self):
        self.urdf.write_text(self.urdf.read_text().replace('xyz="0 0 0"', 'xyz="0.02 0 0"'))
        with self.assertRaisesRegex(validation.ValidationError, "Collision coverage gap"):
            validation.validate_model("testcam", self.root, write_report=False)

    def test_multiple_convex_parts_are_not_combined_into_one_concave_mesh(self):
        import trimesh
        part = trimesh.creation.box(extents=[.01, .01, .01])
        part.apply_translation([.01, .015, .09])
        part.export(self.model / "assets/meshes/collision/detail.stl")
        text = self.urdf.read_text().replace('</collision>', '</collision>\n'
            '<collision><geometry><mesh filename="../assets/meshes/collision/detail.stl"/></geometry></collision>')
        self.urdf.write_text(text)
        report = validation.validate_model("testcam", self.root, write_report=False)
        self.assertEqual(len(report["collision"]), 2)

    def test_unknown_joint_parent_fails_before_urdf_loader(self):
        self.urdf.write_text(self.urdf.read_text().replace('<parent link="testcam_link"/>', '<parent link="unknown"/>'))
        with self.assertRaisesRegex(validation.ValidationError, "unknown link"):
            validation.validate_model("testcam", self.root, write_report=False)


if __name__ == "__main__":
    unittest.main()
