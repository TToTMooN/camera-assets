"""Command-line access to camera assets."""

from __future__ import annotations

import argparse
import sys

from .api import AssetError, fetch, get_model, list_models
from .release_spec import RELEASE_BASE_URL


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="camera-assets", description="Fetch pinned camera models or resolve local assets offline.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="List bundled catalog model IDs (offline)")
    fetch_parser = commands.add_parser("fetch", help="Download and verify a pinned model")
    fetch_parser.add_argument("id")
    fetch_parser.add_argument("--version", required=True)
    fetch_parser.add_argument("--cache-dir")
    fetch_parser.add_argument("--base-url", default=RELEASE_BASE_URL, help="Release download base URL, including /releases/download")
    path_parser = commands.add_parser("path", help="Print an existing model path (strictly offline)")
    path_parser.add_argument("id")
    path_parser.add_argument("--version", help="Required for cached releases; local checkouts are unversioned")
    path_parser.add_argument("--cache-dir")
    path_parser.add_argument("--root", help="Local library root containing models/<id>")
    path_parser.add_argument("--format", choices=("urdf", "mjcf", "glb", "sensors", "directory"), default="directory")
    args = parser.parse_args(argv)
    try:
        if args.command == "list":
            print("\n".join(list_models()))
        elif args.command == "fetch":
            model = fetch(args.id, version=args.version, cache_dir=args.cache_dir, base_url=args.base_url)
            print(model.directory)
        else:
            model = get_model(args.id, version=args.version, root=args.root, cache_dir=args.cache_dir)
            attribute = {"glb": "visual", "sensors": "sensor_manifest"}.get(args.format, args.format)
            print(getattr(model, attribute))
        return 0
    except AssetError as exc:
        print(f"camera-assets: {exc}", file=sys.stderr)
        return 1
