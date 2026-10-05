"""Compose concise detail sheets from verified renders of the delivered GLBs.

Pillow only lays out existing Blender Cycles PNGs. Source records must identify
the requested view and match the current exported model's SHA-256; no product
photographs, generated illustrations, stale images or software proxies are used.

Run after rendering the needed hero/back views:
    python scripts/make_detail_showcase.py --main-only
    python scripts/make_detail_showcase.py
"""
from functools import lru_cache
from pathlib import Path
import argparse
import hashlib
import json

from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[1]
SIZE = (1920, 1400)
BACKGROUND = (246, 248, 250)
INK = (25, 34, 42)
MUTED = (91, 104, 114)
MAIN = [
    ("x6", "Insta360 X6"),
    ("go3s", "Insta360 GO 3S"),
    ("ace_pro2", "Insta360 Ace Pro 2"),
]
EXTRA = [
    ("go3", "Insta360 GO 3"),
    ("go_ultra", "Insta360 GO Ultra"),
    ("go3_action_pod", "GO 3 / GO 3S Action Pod"),
    ("one_rs_1inch360", "ONE RS 1-Inch 360 Edition"),
    ("realsense_d455", "RealSense D455"),
    ("oak_d", "Luxonis OAK-D"),
]


@lru_cache(maxsize=12)
def font(size, bold=False):
    candidates = [
        Path("/System/Library/Fonts/Supplemental") / ("Arial Bold.ttf" if bold else "Arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu") / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation2") / ("LiberationSans-Bold.ttf" if bold else "LiberationSans-Regular.ttf"),
        Path("/System/Library/Fonts/Helvetica.ttc"),
    ]
    path = next((p for p in candidates if p.is_file()), None)
    return ImageFont.truetype(str(path), size) if path else ImageFont.load_default(size=size)


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


def _header(sheet, title, subtitle):
    draw = ImageDraw.Draw(sheet)
    draw.text((48, 24), "KIWI / CAMERA ASSET LIBRARY", font=font(15, True), fill=MUTED)
    draw.text((46, 53), title, font=font(43, True), fill=INK)
    draw.text((48, 111), subtitle, font=font(19), fill=MUTED)
    draw.line((48, 145, SIZE[0] - 48, 145), fill=(212, 220, 226), width=1)


def _card(sheet, source, label, column, row, tag):
    x, y = 48 + column * 616, 160 + row * 610
    draw = ImageDraw.Draw(sheet)
    draw.rounded_rectangle((x, y, x + 592, y + 586), radius=12,
                           fill=(255, 255, 255), outline=(218, 224, 230), width=1)
    # Longer configuration names fit naturally without shrinking image areas.
    label_font = font(23, True)
    if draw.textbbox((0, 0), label, font=label_font)[2] > 460:
        label_font = font(21, True)
    draw.text((x + 18, y + 13), label, font=label_font, fill=INK)
    tag_font = font(13, True)
    tag_width = draw.textbbox((0, 0), tag, font=tag_font)[2]
    draw.text((x + 574 - tag_width, y + 19), tag, font=tag_font, fill=MUTED)
    image = ImageOps.contain(source, (528, 528), Image.Resampling.LANCZOS)
    image_x, image_y = x + (592 - image.width) // 2, y + 46 + (528 - image.height) // 2
    sheet.paste(image, (image_x, image_y))


def _footer(sheet):
    draw = ImageDraw.Draw(sheet)
    text = "Actual exported GLB renders  /  Individually framed; not to a common physical scale"
    draw.text((48, 1371), text, font=font(14), fill=MUTED)


def main_sheet():
    # Resolve every source before composing or replacing an existing output.
    sources = {(mid, view): load_render(mid, view)
               for mid, _ in MAIN for view in ("hero", "back")}
    sheet = Image.new("RGB", SIZE, BACKGROUND)
    _header(sheet, "DETAILED CAMERA EXTERIORS", "Front and rear views of the delivered simulation models")
    for column, (mid, label) in enumerate(MAIN):
        for row, view in enumerate(("hero", "back")):
            _card(sheet, sources[mid, view], label, column, row,
                  "FRONT" if view == "hero" else "REAR")
    _footer(sheet)
    return sheet


def extra_sheet():
    sources = {mid: load_render(mid, "hero") for mid, _ in EXTRA}
    sheet = Image.new("RGB", SIZE, BACKGROUND)
    _header(sheet, "MORE CAMERA CONFIGURATIONS", "Wearables, a docking accessory, modular 360 and robot depth cameras")
    for index, (mid, label) in enumerate(EXTRA):
        _card(sheet, sources[mid], label, index % 3, index // 3, "HERO")
    _footer(sheet)
    return sheet


def save(sheet, name):
    output = ROOT / "catalog" / name
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name("." + output.name + ".tmp")
    sheet.save(temporary, format="PNG", optimize=True)
    temporary.replace(output)
    print(f"{output} ({sheet.width} x {sheet.height})", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument("--main-only", action="store_true", help="Only X6 / GO 3S / Ace Pro 2 front and rear sheet")
    choice.add_argument("--extra-only", action="store_true", help="Only the six additional configuration hero views")
    args = parser.parse_args()
    try:
        primary = None if args.extra_only else main_sheet()
        extra = None if args.main_only else extra_sheet()
        if primary is not None:
            save(primary, "detail_showcase.png")
        if extra is not None:
            save(extra, "detail_showcase_extra.png")
    except (OSError, ValueError, KeyError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
