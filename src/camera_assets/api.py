"""Resolve local camera assets and explicitly fetch verified release archives.

The installed Python package is small. Downloaded models live in a shared cache,
and get_model never performs network I/O. Release cache contents are immutable;
keep project-specific calibration in a separate local library checkout.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
from importlib import resources
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tempfile
import time
from typing import Any, Iterator
from urllib.parse import urlsplit
from urllib.request import urlopen
import zipfile

from .release_spec import (
    RELEASE_BASE_URL,
    REPOSITORY,
    SCHEMA_VERSION,
    normalize_version,
    validate_model_id,
)

_CHUNK_SIZE = 1024 * 1024
_MANIFEST_LIMIT = 8 * 1024 * 1024
_ARCHIVE_LIMIT = 2 * 1024**3
_UNPACKED_LIMIT = 8 * 1024**3
_FILE_COUNT_LIMIT = 100_000
_SHA256 = re.compile(r"[0-9a-fA-F]{64}")


class AssetError(ValueError):
    """An unavailable, invalid or unverifiable camera asset."""


@dataclass(frozen=True)
class CameraModel:
    id: str
    version: str | None
    directory: Path
    metadata: dict[str, Any]
    urdf: Path
    mjcf: Path
    visual: Path
    sensor_manifest: Path

    @property
    def model_json(self) -> Path:
        return self.directory / "model.json"


def default_cache_dir() -> Path:
    """Use the user's shared platform cache, rather than a virtual environment."""
    override = os.environ.get("CAMERA_ASSETS_CACHE")
    if override:
        return _absolute_path(override, "CAMERA_ASSETS_CACHE")
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Caches"
    else:
        configured = os.environ.get("XDG_CACHE_HOME")
        base = Path(configured) if configured and Path(configured).is_absolute() else Path.home() / ".cache"
    return _absolute_path(base / "camera-assets", "Default asset cache")


def list_models() -> list[str]:
    """List the model IDs in this client's bundled catalog, without network I/O."""
    try:
        text = resources.files("camera_assets").joinpath("catalog.json").read_text(encoding="utf-8")
        catalog = _parse_json(text, "Bundled catalog")
        entries = catalog["cameras"]
        if not isinstance(entries, list):
            raise AssetError("Bundled catalog cameras must be a list")
        ids = [validate_model_id(entry["id"]) for entry in entries]
        if len(set(ids)) != len(ids):
            raise AssetError("Bundled catalog contains duplicate model IDs")
        return sorted(ids)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, AssetError):
            raise
        raise AssetError(f"Cannot read bundled catalog: {exc}") from exc


def _parse_json(data: str | bytes, description: str) -> dict[str, Any]:
    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise AssetError(f"{description} contains duplicate JSON key {key!r}")
            result[key] = value
        return result

    try:
        parsed = json.loads(data, object_pairs_hook=unique_pairs)
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, AssetError):
            raise
        raise AssetError(f"{description} is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise AssetError(f"{description} must be a JSON object")
    return parsed


def _relative_path(value: Any, description: str) -> PurePosixPath:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 1024
        or "\\" in value
        or ":" in value
        or "\x00" in value
        or any(part in ("", ".", "..") for part in value.split("/"))
    ):
        raise AssetError(f"{description} must be a safe relative POSIX file path")
    path = PurePosixPath(value)
    if path.is_absolute():
        raise AssetError(f"{description} must remain inside its model directory")
    return path


def _integer(value: Any, description: str, *, maximum: int | None = None) -> int:
    if type(value) is not int or value < 0 or (maximum is not None and value > maximum):
        raise AssetError(f"{description} must be a nonnegative integer within supported bounds")
    return value


