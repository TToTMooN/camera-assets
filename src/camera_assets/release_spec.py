"""Small, shared identifiers for camera asset releases."""

import re

SCHEMA_VERSION = 1
REPOSITORY = "TToTMooN/camera-assets"
RELEASE_BASE_URL = f"https://github.com/{REPOSITORY}/releases/download"


def normalize_version(value: str) -> str:
    """Return a pinned stable release version, such as ``v0.1.0``."""
    if not isinstance(value, str) or not re.fullmatch(
        r"v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value
    ):
        raise ValueError("Version must be a fixed stable release, such as v0.1.0")
    return value if value.startswith("v") else f"v{value}"


def validate_model_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", value):
        raise ValueError("Model ID must contain lowercase letters, digits or underscores")
    return value
