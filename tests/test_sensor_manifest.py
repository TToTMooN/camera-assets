"""Reject misleading sensor calibration declarations and preserve user data."""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import sys
import tempfile
import unittest

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import sensor_manifest as sensors
import preview_assets as previews


class SensorManifestTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.camera, self.folder = self.fixture("go3s", "wearable", ["front"])
        self.document = sensors.make_template(self.camera, self.folder)

    def fixture(self, ident, family, lenses):
        folder = self.root / ident
        (folder / "config").mkdir(parents=True)
        (folder / "urdf").mkdir()
        (folder / "model.json").write_text(json.dumps(dict(root_link=f"{ident}_link", urdf="urdf/camera.urdf")))
        references = [f"{ident}_mount", *[f"{ident}_{name}_lens_surface" for name in lenses]]
        links = "".join(f'<link name="{name}"/>' for name in references)
        joints = "".join(f'<joint name="j{i}" type="fixed"><parent link="{ident}_link"/><child link="{name}"/><origin xyz="0.01 0 0.02" rpy="0 0 0"/></joint>'
                         for i, name in enumerate(references))
        (folder / "urdf/camera.urdf").write_text(f'<robot name="fixture"><link name="{ident}_link"/>{links}{joints}</robot>')
        return dict(id=ident, family=family), folder

    def calibrated_fixture(self):
        document = deepcopy(self.document)
        document['status'] = 'calibrated'
        document['calibration'].update(device_serial='synthetic-fixture', firmware='fixture',
                                       source='unit-test-only', date='2026-01-01')
        imager = document['imagers'][0]
        imager.update(geometry_mapping_status='verified', optical_frame='fixture_optical')
        imager['T_body_optical'].update(translation_m=[0,0,0], quaternion_xyzw=[0,0,0,1])
        imager['modes'][0].update(mode_id='synthetic', image_state='raw', projection_model='pinhole',
                                resolution_px=[640,480], rate_hz=30, K_px=[[300,0,320],[0,300,240],[0,0,1]],
                                distortion_model='none', distortion_coefficients=[], encoding='rgb8',
                                calibration_source='unit-test-only')
        return document

    def test_null_template_passes_structure_but_fails_calibration_requirement(self):
        missing = sensors.check_manifest(self.document, self.camera, self.folder)
        self.assertIn('image_0.unconfigured.K_px', missing)
        with self.assertRaisesRegex(ValueError, 'Optical calibration missing'):
            sensors.check_manifest(self.document, self.camera, self.folder, require_calibrated=True)

    def test_complete_synthetic_optics_do_not_certify_backend(self):
        document = self.calibrated_fixture()
        self.assertEqual(sensors.check_manifest(document, self.camera, self.folder, True), [])
        self.assertEqual(document['backends']['isaac_sim']['validation_status'], 'not_run')

    def test_projector_is_emitter_and_oak_stereo_is_monochrome(self):
        camera, folder = self.fixture('realsense_d455', 'depth_stereo', ['left','projector','rgb','right'])
        document = sensors.make_template(camera, folder)
        self.assertEqual(len(document['imagers']), 3)
        self.assertEqual(len(document['emitters']), 1)
        self.assertFalse(any('projector' in name for unit in document['imagers'] for name in unit['geometry_frame_candidates']))
        document['emitters'][0]['geometry_frame_candidates'] = ['stale_nonexistent_frame']
        with self.assertRaisesRegex(ValueError, 'Emitter'):
            sensors.check_manifest(document, camera, folder)
        camera, folder = self.fixture('oak_d', 'depth_stereo', ['left','rgb','right'])
        document = sensors.make_template(camera, folder)
        self.assertEqual(document['imagers'][0]['semantic_role'], 'mono_left')

    def test_calibration_and_pose_declaration_regressions(self):
        mutations = [
            ('intrinsic', lambda d: d['imagers'][0]['modes'][0].update(K_px=[[1,1,0],[1,1,0],[0,0,1]])),
            ('not applicable', lambda d: d.update(status='not_applicable')),
            ('verified mapping', lambda d: d['imagers'][0].update(geometry_frame_candidates=[])),
            ('mounting quaternion', lambda d: d['T_robot_body'].update(quaternion_xyzw=[0,0,0,0])),
            ('normalized', lambda d: d['imagers'][0]['T_body_optical'].update(quaternion_xyzw=[0,0,0,0])),
            ('nonfinite', lambda d: d['imagers'][0]['modes'][0].update(rate_hz=float('inf'))),
        ]
        for message, mutate in mutations:
            with self.subTest(case=message):
                document = self.calibrated_fixture()
                mutate(document)
                with self.assertRaisesRegex(ValueError, message):
                    sensors.check_manifest(document, self.camera, self.folder, True)

        camera, folder = self.fixture('realsense_d455', 'depth_stereo', ['left','projector','rgb','right'])
        for message in ('duplicate verified geometry reference', 'duplicate optical frame'):
            with self.subTest(case=message):
                document = sensors.make_template(camera, folder)
                left, right = document['imagers'][:2]
                if message == 'duplicate verified geometry reference':
                    for imager in (left, right):
                        imager.update(geometry_mapping_status='verified',
                                      geometry_frame_candidates=['realsense_d455_left_lens_surface'])
                else:
                    left['optical_frame'] = right['optical_frame'] = 'shared_optical'
                with self.assertRaisesRegex(ValueError, message):
                    sensors.check_manifest(document, camera, folder)

    def test_existing_calibration_is_never_overwritten(self):
        path = sensors.ensure_template(self.camera, self.folder)
        original = json.dumps(self.calibrated_fixture(), indent=4).encode()
        path.write_bytes(original)
        sensors.ensure_template(self.camera, self.folder)
        self.assertEqual(path.read_bytes(), original)
        metadata = json.loads((self.folder / 'model.json').read_text())
        self.assertEqual(metadata['sensor_manifest'], 'config/sensors.json')

    def test_accessory_has_no_imaging_or_calibration_requirement(self):
        camera, folder = self.fixture('go3_action_pod', 'accessory', [])
        document = sensors.make_template(camera, folder)
        self.assertEqual(document['imagers'], [])
        self.assertEqual(sensors.check_manifest(document, camera, folder, True), [])

    def test_urdf_changes_make_geometry_snapshot_stale(self):
        path = self.folder / 'urdf/camera.urdf'
        path.write_text(path.read_text().replace('0.01 0 0.02', '0.02 0 0.02'))
        with self.assertRaisesRegex(ValueError, 'stale'):
            sensors.check_manifest(self.document, self.camera, self.folder)

    def test_every_delivered_model_has_an_honest_sensor_manifest(self):
        cameras = json.loads((ROOT / 'catalog/cameras.json').read_text())['cameras']
        for camera in cameras:
            with self.subTest(model=camera['id']):
                folder = ROOT / 'models' / camera['id']
                metadata = json.loads((folder / 'model.json').read_text())
                document = json.loads((folder / metadata['sensor_manifest']).read_text())
                sensors.check_manifest(document, camera, folder)
                self.assertIn(document['status'], ('uncalibrated','not_applicable'))
                self.assertTrue(all(backend['validation_status'] == 'not_run' for backend in document['backends'].values()))


