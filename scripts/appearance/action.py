"""Reference-informed Ace and horizontal ONE R/RS exteriors.

The closed camera, with its folded display, is modeled. Fine dimensions are
proportion estimates from manufacturer product photographs and part diagrams;
the nominal envelope remains authoritative. All geometry is authored in mm.
"""
import math

import numpy as np
import trimesh

from .common import (basis, contour, lathe, orient, outline, ring,
                     rounded_panel, screw, text_mesh, tube_line)


IDS = {"ace", "ace_pro", "ace_pro2", "one_r_4k", "one_r_360", "one_r_1inch",
       "one_rs_4k", "one_rs_360", "one_rs_1inch"}


def _frame(width, height, depth, radius, border, center, normal=(1, 0, 0)):
    """Beveled, hollow rounded rectangle: the opening remains actual geometry."""
    b = min(.22, depth * .24, border * .25)
    rows = []
    for w, h, r, z in [
            (width - 2*b, height - 2*b, radius - b, -depth/2),
            (width, height, radius, -depth/2 + b),
            (width, height, radius, depth/2 - b),
            (width - 2*b, height - 2*b, radius - b, depth/2),
            (width - 2*border, height - 2*border, max(.05, radius-border), depth/2),
            (width - 2*border, height - 2*border, max(.05, radius-border), -depth/2)]:
        xy = contour(w, h, max(.05, r), 24)
        rows.append(np.column_stack([xy, np.full(len(xy), z)]))
    vertices = np.vstack(rows)
    n = len(rows[0])
    faces = []
    for j in range(len(rows)):
        k = (j + 1) % len(rows)
        for i in range(n):
            ni = (i + 1) % n
            faces.extend([[j*n+i, j*n+ni, k*n+ni], [j*n+i, k*n+ni, k*n+i]])
    mesh = trimesh.Trimesh(vertices*.001, faces, process=True)
    mesh.fix_normals()
    mesh = trimesh.graph.smooth_shade(mesh, angle=math.radians(35), facet_minarea=None)
    return orient(mesh, center, normal)


def _disk(radius, depth, center, normal=(1, 0, 0), sections=64):
    return lathe([(0, -depth/2), (radius, -depth/2), (radius, depth/2),
                  (0, depth/2)], center, normal, sections)


def _knurled_ring(radius, inner_radius, depth, center, teeth=96):
    """Closed milled filter ring, with a real periodic radial tooth profile."""
    count = teeth*4
    theta = np.linspace(0,math.tau,count,endpoint=False)
    radii = np.tile([radius-.20,radius,radius,radius-.20],teeth)
    rows=[]
    for r,z in [(radii,-depth/2),(radii,depth/2),
                (np.full(count,inner_radius),depth/2),
                (np.full(count,inner_radius),-depth/2)]:
        rows.append(np.column_stack([r*np.cos(theta),r*np.sin(theta),np.full(count,z)]))
    faces=[]
    for j in range(4):
        k=(j+1)%4
        for i in range(count):
            ni=(i+1)%count
            faces.extend([[j*count+i,j*count+ni,k*count+ni],
                          [j*count+i,k*count+ni,k*count+i]])
    mesh=trimesh.Trimesh(np.vstack(rows)*.001,faces,process=True)
    mesh.fix_normals()
    return orient(mesh,center)


def _perforated_panel(width,height,radius,depth,holes,center):
    """Thin sheet with actual through-holes, retaining its acoustic backing."""
    from shapely.geometry import Point,Polygon
    from shapely.ops import unary_union
    sheet=Polygon(contour(width,height,radius,24)*.001)
    cutouts=unary_union([Point(y*.001,z*.001).buffer(r*.001,quad_segs=4)
                        for y,z,r in holes])
    sheet=sheet.difference(cutouts)
    mesh=trimesh.creation.extrude_polygon(sheet,height=depth*.001,engine='earcut')
    return orient(mesh,center)


def _txt(ctx, name, text, height, center, normal=(1, 0, 0), material="markings",
         width=None, angle=0, collision=False):
    ctx.add(name, text_mesh(text, height, .012, center, normal, width, angle), material, collision)


