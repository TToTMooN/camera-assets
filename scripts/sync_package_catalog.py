"""Copy the canonical model catalog into the lightweight Python package."""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if the bundled catalog is out of date")
    args = parser.parse_args()
    source = (ROOT / "catalog/cameras.json").read_bytes()
    destination = ROOT / "src/camera_assets/catalog.json"
    if args.check:
        if not destination.is_file() or destination.read_bytes() != source:
            parser.error("Bundled catalog is stale; run python scripts/sync_package_catalog.py")
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source)


if __name__ == "__main__":
    main()
