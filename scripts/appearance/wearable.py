"""Reference-informed GO cameras and their folded/closed accessories.

All authoring dimensions are millimeters. Exterior detail proportions are
estimated from the manufacturer's renders and annotated manuals in
``references/wearable``; they are not docking-fit or optical calibration data.
"""
import math

import numpy as np
import trimesh
from shapely.geometry import Polygon

from .common import (basis, contour, lathe, outline, ring, rounded_panel,
                     text_mesh, tube_line)


IDS = {"go2", "go3", "go3s", "go_ultra", "go3_action_pod",
       "go_ultra_action_pod", "go2_charging_case"}


def _disk(radius, depth, center, normal=(1, 0, 0), segments=72):
    return lathe([(0, -depth / 2), (radius, -depth / 2),
                  (radius, depth / 2), (0, depth / 2)], center, normal, segments)


def _ellipse(points, center, normal=(1, 0, 0)):
    return np.column_stack([points, np.zeros(len(points))]) @ basis(normal).T + np.asarray(center)


def _planar(poly, offset, normal=(1, 0, 0)):
    """Planar polygon with genuine holes; no filled-in cavity decal."""
    vertices, faces = trimesh.creation.triangulate_polygon(poly, engine="earcut")
    local = np.column_stack([vertices, np.zeros(len(vertices))])
    result = trimesh.Trimesh((local @ basis(normal).T + np.asarray(offset)) * .001,
                            faces, process=False)
    # Earcut triangulates in counterclockwise local coordinates.
    return result


def _loft(contours, offsets, center, normals=True):
    """Rounded-rectangle side walls in local XY, axis along world X."""
    n = len(contours[0])
    vertices = np.concatenate([np.column_stack([xy, np.full(n, x)])
                               for xy, x in zip(contours, offsets)])
    vertices = vertices @ basis((1, 0, 0)).T + np.asarray(center)
    faces = []
    for i in range(len(contours) - 1):
        for j in range(n):
            a, b = i * n + j, i * n + (j + 1) % n
            c, d = (i + 1) * n + (j + 1) % n, (i + 1) * n + j
            faces.extend([[a, b, c], [a, c, d]])
    result = trimesh.Trimesh(vertices * .001, faces, process=False)
    if normals:
        # Smooth just the continuously curved walls, leaving planar caps separate.
        _ = result.vertex_normals
    return result


def _cavity(ctx, name, width, height, corner, body_height, cavity_width,
            cavity_height, cavity_corner, cy, cz, depth):
    """Build the physical well and curved shell of an empty Action Pod.

    The rear solid stops at the bottom of the well. The annular front cap,
    rolled lip and inside walls contain a real opening, so depth-buffered
    renderers show the contacts below the surrounding housing.
    """
    front = ctx.overall / 2 - .10
    floor = front - depth
    rear = -ctx.overall / 2
    # A shallow rear recess reserves real space for the folded display slab.
    back_depth = floor - rear - .72
    ctx.add(name + "_rear_core", rounded_panel(width, body_height, back_depth + .12,
            corner, ((floor + rear + .72) / 2, 0, body_height / 2), bevel=3.2))
    # The broad side wall has a smoothly rolled front edge.
    outer = [contour(width, body_height, corner, 32)]
    axial = [floor - .06]
    roll = 1.2
    for angle in np.linspace(0, math.pi / 2, 9):
        inset = roll * (1 - math.cos(angle))
        outer.append(contour(width - 2 * inset, body_height - 2 * inset,
                             corner - inset, 32))
        axial.append(front - roll + roll * math.sin(angle))
    ctx.add(name + "_rounded_shell_wall", _loft(outer, axial, (0, 0, body_height / 2)))
    # Opening coordinates are local face Y/Z. Widen near the mouth to form a lip.
    lip_width, lip_height = cavity_width + 1.5, cavity_height + 1.5
    mouth = contour(lip_width, lip_height, cavity_corner + .65, 32)
    final_outer = Polygon(outer[-1] + [0, body_height / 2])
    opening = Polygon(mouth + [cy, cz])
    ctx.add(name + "_front_shell_with_opening", _planar(final_outer.difference(opening), (front, 0, 0)))
    # Inner wall is open at the top and slopes down to the actual tray floor.
    inner_contours, inner_x = [], []
    for t in np.linspace(0, 1, 11):
        # The top 1.3 mm are rolled; the remaining well tapers slightly inward.
        inset = .75 * math.sin(t * math.pi / 2)
        inner_contours.append(contour(lip_width - 2 * inset,
                                      lip_height - 2 * inset,
                                      cavity_corner + .65 - inset, 32))
        inner_x.append(front - 1.3 * t)
    inner_contours.append(contour(cavity_width - 1.2, cavity_height - 1.0,
                                  cavity_corner - .6, 32))
    inner_x.append(floor + .18)
    ctx.add(name + "_docking_well", _loft(inner_contours, inner_x, (0, cy, cz)), "tray")
    ctx.add(name + "_tray_floor", rounded_panel(cavity_width - 1.1, cavity_height - 1.0,
            .28, cavity_corner - .5, (floor + .05, cy, cz), bevel=.12), "tray")
    ctx.add(name + "_lip_gasket", outline(lip_width - .15, lip_height - .15,
            cavity_corner + .45, (front - .02, cy, cz), stroke=.105), "gasket")
    return front, floor


