"""Distinct RealSense, ZED and original OAK-D exterior assemblies.

Layout is referenced to manufacturer imagery and drawings, not optical calibration.
"""
import math
import numpy as np
import trimesh
from .common import rounded_panel, lathe, ring, outline, text_mesh, tube_line, frame_ring, screw


def _label(ctx,name,text,size,center,normal=(1,0,0),width=None,material='markings'):
    ctx.add(name,text_mesh(text,size,.012,center,normal,width=width),material)


def _optics(ctx,name,y,z,r,front,group='body'):
    # A mechanical lip, rubber seat, inner optical barrel and subtly curved
    # coated front element; separate surfaces make reflections meaningful.
    ctx.add(name+'_seat',lathe([(0,-.08),(r,-.08),(r,0),(0,0)],(front-.10,y,z)),'seam',group)
    ctx.add(name+'_outer_ring',ring(r,r*.82,.12,(front-.04,y,z)),'lens_ring',group)
    ctx.add(name+'_inner_barrel',ring(r*.81,r*.53,.10,(front-.045,y,z)),'rubber',group)
    ctx.add(name+'_coating_ring',ring(r*.59,r*.52,.04,(front+.005,y,z)),'glass_coating',group)
    profile=[(0,-.07),(r*.52,-.07),(r*.52,0)]
    profile += [(r*.52*math.cos(t),.03*math.sin(t)) for t in np.linspace(0,math.pi/2,14)[1:]]
    ctx.add(name+'_optical_element',lathe(profile,(front+.008,y,z)),'optical_glass',group)
    ctx.surfaces.append((f"{ctx.camera['id']}_{name}_lens_surface",[(front+.038)*.001,y*.001,z*.001],1))


def _fastener(ctx,name,center,normal=(1,0,0),radius=1.05,group='body'):
    ctx.add(name+'_recess',lathe([(0,-.03),(radius*1.22,-.03),(radius*1.22,0),(0,0)],center,normal,48),'seam',group)
    ctx.add(name+'_head',screw(radius,np.asarray(center)+np.asarray(normal)*.009,normal),'screw_metal',group)
    # A dark cross is readable in both GLB and color-only simulator import.
    center=np.asarray(center)+np.asarray(normal)*.012
    for j,(w,h) in enumerate(((radius*1.05,.15),(.15,radius*1.05))):
        ctx.add(name+f'_drive_{j}',rounded_panel(w,h,.006,.05,center,normal),'seam',group)


def _rear_port(ctx,y,z,width=9,height=3.2,locking=False):
    back=ctx.body_x-ctx.d/2
    ctx.add('usb_c_well',rounded_panel(width+2,height+2,.08,2,(back+.05,y,z),(-1,0,0)),'seam')
    ctx.add('usb_c_liner',frame_ring(width,height,.10,1.4,.38,(back+.065,y,z),(-1,0,0)),'screw_metal')
    ctx.add('usb_c_tongue',rounded_panel(width*.69,.7,.07,.25,(back+.045,y,z),(-1,0,0)),'rubber')
    for j in range(10):
        ctx.add(f'usb_contact_{j}',rounded_panel(.16,.36,.03,.02,(back+.02,y-width*.28+j*width*.062,z),(-1,0,0)),'contact_gold')
    if locking:
        for side in (-1,1):_fastener(ctx,f'usb_lock_{side}',(back+.02,y+side*(width/2+4),z),(-1,0,0),.8)


