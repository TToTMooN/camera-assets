"""Exercise deterministic runtime packaging without SDK or simulator imports."""
from pathlib import Path
import errno
import hashlib
import importlib.util
import io
import json
import os
import struct
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock
import zipfile

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/package_release.py"
SPEC = importlib.util.spec_from_file_location("package_release", SCRIPT)
packaging = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(packaging)
COMMIT = "0123456789abcdef0123456789abcdef01234567"


class ReleasePackagingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="camera-release-test-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "source"
        self.root.mkdir()
        (self.root / "LICENSE").write_bytes(b"Fixture MIT license\n")
        (self.root / "catalog").mkdir()
        (self.root / "catalog/cameras.json").write_text(json.dumps(dict(cameras=[dict(id="testcam"), dict(id="secondcam")])))
        self.models = [self.make_model(model_id) for model_id in ("testcam", "secondcam")]

    def make_model(self, model_id):
        model = self.root / "models" / model_id
        for directory in ("config", "assets/meshes/visual", "assets/meshes/collision", "urdf", "mjcf", "docs", "preview", "assets/textures"):
            (model / directory).mkdir(parents=True, exist_ok=True)
        metadata = dict(visual=f"assets/meshes/{model_id}_visual.glb", config=f"config/{model_id}.json",
                        urdf=f"urdf/{model_id}.urdf", mjcf=f"mjcf/{model_id}.xml", sensor_manifest="config/sensors.json")
        (model / "model.json").write_text(json.dumps(metadata))
        (model / f"config/{model_id}.json").write_text('{"mass_kg":0.1}\n')
        (model / "config/sensors.json").write_text('{"status":"uncalibrated"}\n')
        (model / "docs/validation.json").write_text('{"status":"PASS"}\n')
        document = json.dumps(dict(asset=dict(version="2.0"), buffers=[dict(byteLength=0)])).encode()
        document += b" " * (-len(document) % 4)
        (model / metadata["visual"]).write_bytes(struct.pack("<4sIIII", b"glTF", 2, 20+len(document), len(document), 0x4e4f534a) + document)
        (model / f"assets/meshes/{model_id}_visual.obj").write_text(f"mtllib {model_id}_visual.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
        (model / f"assets/meshes/{model_id}_visual.mtl").write_text("newmtl fixture\nKd 0.5 0.5 0.5\n")
        (model / "assets/meshes/visual/body.obj").write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
        (model / "assets/meshes/collision/body.stl").write_bytes(b"fixture collision bytes")
        (model / "assets/visual_manifest.json").write_text('[{"file":"../assets/meshes/visual/body.obj"}]\n')
        (model / metadata["urdf"]).write_text('<robot name="fixture"><link name="fixture"><visual><geometry><mesh filename="../assets/meshes/visual/body.obj"/></geometry></visual><collision><geometry><mesh filename="../assets/meshes/collision/body.stl"/></geometry></collision></link></robot>')
        (model / metadata["mjcf"]).write_text('<mujoco><asset><mesh name="body" file="../assets/meshes/visual/body.obj"/></asset><worldbody><body><geom type="mesh" mesh="body"/></body></worldbody></mujoco>')
        for relative in ("preview/studio_hero.png", "assets/source.blend", "assets/textures/normal.png", "assets/meshes/scratch.obj.tmp", "config/calibration.json~", "mjcf/.DS_Store"):
            (model / relative).write_bytes(b"excluded")
        return model

    def build(self, name="release", **kwargs):
        return packaging.build_release(self.root, self.base / name, "v0.1.0", source_commit=COMMIT, **kwargs)

    def test_deterministic_archives_manifest_checksums_and_roundtrip(self):
        first = self.build("first")
        # Filesystem mtimes and modes must not change archive bytes.
        for model in self.models:
            for path in model.rglob("*"):
                if path.is_file():
                    os.utime(path, (1234567890, 1234567890))
                    path.chmod(0o600)
        second = self.build("second", model_ids=["secondcam", "testcam"])
        self.assertEqual(first, second)
        expected_top = {"testcam-v0.1.0.zip", "secondcam-v0.1.0.zip", "manifest.json", "SHA256SUMS"}
        self.assertEqual({path.name for path in (self.base / "first").iterdir()}, expected_top)
        for name in expected_top:
            self.assertEqual((self.base / "first" / name).read_bytes(), (self.base / "second" / name).read_bytes())
        self.assertEqual(first["source_commit"], COMMIT)
        self.assertEqual(first["repository"], "TToTMooN/camera-assets")
        for model_id, entry in first["models"].items():
            archive_path = self.base / "first" / entry["archive"]
            self.assertEqual(entry["sha256"], hashlib.sha256(archive_path.read_bytes()).hexdigest())
            self.assertEqual(entry["size_bytes"], archive_path.stat().st_size)
            with zipfile.ZipFile(archive_path) as archive:
                self.assertEqual(archive.namelist(), sorted(archive.namelist()))
                expected_files = {"LICENSE", "model.json", f"config/{model_id}.json", "config/sensors.json",
                                  f"assets/meshes/{model_id}_visual.glb", f"assets/meshes/{model_id}_visual.obj",
                                  f"assets/meshes/{model_id}_visual.mtl", "assets/meshes/visual/body.obj",
                                  "assets/meshes/collision/body.stl", "assets/visual_manifest.json",
                                  f"urdf/{model_id}.urdf", f"mjcf/{model_id}.xml", "docs/validation.json"}
                self.assertEqual(set(entry["files"]), expected_files)
                self.assertEqual(set(archive.namelist()), {f"models/{model_id}/{relative}" for relative in expected_files})
                for info in archive.infolist():
                    self.assertFalse(info.is_dir())
                    self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0))
                    self.assertEqual(info.external_attr >> 16, 0o100644)
                    self.assertEqual(info.compress_type, zipfile.ZIP_DEFLATED)
                    relative = info.filename.removeprefix(f"models/{model_id}/")
                    data = archive.read(info)
                    original = self.root / "LICENSE" if relative == "LICENSE" else self.root / "models" / model_id / relative
                    self.assertEqual(data, original.read_bytes())
                    self.assertEqual(entry["files"][relative], dict(sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data)))
                self.assertEqual(entry["unpacked_size_bytes"], sum(info.file_size for info in archive.infolist()))
                archive.extractall(self.base / "unpacked")
            restored = self.base / "unpacked/models" / model_id
            # References remain valid after moving the archive to another tree.
            packaging.validate_dependencies(restored, packaging.model_files(self.base / "unpacked", model_id))
        checksums = dict(line.split("  ", 1)[::-1] for line in (self.base / "first/SHA256SUMS").read_text().splitlines())
        self.assertEqual(set(checksums), expected_top - {"SHA256SUMS"})
        for name, digest in checksums.items():
            self.assertEqual(digest, hashlib.sha256((self.base / "first" / name).read_bytes()).hexdigest())

    def test_select_one_model_and_normalize_version(self):
        result = packaging.build_release(self.root, self.base / "single", "0.1.0", model_ids="testcam", source_commit=COMMIT)
        self.assertEqual(result["version"], "v0.1.0")
        self.assertEqual(list(result["models"]), ["testcam"])

    def test_reject_unsafe_version_ids_and_source_commit(self):
        for version in ("latest", "v01.0.0", "v0.1.0-rc1", "../../bad", "0.1", "v0.1.0+build"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                packaging.build_release(self.root, self.base / "bad", version, source_commit=COMMIT)
        for model_id in ("../testcam", "/testcam", "bad\\name", "X5", "missing"):
            with self.subTest(model=model_id), self.assertRaises(ValueError):
                self.build(model_ids=[model_id])
        for source_commit in ("abc", "g"*40, None):
            with self.subTest(commit=source_commit), self.assertRaises(ValueError):
                packaging.build_release(self.root, self.base / "bad", "v0.1.0", source_commit=source_commit)
        with self.assertRaises(ValueError):
            self.build(model_ids=["testcam", "testcam"])

    def test_reject_existing_output_and_output_inside_models(self):
        output = self.base / "occupied"
        output.mkdir()
        marker = output / "manifest.json"
        marker.write_bytes(b"must remain")
        with self.assertRaises(FileExistsError):
            packaging.build_release(self.root, output, "v0.1.0", source_commit=COMMIT)
        self.assertEqual(marker.read_bytes(), b"must remain")
        empty = self.base / "empty"
        empty.mkdir()
        with self.assertRaises(FileExistsError):
            packaging.build_release(self.root, empty, "v0.1.0", source_commit=COMMIT)
        with self.assertRaises(ValueError):
            packaging.build_release(self.root, self.models[0] / "release", "v0.1.0", source_commit=COMMIT)

    def test_missing_mesh_and_metadata_dependency_publish_nothing(self):
        (self.models[0] / "assets/meshes/visual/body.obj").unlink()
        with self.assertRaises(FileNotFoundError):
            self.build()
        self.assertFalse((self.base / "release").exists())
        self.assertFalse(list(self.base.glob(".release-*")))
        metadata = self.models[1] / "model.json"
        data = json.loads(metadata.read_text())
        data["sensor_manifest"] = "config/missing.json"
        metadata.write_text(json.dumps(data))
        with self.assertRaises(FileNotFoundError):
            self.build(model_ids=["secondcam"])

    def test_reject_escape_and_excluded_dependencies(self):
        urdf = self.models[0] / "urdf/testcam.urdf"
        original = urdf.read_text()
        for reference in ("../../../LICENSE", "/absolute.obj", "package://foreign/body.obj", "..\\assets\\body.obj"):
            with self.subTest(reference=reference):
                urdf.write_text(original.replace("../assets/meshes/visual/body.obj", reference))
                with self.assertRaises(ValueError):
                    self.build()
        urdf.write_text(original.replace("../assets/meshes/visual/body.obj", "../assets/textures/normal.png"))
        with self.assertRaisesRegex(ValueError, "excluded"):
            self.build()

    def test_reject_symlink_inputs(self):
        # Keep path-escape coverage independent of Windows symlink privileges.
        link = self.models[0] / "assets/meshes/linked.obj"
        try:
            link.symlink_to(self.models[0] / "assets/meshes/visual/body.obj")
        except OSError as error:
            if os.name == "nt" and (getattr(error, "winerror", None) == 1314 or error.errno in (errno.EPERM, errno.EACCES, errno.ENOTSUP)):
                self.skipTest("Windows fixture cannot create symlinks without permission")
            raise
        with self.assertRaisesRegex(ValueError, "Symlinks"):
            self.build()

    def test_invalid_catalog_id_is_rejected_before_directory_lookup(self):
        (self.root / "catalog/cameras.json").write_text('{"cameras":[{"id":"../testcam"}]}')
        with self.assertRaisesRegex(ValueError, "Unsafe model"):
            self.build()

    def initialize_git(self):
        for arguments in (["init", "-q"], ["config", "user.name", "Release fixture"], ["config", "user.email", "fixture@example.invalid"], ["add", "."], ["commit", "-qm", "Fixture"]):
            subprocess.run(["git", "-C", str(self.root), *arguments], check=True, capture_output=True)

    def test_git_head_and_dirty_tracked_or_untracked_source(self):
        self.initialize_git()
        result = packaging.build_release(self.root, self.base / "clean", "v0.1.0", model_ids=["testcam"])
        expected = subprocess.check_output(["git", "-C", str(self.root), "rev-parse", "HEAD"], text=True).strip()
        self.assertEqual(result["source_commit"], expected)
        license_path = self.root / "LICENSE"
        original = license_path.read_bytes()
        license_path.write_bytes(original + b"dirty")
        with self.assertRaisesRegex(ValueError, "tracked changes"):
            packaging.build_release(self.root, self.base / "dirty", "v0.1.0")
        license_path.write_bytes(original)
        (self.root / "untracked.txt").write_text("dirty")
        with self.assertRaisesRegex(ValueError, "untracked"):
            packaging.build_release(self.root, self.base / "untracked", "v0.1.0")

    def test_clean_git_rejects_ignored_runtime_files_but_fixture_override_is_explicit(self):
        (self.root / ".gitignore").write_text("*.zip\nmodels/testcam/preview/ignored.png\n", encoding="utf-8")
        self.initialize_git()
        scratch = self.models[0] / "assets/meshes/private.zip"
        scratch.write_bytes(b"must not silently be released")
        dirty = subprocess.check_output(["git", "-C", str(self.root), "status", "--porcelain=v1", "--untracked-files=all"])
        self.assertEqual(dirty, b"")
        with self.assertRaisesRegex(ValueError, "Git-tracked.*private.zip"):
            packaging.build_release(self.root, self.base / "ignored", "v0.1.0", model_ids="testcam")
        self.assertFalse((self.base / "ignored").exists())
        self.assertFalse(list(self.base.glob(".ignored-*")))
        result = self.build("fixture-override", model_ids="testcam")
        self.assertIn("assets/meshes/private.zip", result["models"]["testcam"]["files"])
        scratch.unlink()
        # Ignored preview files are outside the runtime allowlist.
        (self.models[0] / "preview/ignored.png").write_bytes(b"ignored preview")
        packaging.build_release(self.root, self.base / "excluded-preview", "v0.1.0", model_ids="testcam")

    def test_git_requires_tracked_catalog_license_and_selected_runtime_inputs(self):
        (self.root / ".gitignore").write_text("", encoding="utf-8")
        self.initialize_git()
        for relative in ("catalog/cameras.json", "LICENSE", "models/testcam/config/sensors.json"):
            with self.subTest(relative=relative):
                subprocess.run(["git", "-C", str(self.root), "rm", "--cached", relative], check=True, capture_output=True)
                with (self.root / ".gitignore").open("a", encoding="utf-8") as ignored:
                    ignored.write(relative + "\n")
                subprocess.run(["git", "-C", str(self.root), "add", ".gitignore"], check=True, capture_output=True)
                subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "Ignore fixture input"], check=True, capture_output=True)
                with self.assertRaisesRegex(ValueError, "Git-tracked"):
                    packaging.build_release(self.root, self.base / "untracked-input", "v0.1.0", model_ids="testcam")
                self.assertFalse((self.base / "untracked-input").exists())
                subprocess.run(["git", "-C", str(self.root), "add", "-f", relative], check=True, capture_output=True)
                subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "Restore fixture input"], check=True, capture_output=True)

    def test_late_empty_destination_is_preserved_and_staging_is_removed(self):
        original_publish = packaging.publish_no_replace
        identity = None

        def competing_destination(staging, output):
            nonlocal identity
            output.mkdir()
            identity = (output.stat().st_dev, output.stat().st_ino)
            original_publish(staging, output)

        with mock.patch.object(packaging, "publish_no_replace", side_effect=competing_destination):
            with self.assertRaises(FileExistsError):
                self.build()
        output = self.base / "release"
        self.assertTrue(output.is_dir())
        self.assertEqual((output.stat().st_dev, output.stat().st_ino), identity)
        self.assertEqual(list(output.iterdir()), [])
        self.assertFalse(list(self.base.glob(".release-*")))

    def test_missing_exclusive_rename_primitive_fails_without_fallback(self):
        with mock.patch.object(packaging.sys, "platform", "linux"), mock.patch.object(packaging.ctypes, "CDLL", return_value=object()), mock.patch.object(packaging.os, "rename") as unsafe_rename:
            with self.assertRaisesRegex(OSError, "requires renameat2"):
                self.build()
            unsafe_rename.assert_not_called()
        self.assertFalse((self.base / "release").exists())
        self.assertFalse(list(self.base.glob(".release-*")))
        with mock.patch.object(packaging.sys, "platform", "unsupported"), mock.patch.object(packaging.os, "rename") as unsafe_rename:
            with self.assertRaisesRegex(OSError, "unsupported"):
                self.build()
            unsafe_rename.assert_not_called()
        self.assertFalse((self.base / "release").exists())
        self.assertFalse(list(self.base.glob(".release-*")))

    def test_write_failure_never_publishes_partial_release(self):
        with mock.patch.object(packaging.zipfile.ZipFile, "writestr", side_effect=OSError("fixture disk failure")):
            with self.assertRaisesRegex(OSError, "disk failure"):
                self.build()
        self.assertFalse((self.base / "release").exists())
        self.assertFalse(list(self.base.glob(".release-*")))

    def make_sdk(self, version="0.1.0", embedded_version=None):
        directory = self.base / "sdk"
        directory.mkdir(exist_ok=True)
        metadata = f"Metadata-Version: 2.1\nName: camera-assets\nVersion: {embedded_version or version}\n\n".encode()
        with zipfile.ZipFile(directory / f"camera_assets-{version}-py3-none-any.whl", "w") as archive:
            archive.writestr(f"camera_assets-{version}.dist-info/METADATA", metadata)
        with tarfile.open(directory / f"camera_assets-{version}.tar.gz", "w:gz") as archive:
            member = tarfile.TarInfo(f"camera_assets-{version}/PKG-INFO")
            member.size = len(metadata)
            archive.addfile(member, io.BytesIO(metadata))
        return directory

    def test_sdk_artifacts_are_copied_and_checksummed_outside_model_manifest(self):
        sdk = self.make_sdk()
        result = self.build(sdk_dist=sdk)
        checksums = (self.base / "release/SHA256SUMS").read_text()
        for source in sdk.iterdir():
            self.assertEqual(source.read_bytes(), (self.base / "release" / source.name).read_bytes())
            self.assertIn(f"{hashlib.sha256(source.read_bytes()).hexdigest()}  {source.name}\n", checksums)
        self.assertEqual(set(result), {"schema_version", "version", "repository", "source_commit", "models"})

    def test_reject_sdk_filename_and_embedded_version_drift(self):
        sdk = self.make_sdk("0.2.0")
        with self.assertRaisesRegex(ValueError, "filename"):
            self.build(sdk_dist=sdk)
        for file in sdk.iterdir():
            file.unlink()
        self.make_sdk(embedded_version="0.2.0")
        with self.assertRaisesRegex(ValueError, "metadata"):
            self.build(sdk_dist=sdk)
        self.assertFalse((self.base / "release").exists())


if __name__ == "__main__":
    unittest.main()