def _palette(ctx, white=True):
    # Warm white polymer and cool grey silicone remain distinct under studio light.
    ctx.colors.update({
        "housing": [.91, .915, .905, 1] if white else [.20, .215, .23, 1],
        "front_polymer": [.93, .935, .925, 1] if white else [.23, .242, .255, 1],
        "rear_polymer": [.87, .885, .875, 1] if white else [.175, .185, .198, 1],
        "gasket": [.12, .135, .145, 1], "tray": [.21, .23, .24, 1] if white else [.065, .075, .088, 1],
        "rib": [.255, .277, .285, 1] if white else [.105, .12, .13, 1],
        "lens_ring": [.105, .115, .122, 1], "rim_edge": [.25, .278, .29, 1],
        "lens_coating": [.078, .123, .133, 1], "optical_glass": [.014, .024, .028, 1],
        "pupil": [.004, .007, .009, 1], "screen": [.019, .027, .035, 1],
        "screen_border": [.065, .075, .086, 1], "silver": [.67, .71, .735, 1],
        "gold": [.72, .51, .17, 1], "print": [.19, .21, .22, 1] if white else [.63, .67, .69, 1],
        "ambient_sensor": [.79, .82, .83, 1],
        "subtle_print": [.78, .80, .79, 1] if white else [.30, .32, .34, 1],
        "status": [.20, .79, .89, 1], "slot": [.025, .033, .039, 1],
    })
    if hasattr(ctx, "materials"):
        for name in ["housing", "front_polymer", "rear_polymer"]:
            ctx.materials[name] = {"roughnessFactor": .42 if white else .48, "metallicFactor": .0}
        ctx.materials.update({
            "lens_ring": {"roughnessFactor": .27, "metallicFactor": .55},
            "rim_edge": {"roughnessFactor": .22, "metallicFactor": .7},
            "lens_coating": {"roughnessFactor": .055, "metallicFactor": .15},
            "optical_glass": {"roughnessFactor": .045, "metallicFactor": .12},
            "pupil": {"roughnessFactor": .07, "metallicFactor": .02},
            "screen": {"roughnessFactor": .075, "metallicFactor": .08},
            "gold": {"roughnessFactor": .25, "metallicFactor": .82},
            "silver": {"roughnessFactor": .28, "metallicFactor": .8},
        })


def _mark(ctx, name, text, height, center, normal=(1, 0, 0), width=None,
          material="print", angle=0):
    ctx.add(name, text_mesh(text, height, .014, center, normal, width=width, angle=angle), material)


def _logo(ctx, center, size=2.35, normal=(1, 0, 0)):
    """The small camera-button swirl is modeled as fine rounded engraving."""
    b = basis(normal)
    rings = []
    for radius, begin, end in [(size / 2, -.15, math.tau - .15),
                               (size * .27, .75, math.tau + .45)]:
        for t in np.linspace(begin, end, 80):
            rings.append(np.asarray(center) + b @ np.array([radius * math.cos(t), radius * math.sin(t), 0]))
        ctx.add("button_swirl_" + str(radius), tube_line(rings, .16, 10), "subtle_print")
        rings = []


