"""Distinct X-series exteriors reconstructed from manufacturer product views.

Nominal dimensions and published display sizes are respected. Small features,
shell profiles, lens radii and mounting details remain independent estimates.
All authoring dimensions below are millimeters; common returns meter meshes.
"""
import math
import numpy as np
import trimesh
from .common import (basis, contour, lathe, orient, outline, rounded_panel, ring,
                     text_mesh, tube_line)


MODEL_IDS = {'x6', 'x4_air', 'x4', 'x3', 'one_x2', 'one_x', 'one_rs_1inch360'}
REFERENCE_SOURCES = {
    'x6': 'https://onlinemanual.insta360.com/x6/en-us/camera/product-introduction/insta360-x6',
    'x4_air': 'https://onlinemanual.insta360.com/x4air/en-us/camera/product-description/introduction',
    'x4': 'https://onlinemanual.insta360.com/x4/en-us/camera/productdescription/first',
    'x3': 'https://onlinemanual.insta360.com/x3/en-us/camera/firstuse/introduction',
    'one_x2': 'https://res.insta360.com/static/infr_base/9773c6759c7837738db3dca3c0518376/ONE%20X2%20QuickStart%20Guide.pdf',
    'one_x': 'https://www.insta360.com/product/insta360-onex',
    'one_rs_1inch360': 'https://www.insta360.com/product/insta360-oners/1inch-360',
}

# Model-specific placement read from orthographic manufacturer diagrams. The
# touchscreen extents of X6/Air/X4/X3 and X2 diameter are published dimensions.
DESIGNS = {
    'x6': dict(radius=6.2, lens_r=17.6, lens_z=.790, display=(36.86,46.08), display_z=.290),
    'x4_air': dict(radius=7.0, lens_r=16.0, lens_z=.827, display=(31.4,42.7), display_z=.403),
    'x4': dict(radius=7.0, lens_r=16.6, lens_z=.831, display=(33.9,53.7), display_z=.377),
    'x3': dict(radius=7.3, lens_r=14.9, lens_z=.835, display=(34.16,47.27), display_z=.375),
    'one_x2': dict(radius=8.8, lens_r=14.5, lens_z=.833, display_z=.474),
    'one_x': dict(radius=9.0, lens_r=14.6, lens_z=.827, display_z=.579),
    'one_rs_1inch360': dict(radius=6.0, lens_r=21.1, lens_z=.798, display=(30.1,26.3), display_z=.485),
}


def _panel(ctx, name, width, height, depth, radius, center, normal=(1,0,0), material='housing', collision=False):
    ctx.add(name, rounded_panel(width,height,depth,radius,center,normal),material,collision)


def _disc(ctx, name, radius, center, normal=(1,0,0), material='seam', depth=.06):
    ctx.add(name, lathe([(0,-depth/2),(radius,-depth/2),(radius,depth/2),(0,depth/2)],center,normal,64),material)


def _label(ctx, name, text, size, center, normal=(1,0,0), width=None, angle=0, material='marking'):
    ctx.add(name,text_mesh(text,size,.012,center,normal,width,angle),material)


def _seam(ctx, name, width, height, radius, center, normal=(1,0,0), stroke=.07):
    ctx.add(name,outline(width,height,radius,center,normal,stroke),'seam')


def _power_icon(ctx,name,center,normal,size=2.0):
    u,v,n=basis(normal).T
    c=np.asarray(center)
    points=[c+u*size*.41*math.cos(t)+v*size*.41*math.sin(t)
            for t in np.linspace(math.pi*.72,math.pi*2.28,13)]
    ctx.add(name+'_arc',tube_line(points,.08),'marking_dark')
    ctx.add(name+'_stroke',tube_line([c+v*size*.1,c+v*size*.62],.09),'marking_dark')


