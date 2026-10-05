"""Compose a catalog of the delivered geometry from individual studio previews.

Use --software for an optional common-scale orthographic geometry render.
"""
from pathlib import Path
import json
import math
import argparse

from PIL import Image, ImageDraw, ImageFont, ImageOps
from preview_assets import load_render

ROOT = Path(__file__).resolve().parents[1]


def save_png(image, path):
    # Replace only after the complete image has been written.
    temporary = path.with_name('.' + path.name + '.tmp')
    image.save(temporary, format='PNG')
    temporary.replace(path)


def font(size):
    for path in ("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def render(model_dir, width=440, height=480, pixels_per_meter=2500):
    import numpy as np
    import trimesh
    meta = json.loads((model_dir / "model.json").read_text())
    colors = {part["name"]: part["rgba"] for part in
              json.loads((model_dir / "assets/visual_manifest.json").read_text())}
    scene = trimesh.load_scene(model_dir / meta["visual"])
    scene.apply_transform(trimesh.transformations.rotation_matrix(math.pi/2, [1, 0, 0]))
    view = np.array([1.0, .68, .33])
    view /= np.linalg.norm(view)
    right = np.cross([0, 0, 1], view)
    right /= np.linalg.norm(right)
    up = np.cross(view, right)
    basis = np.stack([right, up, view])
    center = scene.bounds.mean(axis=0)
    pixels = np.empty((height, width, 3), dtype=np.uint8)
    pixels[:] = (241, 243, 244)
    depth_buffer = np.full((height, width), -np.inf)
    light = np.array([.35, -.20, 1.])
    light /= np.linalg.norm(light)
    for name in scene.graph.nodes_geometry:
        transform, geometry_name = scene.graph[name]
        mesh = scene.geometry[geometry_name].copy()
        mesh.apply_transform(transform)
        vertices = (mesh.vertices-center) @ basis.T
        mat = getattr(mesh.visual, "material", None)
        # Use validated full-precision factors. The loader quantizes tiny linear
        # factors to uint8, which must not be mistaken for normalized RGB.
        if getattr(mat, "name", None) in colors:
            factor = np.asarray(colors[mat.name][:3])
            color = np.where(factor <= .0031308, factor*12.92, 1.055*factor**(1/2.4)-.055)*255
        else:
            color = np.asarray(getattr(mat, "diffuse", [80, 90, 100, 255]), dtype=float)[:3]
        for face, normal in zip(mesh.faces, mesh.face_normals):
            if normal @ view < -.001:
                continue
            projected = vertices[face]
            xy = np.stack([width/2+projected[:, 0]*pixels_per_meter,
                           height/2-projected[:, 1]*pixels_per_meter], axis=1)
            shade = .55+.45*max(0., float(normal @ light))
            # Lift very dark PBR albedo for a readable neutral-studio thumbnail.
            rgb = np.clip((color*.85+20)*shade, 0, 255).astype(int)
            x0, y0 = np.maximum(np.floor(xy.min(axis=0)).astype(int), [0, 0])
            x1, y1 = np.minimum(np.ceil(xy.max(axis=0)).astype(int), [width-1, height-1])
            if x0 > x1 or y0 > y1:
                continue
            a, b, c = xy
            denominator = (b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
            if abs(denominator) < 1e-10:
                continue
            yy, xx = np.mgrid[y0:y1+1, x0:x1+1]
            xx, yy = xx+.5, yy+.5
            wa = ((b[1]-c[1])*(xx-c[0])+(c[0]-b[0])*(yy-c[1]))/denominator
            wb = ((c[1]-a[1])*(xx-c[0])+(a[0]-c[0])*(yy-c[1]))/denominator
            wc = 1-wa-wb
            z = wa*projected[0, 2]+wb*projected[1, 2]+wc*projected[2, 2]
            target = depth_buffer[y0:y1+1, x0:x1+1]
            visible = (wa >= -1e-8) & (wb >= -1e-8) & (wc >= -1e-8) & (z >= target)
            pixels[y0:y1+1, x0:x1+1][visible] = rgb
            target[visible] = z[visible]
    return Image.fromarray(pixels)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--software',action='store_true',help='Use to-scale geometry rendering instead of Cycles studio previews')
    args=parser.parse_args()
    cameras = json.loads((ROOT / "catalog/cameras.json").read_text())["cameras"]
    # Resolve and verify all recorded views before replacing any catalog output.
    # A back-only render may leave an old hero PNG on disk; existence is not proof.
    try:
        studio_images = {} if args.software else {
            camera['id']: load_render(camera['id'], 'hero') for camera in cameras}
    except (OSError, ValueError, KeyError) as error:
        parser.error(f"{error}. Run render_studio.py first, or use --software.")
    columns, tile_w, tile_h = 4, 480, 610
    rows = math.ceil(len(cameras)/columns)
    sheet = Image.new("RGB", (columns*tile_w, 165+rows*tile_h+80), (241, 243, 244))
    draw = ImageDraw.Draw(sheet)
    draw.text((40, 28), "CAMERA MODEL LIBRARY", font=font(38), fill=(25, 34, 42))
    scale_text='common physical scale' if args.software else 'individual studio framing'
    draw.text((40, 80), f"{len(cameras)} configurations  /  {scale_text}  /  reference-informed exterior", font=font(23), fill=(70, 80, 88))
    draw.text((40, 115), "Actual delivered geometry. Published envelope + mass; fine geometry, mounts and inertia remain unmeasured.", font=font(20), fill=(82, 92, 101))
    for index, camera in enumerate(cameras):
        x, y = index % columns * tile_w, 165+index//columns*tile_h
        model_dir = ROOT / "models" / camera["id"]
        if not args.software:
            image=ImageOps.pad(studio_images[camera['id']],(440,465),color=(241,243,244))
        else:
            image = render(model_dir)
        sheet.paste(image, (x+20, y))
        draw.text((x+27, y+470), camera["name"].replace("Insta360 ", ""), font=font(22), fill=(28, 37, 45))
        dim = f"{camera['width_mm']:g} x {camera['height_mm']:g} x {camera['overall_depth_mm']:g} mm"
        draw.text((x+27, y+505), dim, font=font(20), fill=(70, 80, 88))
        draw.text((x+27, y+535), f"{camera['mass_kg']*1000:g} g   /   {camera['id']}", font=font(19), fill=(85, 94, 102))
        draw.line((x+25, y+590, x+tile_w-25, y+590), fill=(218, 223, 226), width=1)
    draw.text((40, sheet.height-55), "Independent geometry  /  meters in URDF, MJCF, OBJ and GLB  /  Sources: catalog/cameras.json", font=font(20), fill=(78, 88, 98))
    path = ROOT / ('catalog/catalog_to_scale.png' if args.software else "catalog/catalog.png")
    save_png(sheet, path)
    print(path)


if __name__ == "__main__":
    main()
