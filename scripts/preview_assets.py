"""Load studio previews only when their source GLB and render record agree."""
from pathlib import Path
import hashlib
import json

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def _contained_file(parent, relative):
    path = (parent / relative).resolve()
    if not path.is_relative_to(parent.resolve()):
        raise ValueError(f"Source path escapes its model directory: {relative}")
    if not path.is_file():
        raise ValueError(f"Missing source file: {path}")
    return path


def load_render(model_id, view):
    folder = ROOT / "models" / model_id
    metadata = json.loads((folder / "model.json").read_text())
    glb = _contained_file(folder, metadata["visual"])
    preview = folder / "preview"
    record_path = preview / "studio_render.json"
    if not record_path.is_file():
        raise ValueError(f"{model_id}: no studio render record; render {view} first")
    record = json.loads(record_path.read_text())
    if record.get("renderer") != "Blender Cycles":
        raise ValueError(f"{model_id}: source is not a recorded Blender Cycles render")
    sha256 = hashlib.sha256(glb.read_bytes()).hexdigest()
    if record.get("glb_sha256") != sha256:
        raise ValueError(f"{model_id}: studio render is stale; its GLB hash does not match")
    info = record.get("views", {}).get(view)
    if not isinstance(info, dict):
        raise ValueError(f"{model_id}: {view} is not present in the current render record")
    path = _contained_file(preview, info["file"])
    with Image.open(path) as source:
        if source.format != "PNG":
            raise ValueError(f"{model_id}: recorded render is not a PNG")
        expected = info.get("size_px")
        if expected is not None and source.size != (expected, expected):
            raise ValueError(f"{model_id}: PNG dimensions disagree with the render record")
        source.load()
        return source.convert("RGB")