def _grille(ctx,name,width,height,center,normal=(1,0,0),rounded=True,pitch=.85,hexagonal=False):
    """A grille panel and individually modeled perforation mouths, never a decal."""
    shape=None
    if hexagonal:
        from shapely.geometry import Polygon
        shape=Polygon([(-width/2,height*.15),(-width*.33,height/2),(width*.33,height/2),
                       (width/2,height*.15),(width*.28,-height/2),(-width*.28,-height/2)])
        from shapely.affinity import scale
        panel=trimesh.creation.extrude_polygon(scale(shape,xfact=.001,yfact=.001,origin=(0,0)),height=.08*.001,engine='earcut')
        panel.apply_translation([0,0,-.04*.001])
        ctx.add(name+'_frame',orient(panel,center,normal),'rubber')
    else:
        _panel(ctx,name+'_frame',width+.65,height+.65,.08,min(2,height/3),center,normal,'rubber')
    u,v,n=basis(normal).T
    meshes=[]
    for row,z in enumerate(np.arange(-height/2+.6,height/2-.4,pitch)):
        for y in np.arange(-width/2+.6,width/2-.4,pitch):
            yy=y+(row%2)*pitch/2
            if shape is not None:
                from shapely.geometry import Point
                if not shape.buffer(-.48).contains(Point(yy,z)):continue
            if rounded and (abs(yy)>width/2-1.1 and abs(z)>height/2-1.2):continue
            p=np.asarray(center)+u*yy+v*z+n*.051
            meshes.append(lathe([(.16,-.02),(.16,.015)],p,normal,12))
    if meshes:ctx.add(name+'_perforations',trimesh.util.concatenate(meshes),'aperture')


def _ribs(ctx,name,width,height,center,normal=(1,0,0),pitch=1.25,angle=math.pi/4):
    from shapely.geometry import Polygon,LineString
    shape=Polygon(contour(width,height,min(5,width*.12,height*.12),20))
    c=np.asarray(center);u,v,n=basis(normal).T
    vec=np.array([math.cos(angle),math.sin(angle)])
    perpendicular=np.array([-vec[1],vec[0]])
    meshes=[]
    length=max(width,height)*2
    for offset in np.arange(-length,length,pitch):
        middle=perpendicular*offset
        clipped=shape.intersection(LineString([middle-vec*length,middle+vec*length]))
        if clipped.is_empty:continue
        if clipped.geom_type=='LineString':
            points=[c+u*p[0]+v*p[1] for p in clipped.coords]
            meshes.append(tube_line(points,.055,6))
    if meshes:ctx.add(name,trimesh.util.concatenate(meshes),'grip_ridge')


