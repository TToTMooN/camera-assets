"""Consume every built model through the SDK before publishing a release."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import sys
import tempfile
import threading
from unittest.mock import patch
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from camera_assets import fetch, get_model
from camera_assets.release_spec import normalize_version


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def verify(directory, version, compile_mjcf=False):
    version = normalize_version(version)
    published = {path.name: path for path in directory.iterdir() if path.is_file()}
    expected = {}
    for line in (directory / "SHA256SUMS").read_text(encoding="ascii").splitlines():
        checksum, name = line.split("  ", 1)
        if name in expected or name not in published or Path(name).name != name:
            raise ValueError("Invalid or duplicate release checksum filename")
        expected[name] = checksum
    if set(expected) != set(published) - {"SHA256SUMS"}:
        raise ValueError("Release checksum file coverage differs from published artifacts")
    for name, checksum in expected.items():
        if digest(published[name]) != checksum:
            raise ValueError(f"Release checksum mismatch: {name}")
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest["version"] != version:
        raise ValueError("Release manifest version differs from requested version")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            prefix = f"/{version}/"
            name = self.path[len(prefix):] if self.path.startswith(prefix) else ""
            if name not in published:
                self.send_error(404)
                return
            path = published[name]
            self.send_response(200)
            self.send_header("Content-Length", str(path.stat().st_size))
            self.end_headers()
            with path.open("rb") as source:
                shutil.copyfileobj(source, self.wfile)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="camera-assets-roundtrip-") as cache:
            base_url = f"http://127.0.0.1:{server.server_port}"
            opener = build_opener(ProxyHandler({}))
            for model_id in sorted(manifest["models"]):
                with patch("camera_assets.api.urlopen", side_effect=opener.open):
                    downloaded = fetch(model_id, version=version, cache_dir=cache, base_url=base_url)
                with patch("camera_assets.api.urlopen", side_effect=AssertionError("Offline lookup contacted the network")):
                    model = get_model(model_id, version=version, cache_dir=cache)
                if model.directory != downloaded.directory:
                    raise ValueError("Offline lookup changed the downloaded model")
                if compile_mjcf:
                    import mujoco
                    mujoco.MjModel.from_xml_path(str(model.mjcf))
                print(f"{model_id}: release download, integrity, and offline paths PASS", flush=True)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    print(f"{len(manifest['models'])} release models PASS")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--compile-mjcf", action="store_true")
    args = parser.parse_args()
    try:
        verify(args.directory, args.version, args.compile_mjcf)
    except (OSError, ValueError, KeyError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
