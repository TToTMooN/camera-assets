"""Exercise the distribution SDK with local releases and no network access."""
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path
import stat
import sys
import tempfile
from threading import Barrier
import unittest
from unittest.mock import patch
from urllib.error import URLError
import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import camera_assets as assets


MODEL_ID = "go3s"
BASE_URL = "https://camera-assets.invalid/releases"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fixture_files(version):
    metadata = dict(
        name=f"Synthetic GO 3S {version}", family="wearable", brand="fixture",
        root_link="go3s_link", mount_link="go3s_mount",
        urdf="urdf/go3s.urdf", mjcf="mjcf/go3s.xml",
        visual="assets/meshes/go3s_visual.glb", config="config/go3s.json",
        sensor_manifest="config/sensors.json",
    )
    files = {
        "model.json": json.dumps(metadata).encode(),
        "urdf/go3s.urdf": f'<robot name="fixture_{version}"><link name="go3s_link"/></robot>'.encode(),
        "mjcf/go3s.xml": b'<mujoco model="fixture"><worldbody><body name="go3s_link"/></worldbody></mujoco>',
        "assets/meshes/go3s_visual.glb": b"synthetic-glb-fixture",
        "config/go3s.json": b'{"units":"meters"}',
        "config/sensors.json": b'{"status":"uncalibrated"}',
        "LICENSE": b"Synthetic test fixture; not a distributed camera asset.\n",
    }
    return metadata, files


def release_fixture(version="v0.1.0", *, files=None, members=None):
    metadata, defaults = fixture_files(version)
    files = defaults if files is None else files
    members = [(f"models/{MODEL_ID}/{name}", data) for name, data in files.items()] if members is None else members
    output = io.BytesIO()
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Duplicate name:", category=UserWarning)
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
            for name, data in members:
                archive.writestr(name, data)
    archive_bytes = output.getvalue()
    record = dict(
        archive=f"{MODEL_ID}-{version}.zip", sha256=digest(archive_bytes),
        size_bytes=len(archive_bytes), unpacked_size_bytes=sum(map(len, files.values())),
        files={name: dict(sha256=digest(data), size_bytes=len(data)) for name, data in files.items()},
    )
    manifest = dict(schema_version=1, version=version, repository="TToTMooN/camera-assets",
                    source_commit="a" * 40, models={MODEL_ID: record})
    return dict(version=version, metadata=metadata, files=files, archive=archive_bytes, manifest=manifest)


class DistributionFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name).resolve()
        self.cache = self.directory / "cache"
        self.rejected_release_count = 0

    @contextmanager
    def downloads(self, *releases):
        responses = {}
        for release in releases:
            prefix = f"{BASE_URL}/{release['version']}"
            record = release["manifest"]["models"][MODEL_ID]
            responses[f"{prefix}/manifest.json"] = json.dumps(release["manifest"]).encode()
            responses[f"{prefix}/{record['archive']}"] = release["archive"]

        def open_fixture(request, *args, **kwargs):
            url = request.full_url if hasattr(request, "full_url") else request
            if url not in responses:
                raise AssertionError(f"Unexpected download: {url}")
            response = io.BytesIO(responses[url])
            response.status = 200
            response.headers = {"Content-Length": str(len(responses[url]))}
            return response

        with patch("camera_assets.api.urlopen", side_effect=open_fixture) as download:
            yield download

    def fetch(self, version="v0.1.0", **kwargs):
        return assets.fetch(MODEL_ID, version=version, cache_dir=self.cache,
                            base_url=BASE_URL, **kwargs)

    def assert_rejected_release(self, release):
        self.rejected_release_count += 1
        cache = self.directory / f"rejected-{self.rejected_release_count}"
        with self.downloads(release), self.assertRaises(assets.AssetError):
            assets.fetch(MODEL_ID, version=release["version"], cache_dir=cache, base_url=BASE_URL)
        self.assertFalse((cache / release["version"] / "models" / MODEL_ID).exists())
        self.assertFalse((cache / release["version"] / "escaped.txt").exists())