def _body(ctx,design):
    w,h,d=ctx.w,ctx.h,ctx.d;r=design['radius']
    # Separate smooth shell, gasket and inset face skins give an actual edge
    # highlight and leave room for displays without coplanar depth artifacts.
    if ctx.camera['id']=='one_rs_1inch360':
        for name,width,height,z,radius in [('lens_head_shell',w,h*.385,h*.8075,6.0),
                ('rs_core_shell',w*.86,h*.285,h*.4775,3.2),
                ('vertical_battery_shell',w*.90,h*.345-.12,h*.1725+.06,5.0)]:
            _panel(ctx,name,width,height,d-.34,radius,(0,0,z),
                   material='housing_lens_head' if name=='lens_head_shell' else 'housing',collision='body')
    else:
        # Keep the structural side walls recessed by 0.14 mm. Side details then
        # have real visible relief while their furthest faces stay in W x H x D.
        _panel(ctx,'housing_shell',w-.28,h-.12,d-.34,r,(0,0,(h+.12)/2),collision='body')
    for sign in (-1,1):
        if ctx.camera['id']=='one_rs_1inch360':
            for name,width,height,z,radius in [('head',w-.65,h*.385-.4,h*.8075,5.7),
                    ('core',w*.86-.4,h*.285-.4,h*.4775,3.0),
                    ('battery',w*.90-.4,h*.345-.4,h*.1725,4.7)]:
                _panel(ctx,f'{name}_face_{sign}',width,height,.12,radius,
                       (sign*(d/2-.18),0,z),(sign,0,0),'housing_lens_head' if name=='head' else 'housing_face','body')
                _seam(ctx,f'{name}_face_joint_{sign}',width-.3,height-.3,radius-.1,
                      (sign*(d/2-.10),0,z),(sign,0,0),.04)
        else:
            _panel(ctx,f'face_molding_{sign}',w-.65,h-.65,.12,r-.3,
                   (sign*(d/2-.18),0,h/2),(sign,0,0),'housing_face', 'body')
            _seam(ctx,f'face_joint_{sign}',w-1.1,h-1.1,r-.5,
                  (sign*(d/2-.10),0,h/2),(sign,0,0),.045)
            ctx.add(f'edge_molding_{sign}',outline(w-.10,h-.10,r-.05,
                (sign*(d/2-.165),0,h/2),(sign,0,0),stroke=.05),'housing_face')
    # The bottom plate has a real opening. Raising the structural shell 0.12 mm
    # leaves a shallow blind threaded well without changing the bottom origin.
    # This still describes an estimated interface, not a metrology-grade mate.
    from shapely.geometry import Polygon,Point
    bottom=Polygon(contour(d-2.0,w-3.0,3.0)*.001).difference(Point(0,0).buffer(3.28*.001,quad_segs=32))
    base=trimesh.creation.extrude_polygon(bottom,height=.12*.001,engine='earcut')
    ctx.add('mount_base',base,'rubber','body')
    ctx.add('mount_insert_rim',ring(3.25,2.72,.11,(0,0,.055),(0,0,-1),96),'mount_metal')
    _disc(ctx,'mount_insert_recess',2.70,(0,0,.114),(0,0,-1),'aperture',.008)
    for z in (.025,.052,.079):
        ctx.add(f'mount_thread_{z}',ring(2.73,2.59,.013,(0,0,z),(0,0,-1),64),'mount_metal')
    for y in (-w*.25,w*.25):
        _panel(ctx,f'mount_locator_{y}',3.2,5.3,.025,.5,(0,y,.013),(0,0,-1),'seam')
    if ctx.camera['id'] in ('x6','x4_air'):
        for x in (-d*.24,d*.24):
            for y in (-w*.25,w*.25):
                _panel(ctx,f'quick_mount_{x}_{y}',3.2,4.2,.025,.6,(x,y,.013),(0,0,-1),'aperture')
        if ctx.camera['id']=='x6':
            for y in (-1.5,0,1.5):_disc(ctx,f'connector_pin_{y}',.55,(d*.22,y,.008),(0,0,-1),'mount_metal',.015)