def _digest(value: Any, description: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise AssetError(f"{description} must be a SHA256 digest")
    return value.lower()


def _manifest(data: str | bytes, version: str) -> dict[str, Any]:
    manifest = _parse_json(data, "Release manifest")
    if type(manifest.get("schema_version")) is not int or manifest["schema_version"] != SCHEMA_VERSION:
        raise AssetError("Unsupported release manifest schema_version")
    if manifest.get("version") != version:
        raise AssetError(f"Release manifest version does not match {version}")
    if manifest.get("repository") != REPOSITORY:
        raise AssetError(f"Release manifest repository must be {REPOSITORY}")
    commit = manifest.get("source_commit")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
        raise AssetError("Release manifest must record a full source_commit")
    models = manifest.get("models")
    if not isinstance(models, dict) or not models:
        raise AssetError("Release manifest must contain models")
    for model_id, entry in models.items():
        try:
            validate_model_id(model_id)
        except ValueError as exc:
            raise AssetError(f"Invalid manifest model ID: {model_id!r}") from exc
        if not isinstance(entry, dict):
            raise AssetError(f"Manifest entry for {model_id} must be an object")
        if entry.get("archive") != f"{model_id}-{version}.zip":
            raise AssetError(f"Unexpected archive filename for {model_id}")
        _digest(entry.get("sha256"), f"{model_id} archive sha256")
        _integer(entry.get("size_bytes"), f"{model_id} archive size", maximum=_ARCHIVE_LIMIT)
        unpacked = _integer(entry.get("unpacked_size_bytes"), f"{model_id} unpacked size", maximum=_UNPACKED_LIMIT)
        files = entry.get("files")
        if not isinstance(files, dict) or not files or len(files) > _FILE_COUNT_LIMIT:
            raise AssetError(f"{model_id} manifest must enumerate its files")
        if not {"model.json", "LICENSE"}.issubset(files):
            raise AssetError(f"{model_id} archive must contain model.json and LICENSE")
        total = 0
        for relative, record in files.items():
            _relative_path(relative, f"{model_id} manifest filename")
            if not isinstance(record, dict):
                raise AssetError(f"Manifest file record for {relative} must be an object")
            _digest(record.get("sha256"), f"{relative} sha256")
            total += _integer(record.get("size_bytes"), f"{relative} file size", maximum=_UNPACKED_LIMIT)
        if total != unpacked:
            raise AssetError(f"{model_id} unpacked_size_bytes does not equal its file sizes")
    return manifest


def _id(value: str) -> str:
    try:
        return validate_model_id(value)
    except ValueError as exc:
        raise AssetError(str(exc)) from exc


def _version(value: str | None) -> str:
    try:
        return normalize_version(value)  # type: ignore[arg-type]
    except ValueError as exc:
        raise AssetError(str(exc)) from exc


def _absolute_path(value: str | os.PathLike[str], description: str) -> Path:
    try:
        return Path(value).expanduser().resolve()
    except (OSError, ValueError, RuntimeError) as exc:
        raise AssetError(f"Cannot resolve {description}: {exc}") from exc


def _cache_root(cache_dir: str | os.PathLike[str] | None) -> Path:
    return _absolute_path(cache_dir, "Asset cache directory") if cache_dir is not None else default_cache_dir()


def _exists(path: Path) -> bool:
    return os.path.lexists(path)


def _plain_directory(path: Path, description: str) -> None:
    if path.is_symlink() or not path.is_dir():
        raise AssetError(f"{description} must be a directory, not a symlink: {path}")


def _read_manifest(path: Path, version: str) -> dict[str, Any]:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > _MANIFEST_LIMIT:
            raise AssetError(f"Cached manifest is missing or invalid: {path}")
        return _manifest(path.read_bytes(), version)
    except OSError as exc:
        raise AssetError(f"Cannot read cached manifest {path}: {exc}") from exc


def _entry(manifest: dict[str, Any], model_id: str) -> dict[str, Any]:
    try:
        return manifest["models"][model_id]
    except KeyError as exc:
        raise AssetError(f"Model {model_id!r} is absent from release {manifest['version']}") from exc


def _file_path(directory: Path, relative: Any, description: str) -> Path:
    path = directory.joinpath(*_relative_path(relative, description).parts)
    try:
        # Reject symlinks even when they currently resolve inside the directory.
        ancestor = path
        while ancestor != directory:
            if ancestor.is_symlink():
                raise AssetError(f"{description} cannot refer through a symlink: {path}")
            ancestor = ancestor.parent
        if not path.resolve().is_relative_to(directory.resolve()) or not path.is_file():
            raise AssetError(f"{description} must resolve to an existing file inside {directory}")
    except OSError as exc:
        raise AssetError(f"Cannot resolve {description}: {exc}") from exc
    return path


def _camera(directory: Path, model_id: str, version: str | None) -> CameraModel:
    _plain_directory(directory, "Model directory")
    metadata_path = _file_path(directory, "model.json", "Model metadata")
    try:
        if metadata_path.stat().st_size > _MANIFEST_LIMIT:
            raise AssetError("model.json is unexpectedly large")
        metadata = _parse_json(metadata_path.read_bytes(), "Model metadata")
    except OSError as exc:
        raise AssetError(f"Cannot read model metadata: {exc}") from exc
    if "id" in metadata and metadata["id"] != model_id:
        raise AssetError(f"Model metadata ID does not match {model_id}")
    paths = {
        key: _file_path(directory, metadata.get(key), f"Model {key}")
        for key in ("urdf", "mjcf", "visual", "sensor_manifest")
    }
    if "config" in metadata:
        _file_path(directory, metadata["config"], "Model config")
    return CameraModel(model_id, version, directory, metadata, **paths)


def _verify_files(directory: Path, entry: dict[str, Any]) -> None:
    _plain_directory(directory, "Cached model directory")
    actual: set[str] = set()
    try:
        for current, dirs, files in os.walk(directory, followlinks=False):
            for name in dirs:
                if (Path(current) / name).is_symlink():
                    raise AssetError(f"Cached model contains a directory symlink: {name}")
            for name in files:
                path = Path(current) / name
                if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
                    raise AssetError(f"Cached model contains a nonregular file: {path}")
                actual.add(path.relative_to(directory).as_posix())
        expected = entry["files"]
        if actual != set(expected):
            missing = sorted(set(expected) - actual)
            extra = sorted(actual - set(expected))
            raise AssetError(f"Cached model file set differs from manifest (missing={missing[:3]}, extra={extra[:3]})")
        for relative, record in expected.items():
            path = _file_path(directory, relative, "Cached model file")
            if path.stat().st_size != record["size_bytes"]:
                raise AssetError(f"Cached file size mismatch: {relative}")
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(_CHUNK_SIZE), b""):
                    digest.update(chunk)
            if digest.hexdigest() != record["sha256"].lower():
                raise AssetError(f"Cached file SHA256 mismatch: {relative}")
    except OSError as exc:
        raise AssetError(f"Cannot verify cached model {directory}: {exc}") from exc