def _contacts(ctx, name, center, radius=4.2, normal=(-1, 0, 0), count=6,
              plate=True, ring_material="rear_polymer"):
    b = basis(normal)
    if plate:
        ctx.add(name + "_contact_insulator", _disk(radius, .11, center, normal), "gasket")
        ctx.add(name + "_contact_surround", ring(radius + .42, radius + .04, .10,
                np.asarray(center) + b[:, 2] * .015, normal), ring_material)
    for i, t in enumerate(np.linspace(0, math.tau, count, endpoint=False)):
        pos = np.asarray(center) + b @ np.array([radius * .62 * math.cos(t), radius * .62 * math.sin(t), .08])
        ctx.add(f"{name}_contact_{i}_rim", _disk(.63, .08, pos, normal, 40), "silver")
        ctx.add(f"{name}_contact_{i}", _disk(.43, .10, pos + b[:, 2] * .04, normal, 40), "gold")


def _lens(ctx, center, radius, protrusion):
    """Flat protective window, machined guard and recessed inner lens optics."""
    group = "front_lens"
    # Four physically distinct concentric steps, with the outer lip setting depth.
    ctx.add("lens_sealing_gasket", ring(radius + .20, radius * .89, .25,
            np.asarray(center) + [.10, 0, 0]), "gasket", collision=group)
    profile = [(radius * .85, .08), (radius * .96, .08), (radius, .30),
               (radius, max(.32, protrusion - .40)), (radius * .97, protrusion),
               (radius * .88, protrusion), (radius * .84, protrusion - .23),
               (radius * .84, .08)]
    ctx.add("replaceable_lens_guard", lathe(profile, center), "lens_ring", collision=group)
    ctx.add("lens_guard_chamfer", ring(radius * .985, radius * .955, .075,
            np.asarray(center) + [protrusion - .09, 0, 0]), "rim_edge", collision=group)
    # The visible optical assembly is a recessed curved cup, with a small
    # convex front element. These real curved normals avoid a flat target-like
    # collection of concentric painted disks in oblique views.
    ctx.add("lens_guard_optical_cup", lathe([
            (radius * .22, protrusion - 1.05), (radius * .40, protrusion - 1.05),
            (radius * .60, protrusion - .78), (radius * .78, protrusion - .33),
            (radius * .88, protrusion - .19), (radius * .87, protrusion - .11),
            (radius * .77, protrusion - .24), (radius * .58, protrusion - .61),
            (radius * .36, protrusion - .80), (radius * .22, protrusion - .75),
            (radius * .22, protrusion - 1.05)], center, segments=160), "lens_coating", collision=group)
    ctx.add("lens_inner_optic", lathe([
            (0, protrusion - .84), (radius * .565, protrusion - .84),
            (radius * .565, protrusion - .63), (radius * .39, protrusion - .74),
            (radius * .24, protrusion - .77), (0, protrusion - .77)],
            center, segments=128), "optical_glass", collision=group)
    ctx.add("lens_inner_optic_ring", ring(radius * .61, radius * .56, .025,
            np.asarray(center) + [protrusion - .55, 0, 0]), "rim_edge", collision=group)
    ctx.add("lens_front_element", lathe([
            (0, protrusion - .83), (radius * .265, protrusion - .83),
            (radius * .265, protrusion - .70), (radius * .23, protrusion - .56),
            (radius * .17, protrusion - .40), (radius * .10, protrusion - .30),
            (0, protrusion - .28)], center, segments=128), "lens_coating", collision=group)
    ctx.add("lens_front_element_ring", ring(radius * .31, radius * .275, .022,
            np.asarray(center) + [protrusion - .665, 0, 0]), "rim_edge", collision=group)
    ctx.add("lens_pupil", _disk(radius * .069, .014,
            np.asarray(center) + [protrusion - .27, 0, 0], segments=64), "pupil", collision=group)