def _lens(ctx,design):
    ident=ctx.camera['id'];r=design['lens_r'];z=ctx.h*design['lens_z'];p=(ctx.overall-ctx.d)/2
    for sign in (-1,1):
        name='front_lens' if sign==1 else 'rear_lens';normal=(sign,0,0);center=(sign*ctx.d/2,0,z)
        # A bevel, shallow barrel, locking rim and separate retaining line.
        radial=[(r*.90,-.13),(r*.97,-.02),(r,p*.08),(r,p*.14),
                (r*.985,p*.21),(r*.94,p*.28),(r*.88,p*.30)]
        ctx.add(name+'_barrel',lathe(radial,center,normal),'lens_barrel',name)
        ctx.add(name+'_rim',ring(r*.938,r*.90,.07,(sign*(ctx.d/2+p*.282),0,z),normal,128),'lens_ring',name)
        ctx.add(name+'_retaining_groove',ring(r*.90,r*.867,.03,(sign*(ctx.d/2+p*.301),0,z),normal,128),'seam',name)
        # Three curved optical zones preserve the same cap and nominal apex,
        # showing a dark pupil and subtle anti-reflection coating as geometry.
        glass_r=r*.867
        def cap(radius):return p*(.31+.69*math.sqrt(max(0,1-(radius/glass_r)**2)))
        for label,lo,hi,mat in [('outer',.60,1.0,'glass_outer'),('coating',.24,.60,'glass_coating'),('pupil',0,.24,'optical_glass')]:
            radii=np.linspace(glass_r*hi,glass_r*lo,24)
            profile=[(rr,cap(rr)) for rr in radii]
            ctx.add(name+'_'+label,lathe(profile,center,normal,128),mat,name)
        for fraction in (.62,.76):
            rr=glass_r*fraction;offset=cap(rr)-.022
            ctx.add(name+f'_coating_edge_{fraction}',ring(rr+.024,rr-.024,.025,
                    (sign*(ctx.d/2+offset),0,z),normal,128),'coating_edge',name)
        if ident in ('x6','x4_air'):
            # Replacement ring alignment dot and six molded locking flats.
            # Follow the outward barrel surface and clear the retaining rim.
            # Intermediate rings keep the paint mesh on the two cone slopes.
            dot_radii=np.linspace(0,.48,13)
            dot_profile=[(rr,-.02) for rr in dot_radii]+[(rr,.02) for rr in dot_radii[::-1]]
            dot=lathe(dot_profile,
                (sign*ctx.d/2,r*.969*math.cos(-.7),z+r*.969*math.sin(-.7)),normal,64)
            vertices_mm=dot.vertices*1000
            radial=np.hypot(vertices_mm[:,1],vertices_mm[:,2]-z)
            relief=sign*vertices_mm[:,0]-ctx.d/2+.02
            outer_depth=np.interp(radial,
                [r*.88,r*.94,r*.985,r],[p*.30,p*.28,p*.21,p*.14])
            vertices_mm[:,0]=sign*(ctx.d/2+outer_depth+.008+relief)
            dot.vertices=vertices_mm*.001
            dot.merge_vertices(merge_tex=True,merge_norm=True,digits_vertex=10)
            ctx.add(name+'_alignment_dot',dot,'marking',name)
            for i in range(12 if ident=='x6' else 6):
                a=i*math.tau/(12 if ident=='x6' else 6)
                flat=rounded_panel(2.4,.65,.10,.24,(0,0,0))
                flat.apply_transform(trimesh.transformations.rotation_matrix(a,[1,0,0]))
                flat.apply_translation(np.array([sign*(ctx.d/2+p*.17),r*.962*math.cos(a),z+r*.962*math.sin(a)])*.001)
                ctx.add(name+f'_locking_flat_{i}',flat,'lens_barrel',name)
        if ident=='one_rs_1inch360':
            # Printed markings follow the outward conical retaining surface.
            # A fixed X offset buries them behind the barrel's closing cap;
            # moving only X would instead put the lower legend over the glass.
            for suffix,text,height,side,width,radius_fraction,material in [
                    ('leica','LEICA',.80,1,5,.961,'marking'),
                    ('lens_spec','SUPER-SUMMICRON',.60,-1,7.6,.953,'marking_dim')]:
                marking=text_mesh(text,height,.012,(sign*ctx.d/2,0,z+side*r*radius_fraction),normal,width)
                vertices_mm=marking.vertices*1000
                radial=np.hypot(vertices_mm[:,1],vertices_mm[:,2]-z)
                relief=sign*vertices_mm[:,0]-ctx.d/2
                outer_depth=np.interp(radial,
                    [r*.88,r*.94,r*.985,r],[p*.30,p*.28,p*.21,p*.14])
                vertices_mm[:,0]=sign*(ctx.d/2+outer_depth+.008+relief)
                marking.vertices=vertices_mm*.001
                ctx.add(name+'_'+suffix,marking,material,name)
        ctx.surfaces.append((f'{ident}_{name}_surface',[sign*ctx.overall*.0005,0,z*.001],sign))


def _screen(ctx,design):
    ident=ctx.camera['id'];f=ctx.d/2;z=ctx.h*design['display_z']
    if ident in ('one_x2','one_x'):
        r=13 if ident=='one_x2' else 10.0
        _disc(ctx,'display_surround',r+1.1,(f-.105,0,z),material='seam',depth=.14)
        ctx.add('display_edge',ring(r+.3,r,.07,(f-.035,0,z)), 'display_edge')
        _disc(ctx,'display_glass',r,(f-.026,0,z),material='screen',depth=.03)
    else:
        w,h=design['display'];corner=4.1 if ident=='x6' else 2.2
        surround=5.8 if ident=='x6' else 2.2
        _panel(ctx,'display_surround',w+surround,h+surround,.18,corner+.5,(f-.105,0,z),material='seam')
        _panel(ctx,'display_glass',w,h,.045,corner,(f-.027,0,z),material='screen')
        ctx.add('display_edge',outline(w+.18,h+.18,corner,(f-.025,0,z),stroke=.036),'display_edge')
    if ident in ('x4_air','x4','x3'):
        sw,sh=design['display']
        _label(ctx,'front_brand','Insta360',1.55,(f-.01,0,z-sh/2-3),width=14)
    if ident=='one_rs_1inch360':
        _label(ctx,'front_brand','Insta360',1.8,(f-.02,0,ctx.h*.078),width=16,material='marking_dim')