def _cached_model(library: Path, model_id: str, version: str, manifest: dict[str, Any]) -> CameraModel:
    entry = _entry(manifest, model_id)
    models = library / "models"
    if _exists(models):
        _plain_directory(models, "Cached models directory")
    directory = models / model_id
    if not _exists(directory):
        raise AssetError(f"Model {model_id!r} at {version} is not cached; call fetch({model_id!r}, version={version!r}) first")
    _verify_files(directory, entry)
    return _camera(directory, model_id, version)


def get_model(
    id: str,
    *,
    version: str | None = None,
    root: str | os.PathLike[str] | None = None,
    cache_dir: str | os.PathLike[str] | None = None,
) -> CameraModel:
    """Resolve an existing model strictly offline.

    ``root`` is a library checkout containing ``models/<id>``. A normal local
    checkout has no verified release version. Supplying ``version`` with a local
    root requires that root's release manifest and matching file checksums.
    Without ``root``, an explicit cached release version is required.
    """
    model_id = _id(id)
    if root is not None:
        library = _absolute_path(root, "Local library root")
        _plain_directory(library / "models", "Local models directory")
        if version is None:
            return _camera(library / "models" / model_id, model_id, None)
        pinned = _version(version)
        manifest = _read_manifest(library / "manifest.json", pinned)
        return _cached_model(library, model_id, pinned, manifest)
    pinned = _version(version)
    library = _cache_root(cache_dir) / pinned
    if not _exists(library):
        raise AssetError(f"Release {pinned} is not cached; call fetch({model_id!r}, version={pinned!r}) first")
    _plain_directory(library, "Cached release directory")
    manifest = _read_manifest(library / "manifest.json", pinned)
    return _cached_model(library, model_id, pinned, manifest)