def _capsule(ctx):
    model = ctx.camera["id"]
    w, h, d, front = ctx.w, ctx.h, ctx.d, ctx.body_front
    # GO 3S's larger protector is distinguishable from GO 3 and GO 2.
    lens_r = {"go2": 9.75, "go3": 10.75, "go3s": 11.8}[model]
    lens_z = h - w / 2
    radius = w / 2 - .02
    ctx.add("continuous_capsule_shell", rounded_panel(w, h, d - 1.02, radius,
            (ctx.body_x + .34, 0, h / 2), bevel=min(3.8, d * .23), steps=40))
    # The whole white face is the quick-capture button. There is no black button.
    ctx.add("front_button_face", rounded_panel(w - 1.10, h - 1.12, .45,
            radius - .6, (front - .185, 0, h / 2), bevel=.20, steps=40), "front_polymer")
    ctx.add("front_face_joint", outline(w - .95, h - .95, radius - .55,
            (front - .20, 0, h / 2), stroke=.055), "subtle_print")
    _lens(ctx, (front, 0, lens_z), lens_r, ctx.overall - d)
    if model == "go2":
        ctx.add("indicator_window", _disk(.56, .065, (front + .07, 0, lens_z - lens_r - 2.5)), "status")
    else:
        ctx.add("microphone_front", _disk(.39, .065, (front + .04, 0, lens_z - lens_r - 1.9)), "slot")
        ctx.add("indicator_window", rounded_panel(4.0, .95, .065, .45,
                (front + .05, 0, 4.8), bevel=.028), "status")
        # Speaker slit at the rounded lower side, explicitly on the bottom face.
        ctx.add("speaker_slot", rounded_panel(3.35, .48, .055, .22,
                (ctx.body_x + 2.2, 0, .065), (0, 0, -1)), "slot")
    _logo(ctx, (front + .052, 0, h * .18), 2.5 if model != "go2" else 2.25)
    # Top microphone is inset below the published height, not added above it.
    ctx.add("top_microphone", _disk(.35, .075, (ctx.body_x + 1.0, 0, h - .04), (0, 0, 1), 48), "slot")
    rear = -ctx.overall / 2
    ctx.add("magnetic_rear_plate", rounded_panel(w - 2.0, h - 2.0, .085,
            radius - 1.0, (rear + .75, 0, h / 2), (-1, 0, 0), bevel=.035, steps=40), "rear_polymer")
    ctx.add("rear_plate_seam", outline(w - 1.8, h - 1.8, radius - .90,
            (rear + .70, 0, h / 2), (-1, 0, 0), stroke=.060), "subtle_print")
    _contacts(ctx, model, (rear + .17, 0, lens_z), radius=3.65 if model == "go2" else 4.0)
    if model != "go2":
        # The six diagonal traction ribs in the GO 3/3S annotated rear view.
        for i, (y, z, length) in enumerate([(-5.3, 29.7, 5.7), (-2.4, 27.4, 11.0),
                                           (0.3, 23.5, 14.1), (2.8, 19.6, 13.5),
                                           (4.4, 15.2, 8.8), (5.7, 10.9, 3.8)]):
            dy, dz = length * .35, length * .94
            ctx.add(f"rear_traction_rib_{i}", tube_line([(rear + .60, y - dy / 2, z - dz / 2),
                    (rear + .60, y + dy / 2, z + dz / 2)], .54, 12), "subtle_print")
    else:
        _mark(ctx, "rear_camera_identifier", "GO 2", 1.65, (rear + .69, 0, 7.2), (-1, 0, 0), width=10)
    ctx.surfaces.append((model + "_front_lens_surface",
                         [ctx.overall * .0005, 0, lens_z * .001], 1))


def _microphone_grid(ctx, center, radius=2.6):
    ctx.add("microphone_mesh_surround", ring(radius + .20, radius, .08, center), "gasket")
    ctx.add("microphone_mesh", _disk(radius, .055, center), "rib")
    for row in range(-5, 6):
        for column in range(-5, 6):
            y, z = column * .43 + (row % 2) * .215, row * .38
            if y * y + z * z <= (radius - .24) ** 2:
                ctx.add(f"mic_perforation_{row}_{column}", _disk(.105, .026,
                        np.asarray(center) + [.045, y, z], segments=16), "slot")