def _front_controls(ctx,design):
    ident=ctx.camera['id'];f=ctx.d/2;h=ctx.h
    if ident=='x6':
        _grille(ctx,'front_microphone',4.5,3.6,(f-.065,-ctx.w*.337,h*.606),pitch=.60)
        _panel(ctx,'front_ambient_window',4.0,2.7,.10,1.1,(f-.058,ctx.w*.337,h*.607),material='glass_outer')
    elif ident=='x4_air':
        _disc(ctx,'shutter_border',6.0,(f-.06,0,h*.094),material='seam',depth=.12)
        _disc(ctx,'shutter_button',5.6,(f-.005,0,h*.094),material='control',depth=.05)
        _disc(ctx,'shutter_dot',1.0,(f+.020,0,h*.094),material='marking_dark',depth=.012)
        _disc(ctx,'front_microphone',.72,(f-.024,0,h*.655),material='aperture',depth=.025)
    elif ident in ('x4','x3'):
        z=h*.069
        for name,y in [('shutter',-ctx.w*.20),('lens_select',ctx.w*.20)]:
            _disc(ctx,name+'_border',2.5,(f-.062,y,z),material='seam',depth=.10)
            _disc(ctx,name+'_button',2.15,(f-.015,y,z),material='control',depth=.045)
        _disc(ctx,'shutter_glyph',.75,(f+.012,-ctx.w*.20,z),material='marking_dark',depth=.012)
        ctx.add('lens_select_glyph',ring(.85,.57,.012,(f+.012,ctx.w*.20,z)), 'marking_dark')
        _disc(ctx,'front_microphone',.68,(f-.032,0,h*.647),material='aperture',depth=.035)
    elif ident=='one_x2':
        _disc(ctx,'shutter_border',5.7,(f-.065,0,h*.177),material='seam',depth=.11)
        _disc(ctx,'shutter_button',5.25,(f-.012,0,h*.177),material='control',depth=.045)
        _disc(ctx,'shutter_glyph',1.0,(f+.014,0,h*.177),material='marking_dark',depth=.015)
        _disc(ctx,'front_microphone',.65,(f-.030,0,h*.680),material='aperture',depth=.035)
    elif ident=='one_x':
        for name,r,z in [('power',4.2,h*.240),('shutter',6.0,h*.378)]:
            _disc(ctx,name+'_border',r+.40,(f-.061,0,z),material='seam',depth=.105)
            _disc(ctx,name+'_button',r,(f-.012,0,z),material='control',depth=.04)
        _power_icon(ctx,'power_glyph',(f+.01,0,h*.240),(1,0,0),2.6)
        _disc(ctx,'shutter_glyph',1.1,(f+.01,0,h*.378),material='marking_dark',depth=.015)
        _label(ctx,'front_brand','Insta360',2.1,(f-.016,0,h*.105),width=19)
    if ident!='one_rs_1inch360':
        z=.028*h if ident in ('x6','x4_air','x4','x3') else .082*h
        _panel(ctx,'front_indicator_border',5.0,.95,.05,.35,(f-.027,0,z),material='seam')
        _panel(ctx,'front_indicator',3.8,.40,.025,.17,(f+.004,0,z),material='status_dim')