def _arc_txt(ctx, name, text, radius, center, height, start, end, material="markings"):
    meshes=[]
    for char,degrees in zip(text,np.linspace(start,end,len(text))):
        if char == " ":
            continue
        a=math.radians(degrees)
        position=np.asarray(center)+[0,radius*math.cos(a),radius*math.sin(a)]
        angle=a-math.pi/2 if end<start else a+math.pi/2
        meshes.append(text_mesh(char,height,.012,position,angle=angle))
    if meshes:
        ctx.add(name,trimesh.util.concatenate(meshes),material,"front_lens")


def _screw(ctx, name, center, normal=(1, 0, 0), radius=.68):
    ctx.add(name, screw(radius, center, normal), "screw_metal")
    # The separate engraved cross is recessed-color geometry, rather than a
    # featureless dot. Its relief is confined inside the screw head.
    axes = basis(normal)
    center = np.asarray(center) - axes[:, 2]*.012
    for axis in (0, 1):
        points = [center-axes[:, axis]*radius*.56, center+axes[:, axis]*radius*.56]
        ctx.add(name+f"_slot_{axis}", tube_line(points, .035, 6), "seam")


def _side_door(ctx, name, sign, pw, ph, x, z):
    y = sign*(ctx.w/2-.20)
    normal = (0, sign, 0)
    ctx.add(name+"_gasket", rounded_panel(pw, ph, .13, 2.5, (x, y, z), normal), "seam")
    ctx.add(name+"_lid", rounded_panel(pw-.75, ph-.75, .09, 2.25,
            (x, y+sign*.08, z), normal), "rubber")
    latch_z = z+ph*.29
    ctx.add(name+"_latch", rounded_panel(pw*.55, 4.2, .08, .8,
            (x, y+sign*.14, latch_z), normal), "housing")
    for i in range(3):
        ctx.add(name+f"_latch_grip_{i}", rounded_panel(pw*.37, .30, .026, .12,
                (x, y+sign*.187, latch_z+.82-i*.82), normal), "seam")


def _glass_stack(ctx, name, center, radius, normal, max_depth, group):
    """Protective window, separated optical rings, and a shallow optical bowl."""
    ctx.add(name+"_guard", lathe([(radius, .03), (radius, max_depth-.22),
            (radius-.35, max_depth), (radius*.79, max_depth),
            (radius*.78, max_depth-.44), (radius*.83, .04), (radius, .03)],
            center, normal), "lens_ring", group)
    ctx.add(name+"_outer_optical_ring", ring(radius*.79, radius*.68, .13,
            np.asarray(center)+np.asarray(normal)*(max_depth-.16), normal), "seam", group)
    ctx.add(name+"_glass", lathe([(0, max_depth-.55), (radius*.67, max_depth-.55),
            (radius*.67, max_depth-.17), (radius*.55, max_depth-.23),
            (radius*.38, max_depth-.31), (radius*.18, max_depth-.38),
            (0, max_depth-.40)], center, normal), "optical_glass", group)
    ctx.add(name+"_inner_aperture", ring(radius*.29, radius*.14, .045,
            np.asarray(center)+np.asarray(normal)*(max_depth-.12), normal), "optics_black", group)
    ctx.add(name+"_inner_glass", _disk(radius*.14, .024,
            np.asarray(center)+np.asarray(normal)*(max_depth-.095), normal), "optics_coating", group)