def _ultra(ctx):
    w, h, d, front, rear = ctx.w, ctx.h, ctx.d, ctx.body_front, -ctx.overall / 2
    ctx.add("rounded_square_camera_shell", rounded_panel(w, h, d - .58, 11.8,
            (ctx.body_x + .11, 0, h / 2), bevel=3.6, steps=40))
    ctx.add("continuous_front_button_panel", rounded_panel(w - 1.1, h - 1.1, .39, 11.35,
            (front - .17, 0, h / 2), bevel=.18, steps=40), "front_polymer")
    ctx.add("front_panel_perimeter", outline(w - 1.0, h - 1.0, 11.35,
            (front - .16, 0, h / 2), stroke=.06), "rear_polymer")
    lens_y, lens_z, lens_r = 8.0, 32.0, 12.6
    _lens(ctx, (front, lens_y, lens_z), lens_r, ctx.overall - d)
    _microphone_grid(ctx, (front + .035, -13.1, 31.9), 2.7)
    ctx.add("ambient_light_sensor_bezel", ring(1.27, 1.03, .07,
            (front + .053, -13.1, 24.8)), "silver")
    ctx.add("ambient_light_sensor_window", _disk(1.015, .073,
            (front + .069, -13.1, 24.8)), "ambient_sensor")
    ctx.add("lower_status_window", rounded_panel(4.6, 1.1, .075, .5,
            (front + .052, 8.0, 7.4), bevel=.03), "status")
    # The manual's dotted button callout denotes an integrated push area;
    # the manufacturer render shows a continuous, unmarked front surface.
    ctx.add("rear_square_plate", rounded_panel(w - 2.1, h - 2.1, .08, 10.8,
            (rear + .048, 0, h / 2), (-1, 0, 0), bevel=.028, steps=40), "rear_polymer")
    ctx.add("rear_magnet_ring", ring(16.1, 14.45, .065,
            (rear + .04, 0, h / 2), (-1, 0, 0), segments=128), "subtle_print")
    # Contacts follow the lower arc of the rear magnetic interface.
    for i, t in enumerate(np.linspace(math.radians(230), math.radians(310), 7)):
        y, z = 15.1 * math.cos(t), h / 2 + 15.1 * math.sin(t)
        ctx.add(f"ultra_rear_contact_{i}", _disk(.58, .045,
                (rear + .0225, y, z), (-1, 0, 0), 40), "gold")
    for sign in (-1, 1):
        ctx.add(f"side_lock_tab_{sign}", rounded_panel(6.4, 6.7, .30, 1.4,
                (ctx.body_x - .5, sign * (w / 2 - .22), h / 2), (0, sign, 0)), "rear_polymer")
        ctx.add(f"side_lock_tab_slit_{sign}", rounded_panel(3.1, .47, .06, .23,
                (ctx.body_x - .5, sign * (w / 2 - .04), h / 2 - 1.3), (0, sign, 0)), "gasket")
    ctx.add("microSD_door", rounded_panel(11.2, 3.8, .07, 1.2,
            (ctx.body_x - 1.2, -8.6, h - .05), (0, 0, 1)), "rear_polymer")
    ctx.add("microSD_door_joint", outline(11.4, 3.9, 1.3,
            (ctx.body_x - 1.2, -8.6, h - .05), (0, 0, 1), stroke=.045), "gasket")
    for sign in (-1, 1):
        ctx.add(f"rear_mount_locator_{sign}", rounded_panel(2.2, 4.0, .05, .8,
                (rear + .04, sign * 12.9, h - 7.2), (-1, 0, 0)), "subtle_print")
    # Bottom side contains the lanyard anchor; the speaker is on the right side.
    ctx.add("lanyard_anchor", rounded_panel(3.7, .8, .055, .35,
            (ctx.body_x + 1.0, 12.2, .045), (0, 0, -1)), "gasket")
    for row in range(4):
        ctx.add(f"speaker_side_slit_{row}", rounded_panel(3.0, .30, .06, .12,
                (ctx.body_x, w / 2 - .04, 13.3 + row * .63), (0, 1, 0)), "slot")
    ctx.surfaces.append(("go_ultra_front_lens_surface",
                         [ctx.overall * .0005, lens_y * .001, lens_z * .001], 1))


def _side_controls(ctx, front, body_height, ultra=False):
    w, d = ctx.w, ctx.d
    # Controls on the user's left, release lever and port on the other side.
    for z, label in [(body_height * .72, "POWER"), (body_height * .34, "Q")]:
        ctx.add("side_" + label + "_recess", rounded_panel(d * .43, 10.4, .07, 3.5,
                (0, -w / 2 + .14, z), (0, -1, 0)), "rear_polymer")
        ctx.add("side_" + label + "_button", rounded_panel(d * .35, 8.1, .12, 2.6,
                (0, -w / 2 + .06, z), (0, -1, 0)), "front_polymer")
        _mark(ctx, "side_" + label + "_symbol", "Q" if label == "Q" else "O", 2.2,
              (0, -w / 2 + .020, z), (0, -1, 0), material="subtle_print")
    ctx.add("release_lever", rounded_panel(d * .40, 7.1, .12, 2.0,
            (.6, w / 2 - .060, body_height * .63), (0, 1, 0)), "rear_polymer")
    for i in range(5):
        ctx.add(f"release_lever_ridge_{i}", rounded_panel(4.0, .30, .055, .13,
                (.6, w / 2 - .030, body_height * .63 - 1.3 + i * .65), (0, 1, 0)), "subtle_print")
    ctx.add("usb_c_metal_surround", rounded_panel(8.8, 3.1, .045, 1.35,
            (-.7, w / 2 - .12, body_height * .30), (0, 1, 0)), "silver")
    ctx.add("usb_c_socket", rounded_panel(8.10, 2.55, .060, 1.14,
            (-.7, w / 2 - .09, body_height * .30), (0, 1, 0)), "slot")
    ctx.add("usb_c_internal_tongue", rounded_panel(5.9, .65, .065, .28,
            (-.7, w / 2 - .045, body_height * .30), (0, 1, 0)), "rear_polymer")
    if ultra:
        for i in range(5):
            ctx.add(f"pod_speaker_slot_{i}", rounded_panel(3.7, .37, .045, .17,
                    (2.0, w / 2 - .024, body_height * .85 + i * .59), (0, 1, 0)), "slot")