def _rear(ctx,design):
    ident=ctx.camera['id'];f=-ctx.d/2;h=ctx.h;n=(-1,0,0)
    if ident=='x6':
        # Manufacturer's six-sided wind guard panel, ambient window and quick
        # key replace the old undifferentiated back plate.
        _grille(ctx,'rear_wind_guard',21.0,12.5,(f+.058,0,h*.518),n,pitch=.68,hexagonal=True)
        _panel(ctx,'rear_ambient_sensor',5.0,1.8,.04,.6,(f-.018,0,h*.479),n,'glass_outer')
        _label(ctx,'rear_brand','Insta360 X6',1.8,(f+.035,0,h*.322),n,width=28,angle=-math.pi/2,material='marking_dim')
        _panel(ctx,'quick_button_border',10.5,6.2,.08,2.6,(f+.04,0,h*.134),n,'seam')
        _panel(ctx,'quick_button',9.3,5.0,.06,2.2,(f-.008,0,h*.134),n,'control')
        _label(ctx,'quick_glyph','Q',1.8,(f-.046,0,h*.134),n,material='marking_dim')
        # Shallow cooling channels follow the tapered back grip outline.
        for side in (-1,1):
            points=[(f+.10,side*ctx.w*.405,h*.09),(f+.10,side*ctx.w*.24,h*.26),
                    (f+.10,side*ctx.w*.36,h*.61)]
            ctx.add(f'rear_cooling_channel_{side}',tube_line(points,.065),'grip_ridge')
    elif ident=='x4':
        _ribs(ctx,'rear_cooling_ribs',ctx.w*.90,h*.67,(f+.045,0,h*.363),n,pitch=1.40)
        _panel(ctx,'rear_logo_recess',6.0,31.5,.08,1.2,(f-.03,0,h*.406),n,'rubber')
        _label(ctx,'rear_brand','Insta360 X4',2.1,(f-.082,0,h*.406),n,angle=-math.pi/2,width=29)
    elif ident=='x4_air':
        _grille(ctx,'rear_wind_guard',11.4,5.5,(f+.043,0,h*.642),n,pitch=.66)
        _label(ctx,'rear_brand','Insta360 X4 Air',2.0,(f+.021,0,h*.439),n,angle=-math.pi/2,width=31)
        for side in (-1,1):
            ctx.add(f'rear_taper_seam_{side}',tube_line([(f+.08,side*ctx.w*.41,h*.077),
                 (f+.08,side*ctx.w*.23,h*.28),(f+.08,side*ctx.w*.40,h*.695)],.047),'seam')
    elif ident=='one_rs_1inch360':
        _ribs(ctx,'vertical_battery_grip',ctx.w*.78,h*.45,(f+.041,0,h*.256),n,pitch=.90,angle=-math.pi/10)
        _seam(ctx,'vertical_battery_cover',ctx.w*.85,h*.495,5.0,(f+.04,0,h*.261),n)
        _label(ctx,'battery_legend','1-INCH 360 EDITION',1.30,(f+.013,ctx.w*.32,h*.25),n,angle=math.pi/2,width=32,material='marking_dim')
        _disc(ctx,'rear_record_led',.72,(f+.0,-ctx.w*.19,h*.354),n,'record_red',.032)
    else:
        label='Insta360 X3' if ident=='x3' else 'Insta360 ONE X2' if ident=='one_x2' else 'Insta360 ONE X'
        _label(ctx,'rear_brand',label,1.85,(f+.035,0,h*.437),n,angle=-math.pi/2,width=29,material='marking_dim')
    if ident not in ('x6','one_rs_1inch360'):
        _disc(ctx,'rear_microphone',.63,(f+.028,0,h*.677),n,'aperture',.028)
    if ident!='one_rs_1inch360':
        z=h*(.085 if ident=='x6' else .105)
        _panel(ctx,'rear_indicator_border',4.4,.85,.04,.29,(f+.026,0,z),n,'seam')
        _panel(ctx,'rear_indicator',3.8,.37,.026,.16,(f+.001,0,z),n,'status_dim')