def decorate(ctx):
    ident=ctx.camera['id']
    if ident not in ('realsense_d435i','realsense_d455','zed2i','oak_d'):return False
    ctx.parts.clear();ctx.surfaces.clear();ctx.collision_proxies.clear()
    ctx.colors.update(housing=[.19,.195,.20,1],aluminum=[.69,.70,.71,1],
        seam=[.008,.009,.012,1],rubber=[.027,.029,.032,1],lens_ring=[.14,.15,.17,1],
        optical_glass=[.021,.035,.044,1],glass_coating=[.075,.09,.125,1],
        markings=[.74,.75,.76,1],screw_metal=[.31,.32,.34,1],contact_gold=[.64,.48,.20,1],
        status_blue=[.025,.16,.45,1])
    ctx.materials['optical_glass']={'roughnessFactor':.045,'metallicFactor':.12}
    ctx.materials['aluminum']={'roughnessFactor':.34,'metallicFactor':.82}
    w,h,d=ctx.w,ctx.h,ctx.d
    front=ctx.body_front
    if ident=='oak_d':
        # Capsule camera bar and the processing stem preserve the characteristic
        # T silhouette. The two convex collision groups retain the lower voids.
        bar_z=h-12
        ctx.add('cast_camera_bar',rounded_panel(w,24,d-.20,11.8,(-.1,0,bar_z),bevel=1.1),'housing','body_bar')
        ctx.add('cast_processor_stem',rounded_panel(50,h-21,d-.20,5.5,(-.1,0,(h-21)/2),bevel=1.1),'housing','body_stem')
        ctx.add('camera_bar_gasket',outline(w-2,22,10.8,(front-.24,0,bar_z),stroke=.13),'seam','body_bar')
        ctx.add('camera_bar_front_glass',rounded_panel(w-20,18.5,.11,8.8,(front-.18,0,bar_z)),'seam','body_bar')
        for name,y,r in [('left',-37.5,3.9),('rgb',0,3.3),('right',37.5,3.9)]:
            _optics(ctx,name,y,bar_z,r,front-.038,'body_bar')
        for side in (-1,1):
            _fastener(ctx,f'front_bar_screw_{side}',(front-.025,side*(w/2-6),bar_z),radius=1.3,group='body_bar')
            _fastener(ctx,f'front_stem_screw_{side}',(front-.025,side*18,6),radius=1.3,group='body_stem')
        back=-d/2
        ctx.add('back_processor_cover',rounded_panel(45,h-25,.10,3.8,(back+.055,0,(h-25)/2),(-1,0,0)),'housing','body_stem')
        _label(ctx,'rear_luxonis_brand','LUXONIS',3,(back+.015,0,18),(-1,0,0),width=31)
        _rear_port(ctx,0,10)
        for side in (-1,1):_fastener(ctx,f'rear_screw_{side}',(back+.02,side*18,5),(-1,0,0),1.1,group='body_stem')
    else:
        silver=ident.startswith('realsense')
        material='aluminum' if silver else 'housing'
        ctx.colors['housing']=[.075,.080,.087,1] if ident=='zed2i' else [.69,.70,.71,1]
        radius=h/2-.3
        ctx.add('extruded_alloy_shell',rounded_panel(w,h,d-.30,radius,(ctx.body_x-.15,0,h/2),bevel=1.15),material)
        ctx.add('front_surround',frame_ring(w-.9,h-.9,.14,radius-.45,1.3,(front-.14,0,h/2)),material)
        ctx.add('front_optical_mask',rounded_panel(w-4.3,h-4.3,.13,radius-2.15,(front-.17,0,h/2)),'seam')
        ctx.add('rear_cover',rounded_panel(w-1.1,h-1.1,.13,radius-.55,(ctx.body_x-d/2+.09,0,h/2),(-1,0,0)),material)
        ctx.add('rear_cover_seal',outline(w-1.3,h-1.3,radius-.65,(ctx.body_x-d/2+.09,0,h/2),(-1,0,0),.075),'seam')
        if ident=='realsense_d455':
            positions=[('left',-47.5,5.55),('projector',-12.0,5.5),('rgb',9.0,6.5),('right',47.5,5.55)]
            for name,y,r in positions:
                if name=='rgb':
                    ctx.add('rgb_flat_window_housing',rounded_panel(18,13.4,.09,5.8,(front-.078,y,h/2)),'rubber')
                _optics(ctx,name,y,h/2,r,front-.038)
        elif ident=='realsense_d435i':
            positions=[('left',-25,4.4),('projector',-10,4.35),('right',25,4.4),('rgb',9.5,3.3)]
            for name,y,r in positions:_optics(ctx,name,y,h/2,r,front-.038)
        else:
            for name,y in [('left',-60),('right',60)]:_optics(ctx,name,y,h/2,9.5,front-.038)
            _label(ctx,'front_zed_logo','ZED',3.3,(front-.075,38,h/2),width=12,material='markings')
            ctx.add('blue_status_led',lathe([(0,-.02),(.62,-.02),(.62,0),(0,0)],(front-.06,28,h/2),segments=48),'status_blue')
        back=ctx.body_x-d/2
        for side in (-1,1):
            for z in (7,h-7):_fastener(ctx,f'rear_m3_{side}_{z}',(back+.02,side*(w/2-10),z),(-1,0,0),1.12)
        _rear_port(ctx,0,h/2,locking=ident=='zed2i')
        _label(ctx,'rear_brand','STEREOLABS' if ident=='zed2i' else 'RealSense',2.8,
               (back+.014,35 if ident=='zed2i' else w*.27,h/2),(-1,0,0),width=w*.31)
        # Threaded mounting sockets appear on the bottom surface, not as bolts.
        for j,y in enumerate((-w*.30,0,w*.30)):
            r=3.0 if y==0 else 1.9
            ctx.add(f'bottom_socket_{j}',ring(r,r*.70,.08,(ctx.body_x,y,.05),(0,0,-1)),'screw_metal')
            ctx.add(f'bottom_thread_shadow_{j}',lathe([(0,-.015),(r*.69,-.015),(r*.69,0),(0,0)],(ctx.body_x,y,.015),(0,0,-1),48),'seam')
    ctx.camera.setdefault('appearance_sources',[])
    return True