def _folded_screen(ctx, body_height, ultra=False):
    w, h, rear = ctx.w, ctx.h, -ctx.overall / 2
    # The screen is a separate, folded slab with hinges, gasket and glass.
    screen_w, screen_h = w - 2.4, h - 4.1
    screen_z = h / 2 + .8
    ctx.add("folded_display_backplate", rounded_panel(screen_w, screen_h, .42, 5.8,
            (rear + .31, 0, screen_z), (-1, 0, 0), bevel=.19, steps=32), "rear_polymer")
    ctx.add("folded_display_gasket", rounded_panel(screen_w - .8, screen_h - .8, .09, 5.2,
            (rear + .095, 0, screen_z), (-1, 0, 0), bevel=.04, steps=32), "gasket")
    ctx.add("display_bezel", rounded_panel(screen_w - 1.3, screen_h - 1.3, .095, 4.9,
            (rear + .057, 0, screen_z), (-1, 0, 0), bevel=.042, steps=32), "screen_border")
    # 2.2/2.5-inch active area, with left branding/right indicator margins.
    active_w, active_h = screen_w - 11.2, screen_h - 6.6
    ctx.add("folded_display_glass", rounded_panel(active_w, active_h, .068, 3.6,
            (rear + .034, 0, screen_z), (-1, 0, 0), bevel=.028, steps=32), "screen")
    ctx.add("display_glass_edge", outline(active_w + .16, active_h + .16, 3.68,
            (rear + .037, 0, screen_z), (-1, 0, 0), stroke=.036), "rear_polymer")
    _mark(ctx, "display_brand", "Insta360", 1.5, (rear + .016, w / 2 - 5.9, screen_z + 7.3),
          (-1, 0, 0), width=14.1, material="subtle_print", angle=math.pi / 2)
    ctx.add("display_indicator", rounded_panel(.64, 2.4, .050, .30,
            (rear + .025, -w / 2 + 5.0, screen_z - 8.0), (-1, 0, 0)), "status")
    for sign in (-1, 1):
        ctx.add(f"display_hinge_{sign}", lathe([(0, -6.0), (1.15, -6.0),
                (1.15, 6.0), (0, 6.0)], (-ctx.overall / 2 + 1.45, sign * w * .27, h - 2.0),
                (0, sign, 0), segments=64), "rear_polymer")
        ctx.add(f"display_hinge_split_{sign}", ring(1.20, 1.05, .10,
                (-ctx.overall / 2 + 1.45, sign * w * .27, h - 2.0), (0, sign, 0), segments=64), "gasket")


def _mounting_latches(ctx):
    for sign in (-1, 1):
        ctx.add(f"base_mount_latch_{sign}", rounded_panel(5.0, 7.8, .095, 1.4,
                (ctx.body_x, sign * ctx.w * .33, .075), (0, 0, -1)), "rear_polymer")
        ctx.add(f"base_mount_latch_slot_{sign}", rounded_panel(2.2, 5.2, .055, .65,
                (ctx.body_x, sign * ctx.w * .33, .031), (0, 0, -1)), "gasket")
    ctx.add("base_magnetic_attachment", rounded_panel(ctx.w * .39, 14.1, .045, 2.0,
            (ctx.body_x, 0, .024), (0, 0, -1)), "subtle_print")