def _ace(ctx):
    mid = ctx.camera["id"]
    pro2, pro = mid == "ace_pro2", mid != "ace"
    w, h, d, overall = ctx.w, ctx.h, ctx.d, ctx.overall
    front = ctx.body_front
    rear = -overall/2
    # Folded rear display is a distinct thin assembly, with a perimeter gap.
    shell_d = d-.80
    shell_x = (front+rear+.80)/2
    shell_h = h-.45
    ctx.add("pressure_sealed_body", rounded_panel(w-.45, shell_h, shell_d, 5.5,
            (shell_x, 0, shell_h/2), bevel=1.35), "housing", "body")
    ctx.add("front_molded_plate", rounded_panel(w-1.35, h-2.0, .18, 5.2,
            (front-.015, 0, h/2-.22), bevel=.06), "rubber")
    ctx.add("front_plate_perimeter", outline(w-1.0, h-1.6, 5.4,
            (front+.08, 0, h/2-.22), stroke=.055), "seam")

    # The Ace's smaller screen, position of its red light, and branded screen
    # bezel are deliberately different from both Pro models.
    sw, sh = (21.2, 27.2) if pro else (21.8, 23.0)
    sy, sz = -w*.278, h*.657
    ctx.add("front_lcd_bezel", rounded_panel(sw, sh, .40, 2.6,
            (front+.16, sy, sz)), "seam")
    ctx.add("front_lcd_cover", rounded_panel(sw-1.2, sh-1.3, .10, 2.0,
            (front+.405, sy, sz)), "screen")
    aw, ah = (14.1, 18.8) if pro else (10.0, 13.9)
    az = sz+.75 if pro else sz+2.7
    ctx.add("front_lcd_active", rounded_panel(aw, ah, .025, .55,
            (front+.47, sy+.2 if pro else sy+1.5, az)), "display_black")
    if pro:
        light_center = (front+.50, sy, sz-sh/2+.86)
        ctx.add("front_status_window", rounded_panel(11.7, 1.25, .045, .6,
                light_center), "accent_red")
    else:
        ctx.add("front_status_window", rounded_panel(1.1, 11.8, .045, .48,
                (front+.50, sy-sw*.36, sz+2)), "accent_red")
        _txt(ctx, "front_screen_brand", "Insta360", 2.35,
             (front+.51, sy-2.5, sz-7.4), width=13.8)
        ctx.add("front_ace_badge", rounded_panel(5.7, 2.8, .04, .3,
                (front+.51, sy+7, sz-7.4)), "accent_red")
        _txt(ctx, "front_ace_name", "Ace", 1.92,
             (front+.54, sy+7, sz-7.4), width=5.1)

    lens_y, lens_z = w*.236, h*.660
    cover_size = 33.5 if pro2 else 33.0
    gap = overall/2-front
    ctx.add("removable_lens_guard_base", rounded_panel(cover_size+1.1, cover_size+1.1,
            gap-.58, 6.15, (front+(gap-.58)/2, lens_y, lens_z)), "lens_ring", "front_lens")
    ctx.add("lens_guard_red_surround", _frame(cover_size, cover_size, .46, 5.6, .83,
            (overall/2-.35, lens_y, lens_z)), "accent_red", "front_lens")
    ctx.add("lens_guard_black_inner_surround", _frame(cover_size-1.8, cover_size-1.8,
            .37, 4.8, 1.55, (overall/2-.24, lens_y, lens_z)), "rubber", "front_lens")
    ctx.add("lens_guard_face", rounded_panel(cover_size-5.0, cover_size-5.0,
            .08, 4.0, (overall/2-.17, lens_y, lens_z)), "optics_black", "front_lens")
    # Flat action-camera cover, with the optical pupil visible inside. This
    # replaces the former hemispherical panorama-lens silhouette.
    optical_r = 11.15 if pro else 10.1
    _glass_stack(ctx, "summarit" if pro else "wide_angle",
                 (overall/2-.44, lens_y, lens_z), optical_r, (1, 0, 0), .44, "front_lens")
    if pro:
        _txt(ctx, "leica_lens_mark", "LEICA", 1.42,
             (overall/2-.020, lens_y, lens_z+13.45), width=8.5,collision="front_lens")
        _txt(ctx, "lens_specification", "SUMMARIT 1:2.6 ASPH.", .69,
             (overall/2-.020, lens_y, lens_z-13.48), width=21.5,collision="front_lens")
    else:
        _txt(ctx, "lens_specification", "F2.4 16mm equiv.", .86,
             (front+.12, lens_y+1.4, 10.4), width=20.0, material="muted_markings")
    ctx.surfaces.append((f"{mid}_front_lens_surface",
                         [overall*.0005, lens_y*.001, lens_z*.001], 1))

    if pro2:
        # Closed removable wind guard, in its factory-supplied position. The
        # perforation pattern is geometry, so it survives all mesh formats.
        gy, gz, gw, gh = 18.1, 7.10, 30.7, 10.5
        ctx.add("wind_guard_perimeter", rounded_panel(gw, gh, .28, 3.7,
                (front+.20, gy, gz)), "seam")
        ctx.add("wind_guard_acoustic_foam", rounded_panel(gw-.8,gh-.75,.07,3.3,
                (front+.325,gy,gz)),"seam")
        holes=[]
        for row in range(7):
            z = gz-3.7+row*1.16
            for col in range(23):
                y = gy-12.9+col*1.16+(row%2)*.58
                # Tapered rounded ends match the front shield silhouette.
                if abs(y-gy) > 12.9-abs(z-gz)*.34:
                    continue
                holes.append((y-gy,z-gz,.34))
        ctx.add("wind_guard_perforated_metal", _perforated_panel(gw-.8,gh-.75,3.3,.10,
                holes,(front+.36,gy,gz)),"rubber")
        label_w, label_y, label_z = 33.6, -17.1, 7.05
    elif pro:
        label_w, label_y, label_z = 48.0, -9.8, 5.50
        for i in range(2):
            ctx.add(f"front_mic_{i}", _disk(.54, .025, (front+.125, 10.0+i*1.95, 9.5)), "seam")
        _txt(ctx, "body_lens_specification", "1/1.3 F2.6 16mm", .72,
             (front+.13, 21.2, 9.6), width=18.7, material="muted_markings")
    else:
        label_w = 0
        label_y = label_z = 0
        for i in range(3):
            ctx.add(f"front_mic_{i}", _disk(.47, .025, (front+.125, 8.8+i*2.0, 10.4)), "seam")
    if label_w:
        ctx.add("lower_brand_panel", rounded_panel(label_w, 8.9, .25, 2.4,
                (front+.17, label_y, label_z)), "housing")
        _txt(ctx, "insta360_wordmark", "Insta360", 2.15,
             (front+.31, label_y-label_w*.21, label_z), width=15.3)
        badge_y = label_y+label_w*.13
        ctx.add("ace_red_badge", rounded_panel(6.3, 3.0, .035, .35,
                (front+.325, badge_y, label_z)), "accent_red")
        _txt(ctx, "ace_badge_text", "Ace", 2.05,
             (front+.35, badge_y, label_z), width=5.4)
        _txt(ctx, "pro_model_text", "Pro 2" if pro2 else "Pro", 2.13,
             (front+.35, badge_y+8.0, label_z), width=7.1)

    fh = 43.0 if pro2 else 41.6
    fz = 2.2+fh/2
    ctx.add("folded_flip_screen_frame", rounded_panel(w-2.3, fh, .66, 3.5,
            (rear+.40, 0, fz), (-1,0,0)), "seam")
    ctx.add("flip_screen_cover_glass", rounded_panel(w-4.4, fh-2.1, .075, 2.5,
            (rear+.045, 0, fz), (-1,0,0)), "screen")
    ctx.add("flip_screen_active_area", rounded_panel(w-9.0, fh-6.1, .020, 1.35,
            (rear+.010, 0, fz+.15), (-1,0,0)), "display_black")
    ctx.add("display_frame_lower_mark", text_mesh("Insta360", 1.18, .012,
            (rear+.020, 0, fz-fh/2+1.25), (-1,0,0), width=9.0), "muted_markings")
    for side in (-1, 1):
        ctx.add(f"flip_hinge_{side}", _disk(1.85, 9.8,
                (rear+2.0, side*w*.285, h-2.25), (0,1,0)), "lens_ring")
        _side_door(ctx, "battery_door" if side == 1 else "usb_sd_door", side,
                   min(d-5.0, 24.5), 29.0, shell_x, h*.43)
        ctx.add(f"display_release_button_{side}", rounded_panel(6.4, 3.2, .14, .8,
                (rear+3.3, side*(w/2-.085), h*.75), (0,side,0)), "rubber")
    # Shutter and side power switch sit in recesses inside the source envelope.
    ctx.add("shutter_button_gasket", rounded_panel(14.2, 8.2, .14, 2.0,
            (shell_x, -w*.27, h-.35), (0,0,1)), "seam")
    ctx.add("shutter_button", rounded_panel(12.5, 6.7, .18, 1.6,
            (shell_x, -w*.27, h-.09), (0,0,1)), "rubber")
    ctx.add("shutter_record_symbol", ring(1.50, 1.17, .015,
            (shell_x, -w*.27, h-.008), (0,0,1), 48), "muted_markings")
    for side in (-1, 1):
        ctx.add(f"bottom_mount_latch_{side}", rounded_panel(5.8, 2.8, .14, .65,
                (shell_x-.6, side*(w/2-.12), 3.8), (0,side,0)), "rubber")
    for i, (y,z) in enumerate([(-w*.44, 5.0), (w*.44, 5.0)]):
        _screw(ctx, f"lower_face_screw_{i}", (front+.11,y,z), radius=.53)