def _side_details(ctx,design):
    ident=ctx.camera['id'];w,h,d=ctx.w,ctx.h,ctx.d
    if ident=='one_rs_1inch360':w*=.86
    for sign in (-1,1):
        n=(0,sign,0);y=sign*(w/2-.09)
        # Side inset skin makes the battery latch, switches and port cover a
        # coherent assembly instead of floating rectangles on the widest edge.
        grip_h,grip_z=(h*.52,h*.285) if ident=='one_rs_1inch360' else (h*.78,h*.475)
        _panel(ctx,f'side_grip_{sign}',d*.72,grip_h,.08,3.0,(0,y,grip_z),n,'rubber')
        _seam(ctx,f'side_joint_{sign}',d*.73,grip_h+.35,3.1,(0,sign*(w/2-.045),grip_z),n,.045)
    ny=(0,-1,0);py=(0,1,0);yside=-w/2+.037
    if ident=='x6':
        for sign in (-1,1):
            n=(0,sign,0);y=sign*(w/2-.023)
            _grille(ctx,f'side_wind_guard_{sign}',6.8,8.8,(0,y,h*.84),n,pitch=.7)
            _panel(ctx,f'side_mic_secondary_{sign}',5.0,1.8,.05,.65,(0,sign*(w/2+.026),h*.763),n,'aperture')
        _panel(ctx,'power_key_surround',12.1,30.5,.07,3.3,(0,yside,h*.500),ny,'seam')
        _panel(ctx,'power_key',9.1,8.0,.06,2.6,(0,-w/2-.007,h*.580),ny,'control')
        _power_icon(ctx,'side_power_icon',(0,-w/2-.043,h*.580),ny,3.8)
        ctx.add('side_shutter_red_ring',ring(4.8,4.4,.045,(0,-w/2-.006,h*.420),ny),'record_red')
        _disc(ctx,'side_shutter',4.3,(0,-w/2-.020,h*.420),ny,'control',.045)
        _disc(ctx,'side_shutter_dot',.75,(0,-w/2-.045,h*.420),ny,'marking_dark',.012)
        _panel(ctx,'usb_door',d*.72,18.3,.085,3.1,(0,yside,h*.125),ny,'control')
        _seam(ctx,'usb_door_joint',d*.74,18.7,3.1,(0,-w/2-.005,h*.125),ny,.055)
        _panel(ctx,'usb_latch',5.0,3.6,.08,.8,(0,-w/2-.013,h*.136),ny,'lens_barrel')
        _panel(ctx,'battery_cover',d*.74,h*.51,.07,2.5,(0,w/2-.03,h*.336),py,'control')
        _panel(ctx,'battery_latch',5.1,4.1,.09,.9,(0,w/2-.006,h*.108),py,'lens_barrel')
        _grille(ctx,'side_speaker',4.0,5.4,(0,w/2-.002,h*.638),py,pitch=1.1)
    else:
        # Waterproof battery cover opposite power/Q buttons. ONE X predates
        # USB-C; its smaller micro-USB cover remains separately recognizable.
        battery_h=h*(.49 if ident!='one_rs_1inch360' else .36)
        _panel(ctx,'battery_door',d*.72,battery_h,.085,2.6,(0,w/2-.034,battery_h/2+h*.065),py,'control')
        _seam(ctx,'battery_door_joint',d*.75,battery_h+.3,2.7,(0,w/2+.010,battery_h/2+h*.065),py,.05)
        for z in (h*.125,battery_h+h*.025):
            _panel(ctx,f'battery_lock_{z}',4.5,4.1,.10,.7,(0,w/2-.012,z),py,'lens_barrel')
            ctx.add(f'battery_lock_engraving_{z}',tube_line([(-1.4,w/2+.042,z),(1.4,w/2+.042,z)],.07),'seam')
        usb_z=h*.707 if ident!='one_rs_1inch360' else h*.476
        _panel(ctx,'usb_door',d*.66,12.5,.085,2.0,(0,w/2-.024,usb_z),py,'control')
        _seam(ctx,'usb_door_joint',d*.69,12.9,2.0,(0,w/2+.018,usb_z),py,.052)
        _panel(ctx,'usb_latch',4.5,3.5,.09,.7,(0,w/2-.006,usb_z-.7),py,'lens_barrel')
        if ident!='one_x':
            for name,z in [('power',h*.570),('quick',h*.386 if ident!='one_rs_1inch360' else h*.383)]:
                _panel(ctx,name+'_key_surround',8.9,8.9,.08,2.2,(0,yside,z),ny,'seam')
                _panel(ctx,name+'_key',7.7,7.7,.055,1.9,(0,-w/2-.012,z),ny,'control')
                if name=='power':_power_icon(ctx,'power_key_glyph',(0,-w/2-.05,z),ny,3.0)
                else:_label(ctx,'quick_key_glyph','Q',2.0,(0,-w/2-.05,z),ny,material='marking_dark')
            _grille(ctx,'side_speaker',3.8,7.0,(0,yside,h*.739),ny,pitch=.90)
        if ident=='one_rs_1inch360':
            ctx.add('vertical_shutter_ring',ring(3.7,3.35,.04,(0,-w/2-.005,h*.345),ny),'record_red')
    # Fine seams above and below the side assembly leave top/bottom corners
    # smooth; none extend beyond the source envelope by more than 0.08 mm.