def _pod(ctx):
    ultra = ctx.camera["id"] == "go_ultra_action_pod"
    body_h = ctx.h - 1.0
    if ultra:
        cw, ch, cr, cy, cz, depth = 46.5, 43.1, 11.2, 9.6, body_h / 2, 18.5
    else:
        cw, ch, cr, cy, cz, depth = 54.9, 25.4, 12.1, 0, 31.6, 17.7
    front, floor = _cavity(ctx, "action_pod", ctx.w - .32, ctx.h, 7.9, body_h,
                           cw, ch, cr, cy, cz, depth)
    if ultra:
        # Visible interface ring and contacts on the square camera docking well.
        ctx.add("ultra_docking_magnet", ring(16.0, 14.15, .17,
                (floor + .28, cy, cz)), "subtle_print")
        for i, t in enumerate(np.linspace(math.radians(230), math.radians(310), 7)):
            ctx.add(f"ultra_pod_contact_{i}", _disk(.60, .16,
                    (floor + .44, cy + 14.9 * math.cos(t), cz + 14.9 * math.sin(t))), "gold")
        for sign in (-1, 1):
            ctx.add(f"ultra_dock_lock_{sign}", rounded_panel(2.4, 5.8, .65, .65,
                    (floor + depth * .38, cy + sign * (cw / 2 - 1.4), cz)), "rear_polymer")
        ctx.add("pod_front_grip", rounded_panel(17.2, body_h - 4.1, .10, 4.5,
                (front + .04, -ctx.w / 2 + 11.3, body_h / 2)), "rear_polymer")
        _mark(ctx, "pod_front_identifier", "Insta360 GO Ultra", 1.8,
              (front + .086, -ctx.w / 2 + 11.3, body_h * .40), width=27,
              material="subtle_print", angle=math.pi / 2)
    else:
        _contacts(ctx, "pod", (floor + .37, 18.8, cz), radius=4.6, normal=(1, 0, 0), ring_material="tray")
        # Raised diagonal traction ribs molded into the tray, not a flat black decal.
        for i, y in enumerate([-13.0, -7.5, -2.0, 3.5]):
            points = [(floor + .33, y - 5.6, cz - 6.0), (floor + .33, y + 5.6, cz + 6.0)]
            ctx.add(f"pod_diagonal_traction_rib_{i}", tube_line(points, .74, 14), "rib")
        for sign in (-1, 1):
            ctx.add(f"pod_side_retainer_{sign}", rounded_panel(1.4, 5.7, 1.0, .5,
                    (floor + depth * .28, sign * (cw / 2 - 1.2), cz)), "gasket")
        ctx.add("tray_fastener", _disk(1.20, .10, (floor + .44, -17.4, cz)), "gasket")
        ctx.add("tray_fastener_slot", tube_line([(floor + .51, -17.8, cz),
                (floor + .51, -17.0, cz)], .08), "silver")
        _mark(ctx, "pod_front_identifier", "Insta360 GO 3S", 2.55,
              (front + .086, 10.3, 7.6), width=26.0)
    # The shutter is the highest point; the case itself ends one mm below it.
    ctx.add("pod_shutter_gasket", ring(5.3, 4.7, .16,
            (ctx.body_x + 1.5, -ctx.w * .28, ctx.h - .91), (0, 0, 1)), "gasket")
    ctx.add("pod_shutter_button", lathe([(0, -.38), (4.85, -.38),
            (4.85, -.15), (4.65, .14), (0, .14)],
            (ctx.body_x + 1.5, -ctx.w * .28, ctx.h - .14), (0, 0, 1), 96), "front_polymer")
    ctx.add("pod_shutter_icon", ring(2.1, 1.95, .025,
            (ctx.body_x + 1.5, -ctx.w * .28, ctx.h - .017), (0, 0, 1)), "subtle_print")
    _side_controls(ctx, front, body_h, ultra)
    _folded_screen(ctx, body_h, ultra)
    _mounting_latches(ctx)