def _download(url: str, destination: Path, *, limit: int, expected_size: int | None = None) -> str:
    digest = hashlib.sha256()
    count = 0
    try:
        with urlopen(url, timeout=30) as response, destination.open("xb") as output:
            while True:
                chunk = response.read(min(_CHUNK_SIZE, limit - count + 1))
                if not chunk:
                    break
                count += len(chunk)
                if count > limit:
                    raise AssetError(f"Download exceeds its declared size limit: {url}")
                output.write(chunk)
                digest.update(chunk)
    except Exception as exc:
        if isinstance(exc, AssetError):
            raise
        raise AssetError(f"Cannot download {url}: {exc}") from exc
    if expected_size is not None and count != expected_size:
        raise AssetError(f"Download size mismatch for {url}: expected {expected_size}, received {count}")
    return digest.hexdigest()


def _release_url(base_url: str, version: str) -> str:
    if not isinstance(base_url, str):
        raise AssetError("Release base URL must be an HTTP(S) URL")
    try:
        parsed = urlsplit(base_url)
    except ValueError as exc:
        raise AssetError(f"Invalid release base URL: {exc}") from exc
    if (
        parsed.scheme not in ("http", "https") or not parsed.netloc
        or parsed.query or parsed.fragment
        or parsed.username is not None or parsed.password is not None
    ):
        raise AssetError("Release base URL must be an HTTP(S) URL without credentials, query or fragment")
    return f"{base_url.rstrip('/')}/{version}"


def _fetch_manifest(library: Path, version: str, release_url: str) -> dict[str, Any]:
    path = library / "manifest.json"
    if _exists(path):
        return _read_manifest(path, version)
    with tempfile.TemporaryDirectory(prefix=".manifest-", dir=library) as temporary:
        staged = Path(temporary) / "manifest.json"
        _download(f"{release_url}/manifest.json", staged, limit=_MANIFEST_LIMIT)
        manifest = _manifest(staged.read_bytes(), version)
        with _publication_lock(library, "_manifest"):
            if _exists(path):
                winner = _read_manifest(path, version)
                if winner != manifest:
                    raise AssetError(f"A different manifest snapshot already exists for {version}")
                return winner
            try:
                os.rename(staged, path)
            except OSError as exc:
                raise AssetError(f"Cannot publish release manifest: {exc}") from exc
        return manifest