def _modular_shell(ctx,design):
    w,h,d=ctx.w,ctx.h,ctx.d
    for sign in (-1,1):
        f=sign*(d/2-.085);n=(sign,0,0)
        for label,z in [('lens_core',h*.598),('core_battery',h*.327)]:
            ctx.add(label+f'_seam_{sign}',tube_line([(f,-w*.44,z),(f,w*.44,z)],.10),'seam')
        _panel(ctx,f'core_face_{sign}',w*.85,h*.252,.10,2.0,(sign*(d/2-.105),0,h*.466),n,'housing_face')
    # Lens head is visibly wider than core; two vertical bracket rails and their
    # latch provide the distinct three-module silhouette of the 1-inch edition.
    for sign in (-1,1):
        _panel(ctx,f'mounting_bracket_rail_{sign}',d*.65,h*.50,.14,1.6,
               (0,sign*(w*.455-.11),h*.257),(0,sign,0),'lens_barrel')
        _panel(ctx,f'bracket_latch_{sign}',d*.37,6.0,.12,1.2,
               (0,sign*(w*.455-.065),h*.567),(0,sign,0),'control')


def decorate(ctx):
    ident=ctx.camera['id']
    if ident not in MODEL_IDS:return False
    ctx.parts.clear();ctx.surfaces.clear();ctx.collision_proxies.clear()
    ctx.colors.update({
        'housing':[.115,.120,.132,1], 'housing_face':[.092,.099,.108,1],
        'housing_lens_head':[.19,.20,.22,1],
        'lens_barrel':[.060,.068,.078,1], 'control':[.13,.14,.155,1],
        'aperture':[.006,.008,.012,1], 'lens_ring':[.19,.205,.225,1],
        'glass_outer':[.035,.045,.058,1], 'glass_coating':[.025,.047,.040,1],
        'optical_glass':[.008,.014,.020,1], 'coating_edge':[.075,.09,.12,1],
        'display_edge':[.115,.126,.144,1], 'screen':[.015,.019,.027,1],
        'mount_metal':[.27,.285,.31,1], 'marking':[.72,.73,.75,1],
        'marking_dim':[.40,.42,.45,1], 'marking_dark':[.45,.46,.48,1],
        'grip_ridge':[.077,.084,.094,1], 'record_red':[.57,.032,.048,1],
        'status_dim':[.020,.45,.58,1],
    })
    ctx.materials.update({
        'housing':dict(roughnessFactor=.61,metallicFactor=.025),
        'housing_face':dict(roughnessFactor=.72,metallicFactor=.025),
        'housing_lens_head':dict(roughnessFactor=.38,metallicFactor=.13),
        'lens_barrel':dict(roughnessFactor=.30,metallicFactor=.2),
        'lens_ring':dict(roughnessFactor=.19,metallicFactor=.6),
        'glass_outer':dict(roughnessFactor=.085,metallicFactor=.17),
        'glass_coating':dict(roughnessFactor=.060,metallicFactor=.13),
        'optical_glass':dict(roughnessFactor=.045,metallicFactor=.06),
        'screen':dict(roughnessFactor=.095,metallicFactor=.08),
        'mount_metal':dict(roughnessFactor=.28,metallicFactor=.85),
        'display_edge':dict(roughnessFactor=.26,metallicFactor=.35),
    })
    design=DESIGNS[ident]
    _body(ctx,design)
    if ident=='one_rs_1inch360':_modular_shell(ctx,design)
    _lens(ctx,design);_screen(ctx,design)
    _front_controls(ctx,design);_rear(ctx,design)
    side_start=len(ctx.parts)
    _side_details(ctx,design)
    for _,mesh,_,_ in ctx.parts[side_start:]:
        sign=1 if np.mean(mesh.vertices[:,1])>0 else -1
        mesh.apply_translation([0,-sign*.15*.001,0])
        if ident=='x6':
            # Rear-side manufacturer close-up places the battery/speaker on
            # -Y and power/shutter/USB on +Y in the screen-facing convention.
            mesh.apply_transform(np.diag([1.,-1.,1.,1.]))
    return True