class DistributionClientTests(DistributionFixture):

    def test_fetch_checks_bytes_and_returns_readable_model_paths(self):
        release = release_fixture()
        with self.downloads(release) as download:
            model = self.fetch("0.1.0")
        self.assertEqual(download.call_count, 2)
        self.assertEqual(model.id, MODEL_ID)
        self.assertEqual(model.version, "v0.1.0")
        self.assertEqual(model.directory, self.cache / "v0.1.0" / "models" / MODEL_ID)
        self.assertEqual(model.metadata, release["metadata"])
        for relative, expected in release["files"].items():
            self.assertEqual((model.directory / relative).read_bytes(), expected)
        for property_name, relative in (
                ("urdf", "urdf/go3s.urdf"), ("mjcf", "mjcf/go3s.xml"),
                ("visual", "assets/meshes/go3s_visual.glb"),
                ("sensor_manifest", "config/sensors.json")):
            with self.subTest(path=property_name):
                path = getattr(model, property_name)
                self.assertIsInstance(path, Path)
                self.assertEqual(path, model.directory / relative)
                self.assertTrue(path.is_file())
        manifest = json.loads((self.cache / "v0.1.0" / "manifest.json").read_text())
        self.assertEqual(manifest, release["manifest"])

    def test_cached_fetch_and_get_model_are_strictly_offline(self):
        with self.downloads(release_fixture()):
            downloaded = self.fetch()
        with patch("camera_assets.api.urlopen", side_effect=AssertionError("Network forbidden")) as download:
            cached = self.fetch()
            resolved = assets.get_model(MODEL_ID, version="0.1.0", cache_dir=self.cache)
        download.assert_not_called()
        self.assertEqual(cached.directory, downloaded.directory)
        self.assertEqual(resolved.urdf, downloaded.urdf)
        self.assertEqual(resolved.version, "v0.1.0")

    def test_concurrent_fetches_publish_one_cache_without_replacing_files(self):
        release = release_fixture()
        record = release['manifest']['models'][MODEL_ID]
        archive_url = f"{BASE_URL}/v0.1.0/{record['archive']}"
        manifest_url = f"{BASE_URL}/v0.1.0/manifest.json"
        staged_archives = Barrier(2)

        class SynchronizedArchive(io.BytesIO):
            def read(self, size=-1):
                chunk = super().read(size)
                if not chunk:
                    # Both callers have written their ZIP before either can publish.
                    staged_archives.wait(timeout=5)
                return chunk

        def open_fixture(request, *args, **kwargs):
            url = request.full_url if hasattr(request, 'full_url') else request
            if url == manifest_url:
                return io.BytesIO(json.dumps(release['manifest']).encode())
            if url == archive_url:
                return SynchronizedArchive(release['archive'])
            raise AssertionError(f"Unexpected download: {url}")

        def fetch_snapshot():
            model = self.fetch()
            file_identity = {name: (model.directory / name).stat().st_ino
                             for name in release['files']}
            return model, model.directory.stat().st_ino, file_identity

        with patch('camera_assets.api.urlopen', side_effect=open_fixture) as download:
            with ThreadPoolExecutor(max_workers=2) as workers:
                futures = [workers.submit(fetch_snapshot) for _ in range(2)]
                results = [future.result(timeout=10) for future in futures]
        first, second = results[0][0], results[1][0]
        self.assertEqual(first.directory, second.directory)
        self.assertEqual(results[0][1:], results[1][1:])
        for name, expected in release['files'].items():
            self.assertEqual((first.directory / name).read_bytes(), expected)
        archive_calls = [call for call in download.call_args_list
                         if (call.args[0].full_url if hasattr(call.args[0], 'full_url')
                             else call.args[0]) == archive_url]
        self.assertEqual(len(archive_calls), 2)
        library = self.cache / 'v0.1.0'
        self.assertEqual({path.name for path in library.iterdir()}, {'manifest.json', 'models'})
        self.assertEqual({path.name for path in (library / 'models').iterdir()}, {MODEL_ID})
        with patch('camera_assets.api.urlopen', side_effect=AssertionError('Network forbidden')) as offline:
            resolved = assets.get_model(MODEL_ID, version='v0.1.0', cache_dir=self.cache)
        offline.assert_not_called()
        self.assertEqual(resolved.directory, first.directory)

    def test_offline_miss_never_downloads(self):
        with patch("camera_assets.api.urlopen", side_effect=AssertionError("Network forbidden")) as download:
            with self.assertRaises(assets.AssetError):
                assets.get_model(MODEL_ID, version="v0.1.0", cache_dir=self.cache)
        download.assert_not_called()

    def test_catalog_is_bundled_and_offline(self):
        expected = {camera["id"] for camera in json.loads((ROOT / "catalog/cameras.json").read_text())["cameras"]}
        with patch("camera_assets.api.urlopen", side_effect=AssertionError("Network forbidden")) as download:
            ids = assets.list_models()
        download.assert_not_called()
        self.assertIsInstance(ids, list)
        self.assertTrue(all(isinstance(ident, str) for ident in ids))
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), expected)

    def test_explicit_version_is_required_and_latest_or_unsafe_values_are_rejected(self):
        with patch("camera_assets.api.urlopen", side_effect=AssertionError("Network forbidden")) as download:
            with self.assertRaises(TypeError):
                assets.fetch(MODEL_ID, cache_dir=self.cache)
            for version in (None, "", "latest", "vlatest", "../0.1.0", "v0.1.0/../outside", "0.1", "v0.1.0?query"):
                with self.subTest(version=version), self.assertRaises(assets.AssetError):
                    self.fetch(version)
            for ident in ("../go3s", "/go3s", "go3s/../outside"):
                with self.subTest(model=ident), self.assertRaises(assets.AssetError):
                    assets.fetch(ident, version="v0.1.0", cache_dir=self.cache, base_url=BASE_URL)
        download.assert_not_called()
        self.assertIsInstance(assets.AssetError("fixture"), ValueError)

    def test_unknown_model_is_rejected_without_downloading_an_archive(self):
        with self.downloads(release_fixture()) as download, self.assertRaises(assets.AssetError):
            assets.fetch("unknown_model", version="v0.1.0", cache_dir=self.cache, base_url=BASE_URL)
        self.assertLessEqual(download.call_count, 1)

    def test_archive_digest_mismatch_is_rejected(self):
        release = release_fixture()
        release["manifest"]["models"][MODEL_ID]["sha256"] = "0" * 64
        self.assert_rejected_release(release)

    def test_file_digest_mismatch_is_rejected(self):
        release = release_fixture()
        release["manifest"]["models"][MODEL_ID]["files"]["model.json"]["sha256"] = "0" * 64
        self.assert_rejected_release(release)

    def test_truncated_zip_is_rejected_even_with_matching_archive_digest(self):
        release = release_fixture()
        release["archive"] = release["archive"][:-10]
        record = release["manifest"]["models"][MODEL_ID]
        record.update(sha256=digest(release["archive"]), size_bytes=len(release["archive"]))
        self.assert_rejected_release(release)

    def test_archive_and_unpacked_size_mismatches_are_rejected(self):
        for field in ("size_bytes", "unpacked_size_bytes"):
            with self.subTest(field=field):
                release = release_fixture()
                release["manifest"]["models"][MODEL_ID][field] += 1
                self.assert_rejected_release(release)

    def test_symlink_duplicate_unexpected_and_escaping_members_are_rejected(self):
        _, normal_files = fixture_files("v0.1.0")
        normal_members = [(f"models/{MODEL_ID}/{name}", data) for name, data in normal_files.items()]
        link = zipfile.ZipInfo(f"models/{MODEL_ID}/link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        cases = (
            ("symlink", {**normal_files, "link": b"../../outside"}, normal_members + [(link, b"../../outside")]),
            ("duplicate", normal_files, normal_members + [normal_members[0]]),
            ("unexpected", normal_files, normal_members + [(f"models/{MODEL_ID}/unlisted.txt", b"unexpected")]),
            ("path escape", {**normal_files, "../../escaped.txt": b"escape"},
             normal_members + [(f"models/{MODEL_ID}/../../escaped.txt", b"escape")]),
        )
        for name, files, members in cases:
            with self.subTest(member=name):
                self.assert_rejected_release(release_fixture(files=files, members=members))
        self.assertFalse((self.directory / "escaped.txt").exists())
        self.assertFalse((self.cache / "v0.1.0" / "escaped.txt").exists())

    def test_manifest_version_and_archive_path_must_match_requested_release(self):
        for field, value in (("version", "v0.2.0"), ("archive", "../outside.zip")):
            with self.subTest(field=field):
                release = release_fixture()
                if field == "version":
                    release["manifest"][field] = value
                else:
                    release["manifest"]["models"][MODEL_ID][field] = value
                self.assert_rejected_release(release)

    def test_changed_calibration_in_cache_is_preserved_and_not_repaired(self):
        with self.downloads(release_fixture()):
            model = self.fetch()
        calibrated = b'{"status":"calibrated","source":"local-measurement-sentinel"}\n'
        model.sensor_manifest.write_bytes(calibrated)
        with patch("camera_assets.api.urlopen", side_effect=AssertionError("No automatic repair")) as download:
            with self.assertRaises(assets.AssetError):
                self.fetch()
            with self.assertRaises(assets.AssetError):
                assets.get_model(MODEL_ID, version="v0.1.0", cache_dir=self.cache)
        download.assert_not_called()
        self.assertEqual(model.sensor_manifest.read_bytes(), calibrated)

    def test_preexisting_corrupt_cache_directory_is_never_overwritten(self):
        folder = self.cache / "v0.1.0" / "models" / MODEL_ID
        folder.mkdir(parents=True)
        sentinel = b"preexisting-corrupt-model-preserve-me"
        (folder / "model.json").write_bytes(sentinel)
        with self.downloads(release_fixture()), self.assertRaises(assets.AssetError):
            self.fetch()
        self.assertEqual((folder / "model.json").read_bytes(), sentinel)

    def test_local_root_preserves_calibration_and_is_separate_from_release_cache(self):
        local_root = self.cache
        folder = local_root / "models" / MODEL_ID
        _, files = fixture_files("local")
        calibrated = b'{"status":"calibrated","source":"local-device"}\n'
        files["config/sensors.json"] = calibrated
        for relative, data in files.items():
            target = folder / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        with patch("camera_assets.api.urlopen", side_effect=AssertionError("Network forbidden")) as download:
            local = assets.get_model(MODEL_ID, root=local_root)
        download.assert_not_called()
        self.assertEqual(local.directory, folder)
        self.assertIsNone(local.version)
        self.assertEqual(local.sensor_manifest.read_bytes(), calibrated)
        with self.downloads(release_fixture()):
            released = self.fetch()
        self.assertNotEqual(local.directory, released.directory)
        self.assertEqual(local.sensor_manifest.read_bytes(), calibrated)

    def test_two_release_versions_are_isolated_and_remain_offline_resolvable(self):
        first, second = release_fixture("v0.1.0"), release_fixture("v0.2.0")
        with self.downloads(first, second):
            model1 = self.fetch("v0.1.0")
            model2 = self.fetch("0.2.0")
        self.assertNotEqual(model1.directory, model2.directory)
        self.assertNotEqual(model1.urdf.read_bytes(), model2.urdf.read_bytes())
        with patch("camera_assets.api.urlopen", side_effect=AssertionError("Network forbidden")) as download:
            for version, expected in (("v0.1.0", model1), ("v0.2.0", model2)):
                with self.subTest(version=version):
                    actual = assets.get_model(MODEL_ID, version=version, cache_dir=self.cache)
                    self.assertEqual(actual.directory, expected.directory)
                    self.assertEqual(actual.metadata, expected.metadata)
        download.assert_not_called()