def _extract(archive: Path, staging: Path, model_id: str, entry: dict[str, Any]) -> Path:
    prefix = f"models/{model_id}/"
    expected = entry["files"]
    try:
        with zipfile.ZipFile(archive) as zipped:
            infos = zipped.infolist()
            if len(infos) != len(expected):
                raise AssetError("Archive member count differs from manifest")
            seen: set[str] = set()
            for info in infos:
                mode = info.external_attr >> 16
                if info.orig_filename != info.filename:
                    raise AssetError("Archive contains a truncated or normalized member name")
                if info.is_dir() or stat.S_IFMT(mode) not in (0, stat.S_IFREG) or info.flag_bits & 1:
                    raise AssetError(f"Archive contains a directory, symlink, special or encrypted entry: {info.filename}")
                if not info.filename.startswith(prefix):
                    raise AssetError(f"Archive member is outside models/{model_id}: {info.filename}")
                relative = info.filename[len(prefix):]
                _relative_path(relative, "Archive member")
                if relative in seen:
                    raise AssetError(f"Archive contains duplicate member: {relative}")
                seen.add(relative)
                if relative not in expected or info.file_size != expected[relative]["size_bytes"]:
                    raise AssetError(f"Archive member is extra or has an unexpected size: {relative}")
            if seen != set(expected):
                raise AssetError("Archive file set differs from manifest")
            directory = staging / "models" / model_id
            directory.mkdir(parents=True)
            for info in infos:
                relative = info.filename[len(prefix):]
                record = expected[relative]
                path = directory.joinpath(*PurePosixPath(relative).parts)
                path.parent.mkdir(parents=True, exist_ok=True)
                count = 0
                digest = hashlib.sha256()
                with zipped.open(info) as source, path.open("xb") as output:
                    while True:
                        chunk = source.read(min(_CHUNK_SIZE, record["size_bytes"] - count + 1))
                        if not chunk:
                            break
                        count += len(chunk)
                        if count > record["size_bytes"]:
                            raise AssetError(f"Archive member exceeds expected size: {relative}")
                        output.write(chunk)
                        digest.update(chunk)
                if count != record["size_bytes"] or digest.hexdigest() != record["sha256"].lower():
                    raise AssetError(f"Archive member checksum or size mismatch: {relative}")
            return directory
    except (OSError, ValueError, RuntimeError, EOFError, zipfile.BadZipFile, NotImplementedError) as exc:
        if isinstance(exc, AssetError):
            raise
        raise AssetError(f"Cannot safely extract archive: {exc}") from exc


@contextmanager
def _publication_lock(library: Path, model_id: str) -> Iterator[None]:
    """Serialize only the final directory publication, not model downloads."""
    lock = library / f".{model_id}.publish-lock"
    deadline = time.monotonic() + 10
    while True:
        try:
            lock.mkdir()
            break
        except FileExistsError:
            if lock.is_symlink() or not lock.is_dir() or time.monotonic() >= deadline:
                raise AssetError(f"Model publication is busy or its lock is invalid: {lock}")
            time.sleep(0.02)
        except OSError as exc:
            raise AssetError(f"Cannot lock model publication: {exc}") from exc
    try:
        yield
    finally:
        try:
            lock.rmdir()
        except OSError:
            pass


def fetch(
    id: str,
    *,
    version: str,
    cache_dir: str | os.PathLike[str] | None = None,
    base_url: str = RELEASE_BASE_URL,
) -> CameraModel:
    """Explicitly download a pinned model, verify it and publish it atomically.

    A valid cached model is reused without network I/O. Existing corrupt models
    are never repaired or overwritten automatically, including sensor files.
    """
    model_id = _id(id)
    pinned = _version(version)
    cache = _cache_root(cache_dir)
    library = cache / pinned
    target = library / "models" / model_id
    try:
        if _exists(target):
            return get_model(model_id, version=pinned, cache_dir=cache)
        release_url = _release_url(base_url, pinned)
        library.mkdir(parents=True, exist_ok=True)
        _plain_directory(library, "Cached release directory")
        manifest = _fetch_manifest(library, pinned, release_url)
        entry = _entry(manifest, model_id)
        models = library / "models"
        models.mkdir(exist_ok=True)
        _plain_directory(models, "Cached models directory")
        # Another fetch might have completed while the manifest was being read.
        if _exists(target):
            return _cached_model(library, model_id, pinned, manifest)
        with tempfile.TemporaryDirectory(prefix=f".{model_id}-", dir=library) as temporary:
            staging = Path(temporary)
            archive = staging / entry["archive"]
            checksum = _download(
                f"{release_url}/{entry['archive']}", archive,
                limit=entry["size_bytes"], expected_size=entry["size_bytes"],
            )
            if checksum != entry["sha256"].lower():
                raise AssetError(f"Archive SHA256 mismatch for {model_id}")
            staged_model = _extract(archive, staging, model_id, entry)
            _camera(staged_model, model_id, pinned)
            with _publication_lock(library, model_id):
                if not _exists(target):
                    os.rename(staged_model, target)
            return _cached_model(library, model_id, pinned, manifest)
    except OSError as exc:
        raise AssetError(f"Cannot access asset cache {cache}: {exc}") from exc