def _modular(ctx):
    mid = ctx.camera["id"]
    rs, dual, inch = mid.startswith("one_rs_"), mid.endswith("_360"), mid.endswith("_1inch")
    w, h, overall = ctx.w, ctx.h, ctx.overall
    # The ONE RS boosted battery is taller than the original ONE R base; the
    # large 1-inch lens extends above the otherwise unchanged core module.
    bh = (14.1 if rs else 13.0) if inch else h-35.0
    main_h = 35.0
    core_d = min(27.4 if rs else 26.0, overall-.8)
    bx = 0 if dual else -overall/2+core_d/2
    front, rear = bx+core_d/2, bx-core_d/2
    split = -.8 if not inch else -4.9
    core_w = split+w/2-.26
    core_y = -w/2+core_w/2
    mod_right = w/2-(8.2 if inch else 0)
    mod_w = mod_right-split-.26
    mod_y = split+.26+mod_w/2
    mz = bh+main_h/2
    ctx.add("red_battery_base", rounded_panel(w if not inch else w-2.2, bh-.16,
            core_d-.12, min(2.2,bh*.2), (bx, 0 if not inch else -1.1, (bh-.16)/2)),
            "modular_battery", "body")
    # Actual part separation: three closed solids, not a seam painted on a
    # continuous housing. Independent collision groups retain the joint gap.
    ctx.add("core_module", rounded_panel(core_w-.24, main_h-.35, core_d-.30, 2.3,
            (bx, core_y, mz-.18)), "housing", "core")
    ctx.add("lens_module", rounded_panel(mod_w, main_h-.35, core_d-.34, 2.25,
            (bx, mod_y, mz-.18)), "rubber", "lens_module")
    ctx.add("battery_interface_gasket", rounded_panel(w-.55 if not inch else w-2.75,
            .34, core_d-.40, .14, (bx, 0 if not inch else -1.1, bh)), "seam")
    ctx.add("core_front_skin", rounded_panel(core_w-.65, main_h-1.15, .13, 2.0,
            (front-.06, core_y, mz-.18)), "rubber")
    ctx.add("lens_front_skin", rounded_panel(mod_w-.65, main_h-1.15, .13, 2.0,
            (front-.06, mod_y, mz-.18)), "housing")
    ctx.add("core_back_skin", rounded_panel(core_w-.65, main_h-1.15, .13, 2.0,
            (rear+.08, core_y, mz-.18), (-1,0,0)), "rubber")
    ctx.add("lens_back_skin", rounded_panel(mod_w-.65, main_h-1.15, .13, 2.0,
            (rear+.08, mod_y, mz-.18), (-1,0,0)), "housing")
    _txt(ctx, "core_model_label", "ONE RS" if rs else "ONE R", 2.4,
         (front+.028, core_y+.2, bh+29.0), width=15.8)
    ctx.add("core_front_status", _disk(.75, .023, (front+.045, core_y-core_w*.32, bh+29.0)), "status")
    # Core front speaker differs between R and RS generations.
    if rs:
        ctx.add("core_speaker_surround", rounded_panel(core_w*.68, 2.0, .08, .9,
                (front+.035, core_y, bh+6.1)), "seam")
        for i in range(4):
            ctx.add(f"core_speaker_hole_{i}", _disk(.32, .016,
                    (front+.086, core_y+core_w*.23-i*1.4, bh+6.1), sections=24), "optics_black")
    else:
        for i in range(3):
            mesh = rounded_panel(4.2-i*.56, .72, .018, .33,
                    (front+.04, core_y+core_w*.31+i*.75, bh+5.8-i*.50))
            matrix = trimesh.transformations.rotation_matrix(-.76, [1,0,0],
                    [front*.001,(core_y+core_w*.31+i*.75)*.001,(bh+5.8-i*.50)*.001])
            mesh.apply_transform(matrix)
            ctx.add(f"core_diagonal_speaker_slot_{i}", mesh, "seam")

    # Rear display belongs to the Core only, occupying roughly one module.
    sw, sh = core_w*.77, 24.0
    ctx.add("core_rear_screen_frame", rounded_panel(core_w-.7, 32.4, .16, 2.2,
            (rear+.20, core_y, mz), (-1,0,0)), "seam")
    ctx.add("core_rear_screen_glass", rounded_panel(sw+1.2, sh+1.5, .05, 1.45,
            (rear+.112, core_y-.7, mz+.1), (-1,0,0)), "screen")
    ctx.add("core_rear_screen_active", rounded_panel(sw, sh, .014, .7,
            (rear+.083, core_y-.7, mz+.1), (-1,0,0)), "display_black")
    ctx.add("core_rear_status_window", rounded_panel(2.6, .65, .012, .25,
            (rear+.080, core_y+core_w*.27, bh+32), (-1,0,0)), "status")
    _txt(ctx, "core_zoom_indicator", "Q", 1.2,
         (rear+.075, core_y-core_w*.40, bh+25), (-1,0,0), width=1.6, material="muted_markings")

    lens_y = mod_y if not inch else w/2-21.5
    if dual:
        r, lens_z = min(mod_w*.41,14.1), bh+17.2
        # 360 module has a rounded square pressure housing plus two curved
        # opposing fisheye glass elements. No full-camera-width display.
        for sign in (-1,1):
            face = sign*core_d/2
            prot = overall/2-core_d/2
            normal = (sign,0,0)
            center = (face,lens_y,lens_z)
            ctx.add(f"360_square_guard_{sign}", _frame(mod_w-1.7,31.7,.33,2.5,.67,
                    (face+sign*.025,mod_y,mz),normal), "lens_ring", f"lens_{sign}")
            ctx.add(f"360_annular_ring_{sign}", lathe([(r,0),(r,.36),(r-.42,.64),
                    (r-.85,.70),(r-1.18,.50),(r-1.18,0),(r,0)], center,normal),
                    "lens_ring", f"lens_{sign}")
            cap=[(0,.42),(r-1.12,.42)]
            for t in np.linspace(0,1,22):
                cap.append(((r-1.12)*math.cos(t*math.pi/2), .50+(prot-.50)*math.sin(t*math.pi/2)))
            ctx.add(f"360_fisheye_glass_{sign}", lathe(cap,center,normal,160),
                    "optical_glass", f"lens_{sign}")
            ctx.surfaces.append((f"{mid}_{'front' if sign==1 else 'rear'}_lens_surface",
                                 [sign*overall*.0005,lens_y*.001,lens_z*.001],sign))
    elif inch:
        r, lens_z = 21.5, h-21.5
        prot=overall/2-front
        ctx.add("one_inch_barrel", lathe([(r*.90,0),(r*.96,prot*.26),(r,prot*.65),
                (r,prot-.50),(r-.45,prot),(r-.70,prot-.05),
                (r*.74,prot-.05),(r*.74,0),(r*.90,0)],
                (front,lens_y,lens_z)), "lens_ring", "front_lens")
        # Fine milled teeth on the outer protective filter ring.
        ctx.add("one_inch_filter_knurl",_knurled_ring(r-.03,r-.55,1.35,
                (overall/2-.75,lens_y,lens_z)),"rubber","front_lens")
        _glass_stack(ctx,"one_inch_optical",(overall/2-.42,lens_y,lens_z),r*.74,
                     (1,0,0),.42,"front_lens")
        _arc_txt(ctx,"leica_wordmark","LEICA",r*.86,(overall/2-.020,lens_y,lens_z),1.85,108,72)
        _arc_txt(ctx,"one_inch_lens_engraving","SUPER ELMAR-A 1:3.2",r*.86,
             (overall/2-.020,lens_y,lens_z),1.10,230,310,material="muted_markings")
        ctx.surfaces.append((f"{mid}_front_lens_surface",
                             [overall*.0005,lens_y*.001,lens_z*.001],1))
    else:
        lens_z = bh+17.45
        prot = overall/2-front
        cover=31.2 if rs else 29.8
        ctx.add("4k_square_lens_guard", rounded_panel(cover,cover,prot-.17,3.3,
                (front+(prot-.17)/2,lens_y,lens_z)),"lens_ring","front_lens")
        ctx.add("4k_guard_edge",_frame(cover-.40,cover-.40,.24,3.05,.67,
                (overall/2-.13,lens_y,lens_z)),"rubber","front_lens")
        ctx.add("4k_guard_window",rounded_panel(cover-2.5,cover-2.5,.035,2.3,
                (overall/2-.05,lens_y,lens_z)),"optics_black","front_lens")
        _glass_stack(ctx,"4k_boost" if rs else "4k_wide",(overall/2-.35,lens_y,lens_z),
                     13.0 if rs else 11.4,(1,0,0),.35,"front_lens")
        _txt(ctx,"4k_lens_label","4K BOOST" if rs else "4K WIDE",.74,
             (overall/2-.020,lens_y,lens_z-cover*.445),width=12.5,
             material="muted_markings",collision="front_lens")
        ctx.surfaces.append((f"{mid}_front_lens_surface",
                             [overall*.0005,lens_y*.001,lens_z*.001],1))

    # The original and boosted Core have visibly different top controls.
    top = bh+main_h
    for name,y,pw in [("shutter",core_y-core_w*.20,10.6),("power",core_y+core_w*.24,6.2)]:
        ctx.add(name+"_button_recess",rounded_panel(pw+1.0,7.5,.10,1.8,
                (bx,y,top-.18),(0,0,1)),"seam")
        ctx.add(name+"_button",rounded_panel(pw,6.4,.12,1.3,
                (bx,y,top-.060),(0,0,1)),"rubber")
        if name=="shutter":
            ctx.add("record_button_symbol",ring(1.6,1.25,.015,(bx,y,top-.008),(0,0,1),48),"markings")
    # Side door references a closed microSD / USB-C compartment, with its lock.
    normal=(0,-1,0)
    ctx.add("core_usb_door_gasket",rounded_panel(core_d*.68,23.0,.10,1.6,
            (bx,-w/2+.09,bh+16),(0,-1,0)),"seam")
    ctx.add("core_usb_door",rounded_panel(core_d*.68-.65,22.3,.07,1.35,
            (bx,-w/2+.035,bh+16),normal),"rubber")
    ctx.add("core_usb_door_lock",rounded_panel(8.3,3.4,.025,.75,
            (bx,-w/2+.016,bh+11.8),normal),"housing")
    for i in range(3):
        ctx.add(f"core_door_lock_grip_{i}",rounded_panel(5.5,.26,.015,.11,
                (bx,-w/2+.013,bh+11.0+i*.65),normal),"seam")
    ctx.add("red_battery_release",rounded_panel(12.0,4.1,.075,.7,
            (rear+.0375,core_y,bh*.53),(-1,0,0)),"rubber")
    _txt(ctx,"battery_wordmark","Insta360",1.35,
         (front+.018,0,bh*.48),width=13.4,material="muted_markings")
    for i,y in enumerate((core_y-core_w*.30,core_y+core_w*.30)):
        _screw(ctx,f"core_front_lower_screw_{i}",(front+.028,y,bh+2.2),radius=.45)