class DistributionCliTests(DistributionFixture):
    """Use the real argument parser with the same mocked release transport."""

    def run_cli(self, arguments):
        from camera_assets.cli import main
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                code = main(arguments)
            except SystemExit as error:
                code = error.code
        return 0 if code is None else code, stdout.getvalue(), stderr.getvalue()

    def test_cli_list_and_path_do_not_access_network(self):
        with self.downloads(release_fixture()):
            model = self.fetch()
        with patch("camera_assets.api.urlopen", side_effect=AssertionError("Network forbidden")) as download:
            code, stdout, stderr = self.run_cli(["list"])
            self.assertEqual(code, 0)
            self.assertIn(MODEL_ID, stdout.split())
            self.assertEqual(stderr, "")
            for output_format, expected in (("urdf", model.urdf), ("mjcf", model.mjcf),
                                            ("glb", model.visual), ("sensors", model.sensor_manifest),
                                            ("directory", model.directory)):
                with self.subTest(format=output_format):
                    code, stdout, stderr = self.run_cli([
                        "path", MODEL_ID, "--version", "v0.1.0", "--cache-dir", str(self.cache),
                        "--format", output_format,
                    ])
                    self.assertEqual(code, 0)
                    self.assertEqual(stdout.strip(), str(expected))
                    self.assertEqual(stderr, "")
        download.assert_not_called()

    def test_cli_fetch_reports_network_error_without_traceback(self):
        with patch("camera_assets.api.urlopen", side_effect=URLError("fixture connection refused")):
            code, stdout, stderr = self.run_cli([
                "fetch", MODEL_ID, "--version", "v0.1.0", "--cache-dir", str(self.cache),
                "--base-url", BASE_URL,
            ])
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("fixture connection refused", stderr)
        self.assertNotIn("Traceback", stderr)

    def test_cli_fetch_requires_version_before_network_access(self):
        with patch("camera_assets.api.urlopen", side_effect=AssertionError("Network forbidden")) as download:
            code, stdout, stderr = self.run_cli(["fetch", MODEL_ID])
        download.assert_not_called()
        self.assertEqual(code, 2)
        self.assertIn("--version", stderr)


if __name__ == "__main__":
    unittest.main()
