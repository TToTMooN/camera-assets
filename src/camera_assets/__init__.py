"""A small offline-first client for the camera asset library."""

from .api import AssetError, CameraModel, default_cache_dir, fetch, get_model, list_models
from .release_spec import RELEASE_BASE_URL

__version__ = "0.1.0"

__all__ = [
    "AssetError", "CameraModel", "RELEASE_BASE_URL", "default_cache_dir",
    "fetch", "get_model", "list_models",
]