class PreviewRecordTests(unittest.TestCase):
    def test_stale_glb_and_back_only_record_cannot_reuse_old_hero_png(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / 'models/fixture'
            (folder / 'preview').mkdir(parents=True)
            glb = folder / 'fixture.glb'
            glb.write_bytes(b'synthetic-glb-record-fixture')
            (folder / 'model.json').write_text(json.dumps(dict(visual='fixture.glb')))
            Image.new('RGB',(8,8)).save(folder / 'preview/studio_hero.png')
            record = dict(renderer='Blender Cycles', glb_sha256=hashlib.sha256(glb.read_bytes()).hexdigest(),
                          views=dict(hero=dict(file='studio_hero.png',size_px=8)))
            path = folder / 'preview/studio_render.json'
            path.write_text(json.dumps(record))
            with patch.object(previews,'ROOT',root):
                self.assertEqual(previews.load_render('fixture','hero').size,(8,8))
                glb.write_bytes(b'changed-geometry')
                with self.assertRaisesRegex(ValueError,'stale'):
                    previews.load_render('fixture','hero')
                record['glb_sha256'] = hashlib.sha256(glb.read_bytes()).hexdigest()
                record['views'] = dict(back=dict(file='studio_back.png',size_px=8))
                path.write_text(json.dumps(record))
                with self.assertRaisesRegex(ValueError,'hero is not present'):
                    previews.load_render('fixture','hero')


if __name__ == '__main__':
    unittest.main()