def _case(ctx):
    w, h, d, front, rear = ctx.w, ctx.h, ctx.d, ctx.overall / 2, -ctx.overall / 2
    # The closed case is a continuous curved clamshell with folded tripod legs.
    ctx.add("curved_clamshell", rounded_panel(w, h, d - .7, 17.6,
            (0, 0, h / 2), bevel=6.0, steps=40))
    seam_z = h * .506
    skin = rounded_panel(w - 1.6, h - 1.9, .06, 16.8,
                         (front - .04, 0, h / 2), bevel=.026, steps=40)
    ctx.add("clamshell_lid_front_surface", skin.slice_plane([0, 0, (seam_z + .075) * .001],
            [0, 0, 1], cap=False), "front_polymer")
    ctx.add("clamshell_base_front_surface", skin.slice_plane([0, 0, (seam_z - .075) * .001],
            [0, 0, -1], cap=False), "front_polymer")
    ctx.add("clamshell_front_lid_joint", rounded_panel(w - 1.8, .19, .04, .085,
            (front - .07, 0, seam_z), bevel=.015), "subtle_print")
    # The lid joint runs continuously around the housing in its closed pose.
    points = []
    # Cross-section is a rounded depth/width rectangle, in the horizontal plane.
    xy = contour(w - .28, d - .28, 5.8, 40)
    for y, x in xy:
        points.append([x, y, seam_z])
    points.append(points[0])
    ctx.add("closed_lid_seam", tube_line(points, .105, 10), "subtle_print")
    # Discreet lid release notch on the closed front.
    ctx.add("lid_release_notch", rounded_panel(6.4, .7, .045, .31,
            (front - .023, 0, seam_z - .30)), "rear_polymer")
    _mark(ctx, "case_brand", "Insta360", 3.0, (front - .014, 0, h * .29), width=23.6,
          material="subtle_print")
    # Folded leg boundaries are on the rear, with true shallow layered parts.
    for sign in (-1, 1):
        ctx.add(f"folded_tripod_leg_{sign}", rounded_panel(9.4, 22.7, .075, 4.25,
                (rear + .057, sign * 12.8, 17.2), (-1, 0, 0), bevel=.03), "rear_polymer")
        ctx.add(f"folded_tripod_leg_joint_{sign}", outline(9.6, 22.9, 4.30,
                (rear + .070, sign * 12.8, 17.2), (-1, 0, 0), stroke=.065), "subtle_print")
    ctx.add("clamshell_hinge", rounded_panel(17.4, 4.1, .11, 1.4,
            (rear + .075, 0, seam_z), (-1, 0, 0)), "rear_polymer")
    ctx.add("hinge_joint", rounded_panel(16.7, .45, .035, .19,
            (rear + .020, 0, seam_z), (-1, 0, 0)), "subtle_print")
    # Closed rear view from the quickstart: pinhole, USB-C, threaded socket.
    ctx.add("case_lid_pinhole", _disk(.40, .040, (rear + .024, 0, h * .68), (-1, 0, 0)), "slot")
    ctx.add("case_usb_surround", rounded_panel(8.9, 3.2, .045, 1.4,
            (rear + .085, 0, h * .355), (-1, 0, 0)), "silver")
    ctx.add("case_usb_socket", rounded_panel(8.1, 2.5, .065, 1.1,
            (rear + .070, 0, h * .355), (-1, 0, 0)), "slot")
    ctx.add("case_usb_tongue", rounded_panel(5.6, .63, .069, .29,
            (rear + .040, 0, h * .355), (-1, 0, 0)), "rear_polymer")
    ctx.add("quarter_inch_thread_flange", ring(3.9, 2.20, .075,
            (rear + .0375, 0, h * .195), (-1, 0, 0)), "silver")
    ctx.add("quarter_inch_thread_recess", _disk(2.18, .034,
            (rear + .019, 0, h * .195), (-1, 0, 0)), "gasket")
    for radius in [2.28, 2.55, 2.80]:
        ctx.add("thread_ring_" + str(radius), ring(radius, radius - .085, .035,
                (rear + .020, 0, h * .195), (-1, 0, 0), 64), "rear_polymer")
    ctx.add("closed_base_joint", tube_line([(rear + .095, -13.6, 5.4),
            (rear + .095, 13.6, 5.4)], .09, 10), "subtle_print")
    ctx.add("closed_base_center_joint", tube_line([(rear + .095, 0, 1.1),
            (rear + .095, 0, 5.4)], .09, 10), "subtle_print")


def decorate(ctx):
    """Replace generic geometry for the seven GO camera/accessory assets."""
    if ctx.camera["id"] not in IDS:
        return False
    ctx.parts.clear()
    ctx.surfaces.clear()
    ctx.collision_proxies.clear()
    _palette(ctx, white=ctx.camera["id"] not in {"go_ultra", "go_ultra_action_pod"})
    if ctx.camera["id"] in {"go2", "go3", "go3s"}:
        _capsule(ctx)
    elif ctx.camera["id"] == "go_ultra":
        _ultra(ctx)
    elif ctx.camera["id"] == "go2_charging_case":
        _case(ctx)
    else:
        _pod(ctx)
    return True
