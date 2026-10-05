"""Compile exported cameras and exercise their collision geometry in MuJoCo.

Generate all assets and MJCF files before running:
    python -m unittest discover -s tests -p 'test_mjcf.py' -v
"""
from collections import deque
from copy import deepcopy
from pathlib import Path
import json
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET

import mujoco
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def visual_bounds(model, data):
    """Recover imported visual bounds after MuJoCo's mesh centering/rotation."""
    points = []
    for geom in np.flatnonzero(model.geom_group == 2):
        mesh = model.geom_dataid[geom]
        address, count = model.mesh_vertadr[mesh], model.mesh_vertnum[mesh]
        vertices = model.mesh_vert[address:address+count]
        points.append(vertices @ data.geom_xmat[geom].reshape(3, 3).T + data.geom_xpos[geom])
    vertices = np.vstack(points)
    return np.array([vertices.min(axis=0), vertices.max(axis=0)])


class CameraMJCFTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cameras = json.loads((ROOT / "catalog/cameras.json").read_text())["cameras"]
        cls.exports = {}
        for camera in cls.cameras:
            model_dir = ROOT / "models" / camera["id"]
            metadata = json.loads((model_dir / "model.json").read_text())
            path = model_dir / metadata["mjcf"]
            if not path.is_file():
                raise FileNotFoundError(f"Run build_assets.py and export_mjcf.py --model all first: {path}")
            cls.exports[camera["id"]] = (model_dir, metadata, path)

    def test_all_models_compile_with_nominal_mass_and_inertia(self):
        for camera in self.cameras:
            with self.subTest(model=camera["id"]):
                model_dir, metadata, path = self.exports[camera["id"]]
                model = mujoco.MjModel.from_xml_path(str(path))
                data = mujoco.MjData(model)
                mujoco.mj_forward(model, data)
                self.assertEqual(model.nq, 0, "Default export must remain mounted")
                self.assertEqual(model.ncam, 0)
                self.assertEqual(model.nsensor, 0)
                self.assertGreater(model.nmesh, 0)
                self.assertTrue(np.all(model.mesh_vertnum > 0))
                self.assertTrue(np.all(model.mesh_facenum > 0))
                self.assertAlmostEqual(float(model.body_mass.sum()), camera["mass_kg"], places=10)
                urdf = ET.parse(model_dir / metadata["urdf"])
                inertial = urdf.find("link/inertial")
                source = inertial.find("inertia").attrib
                matrix = np.array([[float(source["ixx"]), float(source["ixy"]), float(source["ixz"])],
                                   [float(source["ixy"]), float(source["iyy"]), float(source["iyz"])],
                                   [float(source["ixz"]), float(source["iyz"]), float(source["izz"])]])
                body = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, metadata.get("root_link", f"{camera['id']}_link"))
                np.testing.assert_allclose(np.sort(model.body_inertia[body]), np.linalg.eigvalsh(matrix), rtol=1e-8, atol=1e-12)
                np.testing.assert_allclose(model.body_ipos[body], np.fromstring(inertial.find("origin").get("xyz", "0 0 0"), sep=" "), atol=1e-12)
                self.assertTrue(np.all(model.body_inertia[body] > 0))
                self.assertTrue(np.all(model.geom_contype[model.geom_group == 2] == 0))
                self.assertTrue(np.all(model.geom_conaffinity[model.geom_group == 2] == 0))
                self.assertGreater(np.count_nonzero(model.geom_contype[model.geom_group == 3]), 0)

    def test_mesh_import_preserves_envelope_and_geometric_frames(self):
        for camera in self.cameras:
            with self.subTest(model=camera["id"]):
                model_dir, metadata, path = self.exports[camera["id"]]
                model = mujoco.MjModel.from_xml_path(str(path))
                data = mujoco.MjData(model)
                mujoco.mj_forward(model, data)
                bounds = visual_bounds(model, data)
                expected = np.array([camera["overall_depth_mm"], camera["width_mm"], camera["height_mm"]]) * .001
                np.testing.assert_allclose(bounds[1]-bounds[0], expected, atol=2e-6, rtol=0)
                self.assertAlmostEqual(float(bounds[0, 2]), 0, places=6)
                urdf = ET.parse(model_dir / metadata["urdf"])
                for joint in urdf.findall("joint"):
                    self.assertEqual(joint.get("type"), "fixed")
                    site_name = joint.find("child").get("link")
                    site = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, site_name)
                    self.assertGreaterEqual(site, 0)
                    # Generated frames are direct children of the root link.
                    self.assertEqual(joint.find("parent").get("link"), metadata.get("root_link", f"{camera['id']}_link"))
                    origin = joint.find("origin")
                    position = np.fromstring(origin.get("xyz", "0 0 0"), sep=" ")
                    np.testing.assert_allclose(data.site_xpos[site], position, atol=1e-9)
                    roll, pitch, yaw = np.fromstring(origin.get("rpy", "0 0 0"), sep=" ")
                    cx, sx, cy, sy, cz, sz = np.cos(roll), np.sin(roll), np.cos(pitch), np.sin(pitch), np.cos(yaw), np.sin(yaw)
                    rotation = np.array([[cz*cy, cz*sy*sx-sz*cx, cz*sy*cx+sz*sx],
                                         [sz*cy, sz*sy*sx+cz*cx, sz*sy*cx-cz*sx],
                                         [-sy, cy*sx, cy*cx]])
                    np.testing.assert_allclose(data.site_xmat[site].reshape(3, 3), rotation, atol=1e-9)

    def test_relative_mesh_paths_survive_relocation(self):
        # Exercise every source mesh reference without depending on the repo cwd.
        for camera in self.cameras:
            with self.subTest(model=camera["id"]), tempfile.TemporaryDirectory(prefix="camera-mjcf-") as temporary:
                model_dir, _, path = self.exports[camera["id"]]
                relocated = Path(temporary) / camera["id"]
                shutil.copytree(model_dir / "mjcf", relocated / "mjcf")
                assets = ET.parse(path).findall("asset/mesh")
                for mesh in assets:
                    reference = Path(mesh.attrib["file"])
                    self.assertFalse(reference.is_absolute())
                    source = (path.parent / reference).resolve()
                    relative = source.relative_to(model_dir.resolve())
                    target = relocated / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                model = mujoco.MjModel.from_xml_path(str(relocated / "mjcf" / path.name))
                self.assertAlmostEqual(float(model.body_mass.sum()), camera["mass_kg"], places=10)

    def test_free_camera_falls_and_reaches_bounded_contact_rest(self):
        """Smoke-test contact stability; this is not measured camera dynamics.

        Mesh contact can retain small numerical rocking at rest. Test a full
        second of bounded COM/attitude motion and dissipated kinetic energy,
        rather than combining instantaneous m/s and rad/s into one norm.
        Preserve the export's timestep, contact parameters and friction.
        """
        for camera in self.cameras:
            with self.subTest(model=camera["id"]):
                _, _, path = self.exports[camera["id"]]
                scene = deepcopy(ET.parse(path).getroot())
                # Keep the test scene in memory and preserve absolute asset reads.
                for mesh in scene.findall("asset/mesh"):
                    mesh.set("file", str((path.parent / mesh.attrib["file"]).resolve()))
                world = scene.find("worldbody")
                body = world.find("body")
                body.set("pos", "0 0 0.12")
                ET.SubElement(body, "freejoint", name="test_free")
                ET.SubElement(world, "geom", name="test_floor", type="plane", size="1 1 0.1", contype="1", conaffinity="1")
                ET.SubElement(scene.find("option"), "flag", energy="enable")
                model = mujoco.MjModel.from_xml_string(ET.tostring(scene, encoding="unicode"))
                data = mujoco.MjData(model)
                mujoco.mj_forward(model, data)
                self.assertEqual(model.nq, 7)
                initial_height = float(data.xpos[1, 2])
                # The imposed 12 cm translation supplies m*g*h drop energy.
                drop_energy = camera["mass_kg"] * np.linalg.norm(model.opt.gravity) * .12
                window_steps = max(1, round(1.0 / model.opt.timestep))
                window = deque(maxlen=window_steps)
                contacted = False
                rest = False
                metrics = {}
                for step in range(round(10.0 / model.opt.timestep)):
                    mujoco.mj_step(model, data)
                    contacted |= data.ncon > 0
                    window.append((data.xipos[1].copy(), data.xquat[1].copy(),
                                   max(0., float(data.energy[1])), data.ncon,
                                   float(np.linalg.norm(data.qvel[:3])),
                                   float(np.linalg.norm(data.qvel[3:]))))
                    if step % 100 == 0:
                        self.assertTrue(np.all(np.isfinite(data.qpos)))
                        self.assertTrue(np.all(np.isfinite(data.qvel[:3])), "Linear velocity must remain finite (m/s)")
                        self.assertTrue(np.all(np.isfinite(data.qvel[3:])), "Angular velocity must remain finite (rad/s)")
                        self.assertTrue(np.all(np.isfinite(data.energy)))
                    if data.time >= 2.0 and (step+1) % window_steps == 0:
                        positions = np.array([sample[0] for sample in window])
                        quaternions = np.array([sample[1] for sample in window])
                        attitude_range = float(2*np.arccos(np.clip(np.abs(quaternions @ quaternions[0]), 0, 1)).max())
                        metrics = dict(
                            time_s=float(data.time),
                            com_range_m=float(np.linalg.norm(np.ptp(positions, axis=0))),
                            attitude_range_rad=attitude_range,
                            kinetic_fraction=max(sample[2] for sample in window) / drop_energy,
                            min_contacts=min(sample[3] for sample in window),
                            max_linear_velocity_m_s=max(sample[4] for sample in window),
                            max_angular_velocity_rad_s=max(sample[5] for sample in window),
                        )
                        # Fixture-level rest means sub-mm COM movement, <2°
                        # rocking and <0.1% of initial drop energy over 1 s.
                        rest = (metrics["com_range_m"] < .001
                                and metrics["attitude_range_rad"] < np.deg2rad(2)
                                and metrics["kinetic_fraction"] < .001
                                and metrics["min_contacts"] > 0)
                        if rest:
                            break
                mujoco.mj_forward(model, data)
                self.assertTrue(contacted, "Collision geoms must contact the floor")
                self.assertLess(float(data.xpos[1, 2]), initial_height-.03)
                self.assertTrue(rest, f"Camera must reach bounded contact rest within 10 s: {metrics}")
                self.assertGreater(float(visual_bounds(model, data)[0, 2]), -.004, "Exterior should stay above the floor within contact tolerance")
                self.assertTrue(np.all(np.isfinite(data.qpos)))
                self.assertTrue(np.all(np.isfinite(data.qvel)))


if __name__ == "__main__":
    unittest.main()