def decorate(ctx):
    """Replace this family's generic geometry and report whether handled."""
    if ctx.camera["id"] not in IDS:
        return False
    ctx.parts.clear()
    ctx.surfaces.clear()
    if hasattr(ctx, "collision_proxies"):
        ctx.collision_proxies.clear()
    ctx.colors.update({
        "housing": [.12,.125,.13,1], "rubber": [.068,.072,.076,1],
        "lens_ring": [.21,.215,.22,1], "seam": [.018,.020,.022,1],
        "screen": [.037,.043,.047,1], "display_black": [.010,.013,.015,1],
        "optics_black": [.022,.025,.026,1], "optical_glass": [.026,.045,.042,1],
        "optics_coating": [.033,.059,.078,1],
        "accent_red": [.86,.075,.105,1], "modular_battery": [.75,.047,.065,1],
        "markings": [.72,.73,.73,1], "muted_markings": [.36,.38,.39,1],
        "screw_metal": [.19,.20,.21,1], "status": [.13,.50,.57,1],
    })
    if hasattr(ctx,"materials"):
        ctx.materials.update({"housing":{"roughnessFactor":.56},
            "rubber":{"roughnessFactor":.76},
            "screen":{"roughnessFactor":.12},
            "display_black":{"roughnessFactor":.17},
            "optical_glass":{"roughnessFactor":.095,"metallicFactor":.15},
            "optics_coating":{"roughnessFactor":.085,"metallicFactor":.40},
            "accent_red":{"roughnessFactor":.32},
            "lens_ring":{"roughnessFactor":.32,"metallicFactor":.35}})
    if ctx.camera["id"].startswith("ace"):
        _ace(ctx)
    else:
        _modular(ctx)
    return True
