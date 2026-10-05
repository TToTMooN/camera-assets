"""Independent procedural X5 visual asset. Run in Python with bpy installed.

Coordinates: +X = screen/front, +Y = screen-facing right, +Z = up; origin = bottom mount.
All authoring dimensions below are mm; stored geometry is in meters.
No downloaded geometry, photographs, or third-party texture assets are used.
"""
from pathlib import Path
import json
import math

import bpy
import numpy as np
from mathutils import Vector, Matrix

ROOT = Path(__file__).resolve().parents[2]/"models/x5"
P = json.loads((ROOT / "config/x5.json").read_text())
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
M = .001
objects = []
materials = {}


def material(name, color, rough=.5, metal=0):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1)
    mat.use_nodes = True
    p = mat.node_tree.nodes.get("Principled BSDF")
    p.inputs["Base Color"].default_value = (*color, 1)
    p.inputs["Roughness"].default_value = rough
    p.inputs["Metallic"].default_value = metal
    materials[name] = mat
    return mat


body = material("graphite_polycarbonate", (.027, .031, .037), .63)
rubber = material("rubber_grip", (.013, .017, .022), .82)
seam = material("recess_shadow", (.004, .006, .009), .8)
metal = material("anodized_lens_ring", (.036, .042, .05), .3, .75)
rim = material("lens_edge", (.085, .095, .11), .26, .82)
glass = material("coated_optical_glass", (.003, .009, .007), .10, .22)
glass.node_tree.nodes.get("Principled BSDF").inputs["Coat Weight"].default_value = .8
screen = material("display_glass_off", (.003, .004, .004), .22, .05)
cover = material("display_black_border", (.001, .0012, .0013), .16, .05)
silver = material("mount_stainless", (.38, .4, .43), .26, .9)
ink = material("printed_markings", (.30, .33, .35), .66)
led = material("status_cyan", (.012, .42, .5), .32)
led.node_tree.nodes.get("Principled BSDF").inputs["Emission Color"].default_value=(.0,.2,.3,1)
led.node_tree.nodes.get("Principled BSDF").inputs["Emission Strength"].default_value=.2


def finish(obj, mat, smooth=True):
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    if obj.type == "MESH":
        for p in obj.data.polygons:
            p.use_smooth = smooth
    objects.append(obj)
    return obj


def mesh(name, vertices, faces, mat, smooth=True):
    data = bpy.data.meshes.new(name)
    data.from_pydata(np.asarray(vertices) * M, [], faces)
    data.update()
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    return finish(obj, mat, smooth)


def frame(normal):
    n = Vector(normal)
    v = Vector((0, 0, 1)) if abs(n.z) < .9 else Vector((0,1,0))
    u = v.cross(n)
    return u, v, n


def to_world(points, center, normal):
    u,v,n = frame(normal)
    return [Vector(center) + float(a)*u+float(b)*v+float(c)*n for a,b,c in points]


def contour(w,h,r,steps=12):
    pts=[]
    for x,y,start in [(w/2-r,h/2-r,0),(-w/2+r,h/2-r,90),(-w/2+r,-h/2+r,180),(w/2-r,-h/2+r,270)]:
        for a in np.linspace(start,start+90,steps,endpoint=False):
            t=math.radians(a)
            pts.append((x+r*math.cos(t),y+r*math.sin(t)))
    return pts


def panel(name,w,h,depth,r,center,normal,mat,bevel=.12,steps=12):
    b=min(bevel,depth*.49,r*.4)
    rings=[]
    # A rounded rectangle, with a quarter-circle edge bevel on each face.
    for sign in [-1,1]:
        angles=np.linspace(0,math.pi/2,4)
        if sign<0: angles=angles[::-1]
        for a in angles:
            inset=b*(1-math.cos(a))
            z=sign*(depth/2-b+b*math.sin(a))
            rings.append([(x,y,z) for x,y in contour(w-2*inset,h-2*inset,max(.01,r-inset),steps)])
    vertices=[p for ring in rings for p in ring]
    n=len(rings[0]); faces=[]
    for i in range(len(rings)-1):
        for j in range(n): faces.append((i*n+j,i*n+(j+1)%n,(i+1)*n+(j+1)%n,(i+1)*n+j))
    faces += [tuple(reversed(range(n))),tuple(range((len(rings)-1)*n,len(rings)*n))]
    obj=mesh(name,to_world(vertices,center,normal),faces,mat)
    # Flat caps; curved bevels remain smooth.
    obj.data.polygons[-1].use_smooth=False
    obj.data.polygons[-2].use_smooth=False
    return obj


def lathe(name,profile,center,normal,mat,segments=128):
    vertices=[]
    for radius,z in profile:
        for a in np.linspace(0,math.tau,segments,endpoint=False):
            vertices.append((radius*math.cos(a),radius*math.sin(a),z))
    faces=[]
    for i in range(len(profile)-1):
        for j in range(segments):
            faces.append((i*segments+j,i*segments+(j+1)%segments,(i+1)*segments+(j+1)%segments,(i+1)*segments+j))
    faces += [tuple(reversed(range(segments))),tuple(range((len(profile)-1)*segments,len(profile)*segments))]
    return mesh(name,to_world(vertices,center,normal),faces,mat)


def line(name,points,radius,mat):
    curve=bpy.data.curves.new(name,"CURVE"); curve.dimensions="3D"
    curve.resolution_u=1; curve.bevel_depth=radius*M; curve.bevel_resolution=2
    spl=curve.splines.new("POLY"); spl.points.add(len(points)-1)
    for p,co in zip(spl.points,points): p.co=(*[v*M for v in co],1)
    obj=bpy.data.objects.new(name,curve); bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active=obj; obj.select_set(True)
    bpy.ops.object.convert(target="MESH"); obj.select_set(False)
    return finish(obj,mat)


def text_label(name,text,size,center,normal,mat,angle=0):
    data=bpy.data.curves.new(name,"FONT"); data.body=text; data.size=size*M
    data.align_x="CENTER"; data.align_y="CENTER"; data.extrude=0; data.resolution_u=6
    obj=bpy.data.objects.new(name,data); bpy.context.collection.objects.link(obj)
    u,v,n=frame(normal)
    basis=Matrix((u,v,n)).transposed().to_4x4()
    obj.matrix_world=Matrix.Translation(Vector(center)*M) @ basis @ Matrix.Rotation(angle,4,"Z")
    bpy.context.view_layer.objects.active=obj; obj.select_set(True)
    bpy.ops.object.convert(target="MESH"); obj.select_set(False)
    return finish(obj,mat,False)


def outline(name,w,h,r,center,normal,mat,stroke=.12):
    pts=contour(w,h,r,12)
    line(name,to_world([(x,y,0) for x,y in pts+[pts[0]]],center,normal),stroke,mat)


def hex_plate(name,w,h,center,normal,mat):
    # Six-sided windscreen outline, with gently rounded corners.
    corners=[(w/2,0),(w/4,h/2),(-w/4,h/2),(-w/2,0),(-w/4,-h/2),(w/4,-h/2)]
    edge=[]
    for i,c in enumerate(corners):
        prev=np.array(corners[i-1]);cur=np.array(c);nxt=np.array(corners[(i+1)%6])
        a=cur+.10*(prev-cur);b=cur+.10*(nxt-cur)
        for t in np.linspace(0,1,5,endpoint=False):
            edge.append((1-t)**2*a+2*(1-t)*t*cur+t*t*b)
    n=len(edge)
    verts=[(x,y,z) for z in [-.05,.05] for x,y in edge]
    faces=[tuple(reversed(range(n))),tuple(range(n,n*2))]
    faces += [(i,(i+1)%n,(i+1)%n+n,i+n) for i in range(n)]
    return mesh(name,to_world(verts,center,normal),faces,mat,False)


def normal_texture(mat,name,diamond=False):
    size=1024 if diamond else 512
    y,x=np.mgrid[:size,:size]/size
    rng=np.random.default_rng(11)
    height=rng.normal(0,.02,(size,size))
    if diamond:
        height+=.065*(np.cos(2*math.pi*(x*64+y*174))+np.cos(2*math.pi*(x*64-y*174)))
    dx=np.roll(height,-1,1)-np.roll(height,1,1)
    dy=np.roll(height,-1,0)-np.roll(height,1,0)
    normals=np.stack([-dx*1.8,-dy*1.8,np.ones_like(dx)],axis=2)
    normals/=np.linalg.norm(normals,axis=2,keepdims=True)
    rgba=np.concatenate([normals*.5+.5,np.ones((size,size,1))],axis=2).astype(np.float32)
    image=bpy.data.images.new(name,size,size,alpha=True)
    image.colorspace_settings.name="Non-Color"
    image.pixels.foreach_set(rgba.ravel())
    image.filepath_raw=str(ROOT/"assets/textures"/(name+".png")); image.file_format="PNG"; image.save()
    nodes=mat.node_tree.nodes
    tex=nodes.new("ShaderNodeTexImage"); tex.image=image
    normal=nodes.new("ShaderNodeNormalMap"); normal.inputs["Strength"].default_value=.16 if diamond else .2
    mat.node_tree.links.new(tex.outputs["Color"],normal.inputs["Color"])
    mat.node_tree.links.new(normal.outputs["Normal"],nodes.get("Principled BSDF").inputs["Normal"])


W,H,D=P["width_mm"],P["height_mm"],P["body_depth_mm"]
LZ=P["lens_center_height_mm"]
# The side keys define the nominal width; never rescale the active display.
panel("continuous_body_shell",W-.7,H,D-.2,P["corner_radius_mm"],(0,0,H/2),(1,0,0),body,1.6,20)
for side in [1,-1]:
    normal=(side,0,0)
    # Face panel seam and inset skin, entirely within the housing envelope.
    panel(f"face_seal_{side}",42.7,121,.20,7.8,(side*12.96,0,H/2),normal,seam,.06,18)
    panel(f"face_skin_{side}",42.1,120.4,.20,7.5,(side*13.0,0,H/2),normal,body if side==1 else rubber,.06,18)
    ring=P["lens_ring_radius_mm"]
    lathe(f"lens_seat_{side}",[(ring-.6,-.3),(ring,0),(ring,.55),(ring-.45,.95),(13.7,.95)],(side*13.0,0,LZ),normal,seam)
    lathe(f"replaceable_lens_ring_{side}",[(15.35,0),(15.8,.35),(15.75,.9),(15.05,1.65),(13.55,1.9),(13.45,1.7)],(side*13.45,0,LZ),normal,metal)
    lathe(f"machined_ring_edge_{side}",[(14.7,0),(14.78,.1),(14.65,.24),(14.5,.24)],(side*14.65,0,LZ),normal,rim)
    # Convex spherical cap: outer glass tips exactly +/- 19.1 mm.
    a=P["lens_glass_radius_mm"]; base=15.20; tip=P["overall_depth_mm"]/2
    sag=tip-base; radius=(a*a+sag*sag)/(2*sag)
    profile=[(a,-.20)]
    for rr in np.linspace(a,0,25):
        profile.append((float(rr),math.sqrt(radius*radius-rr*rr)-(radius-sag)))
    lens=lathe(f"convex_fisheye_glass_{side}",profile,(side*base,0,LZ),normal,glass,160)
    # Small alignment indicators on replaceable lens bezel.
    for angle in [45,135,225,315]:
        t=math.radians(angle)
        points=to_world([(15.1*math.cos(t),15.1*math.sin(t),0),(15.6*math.cos(t),15.6*math.sin(t),0)],(side*14.61,0,LZ),normal)
        line(f"bezel_tick_{side}_{angle}",points,.07,ink)

# Display off: physically separate bezel and glass, no copyrighted UI image.
SZ=P["screen_center_height_mm"]
panel("display_cover",P["screen_cover_width_mm"],P["screen_cover_height_mm"],.30,.5,(13.04,0,P["screen_cover_center_height_mm"]),(1,0,0),cover,.04)
panel("display_active_area",P["screen_width_mm"],P["screen_height_mm"],.08,.22,(13.20,0,SZ),(1,0,0),screen,.015)
text_label("front_wordmark","Insta360",2.6,(13.205,0,21.8),(1,0,0),ink)
# X5's lower controls sit in the common face skin, with outlined symbols.
# Front-on: shutter on viewer-left (-Y), menu on viewer-right (+Y).
outline("shutter_outline",2.8,2.8,1.4,(13.14,-9.6,11.8),(1,0,0),ink,.12)
outline("menu_rear_rectangle",2.6,1.9,.5,(13.14,10.0,12.1),(1,0,0),ink,.10)
panel("menu_overlap_mask",2.4,1.7,.025,.4,(13.20,9.4,11.5),(1,0,0),body,.003)
outline("menu_front_rectangle",2.6,1.9,.5,(13.24,9.4,11.5),(1,0,0),ink,.10)
panel("front_led_seal",6.0,1.1,.10,.4,(13.115,0,3.3),(1,0,0),seam,.03)
panel("front_led",5.6,.75,.10,.3,(13.17,0,3.3),(1,0,0),led,.025)
lathe("front_microphone",[(.64,0),(.64,.04)],(13.13,0,86.2),(1,0,0),seam,32)

# Rear windscreen is a wide six-sided mesh, not a rounded rectangle.
hex_plate("rear_mic_frame",18.5,12.5,(-13.18,0,78.3),(-1,0,0),body)
for row in range(-6,7):
    for col in range(-10,11):
        u=col*.82+(.41 if row%2 else 0); v=row*.82
        if abs(v)<5.3 and abs(u)<8.35-.72*abs(v):
            lathe(f"rear_mic_hole_{row}_{col}",[(.22,0),(.22,.018)],(-13.245,u,78.3+v),(-1,0,0),seam,10)
panel("rear_badge_recess",7.6,29,.16,2.8,(-13.13,0,57.8),(-1,0,0),seam,.04)
panel("rear_badge",6.2,27.5,.17,2.1,(-13.24,0,57.8),(-1,0,0),body,.04)
text_label("rear_wordmark","Insta360 X5",3.9,(-13.34,0,57.8),(-1,0,0),ink,-math.pi/2)
panel("rear_led_seal",6.5,1.9,.15,.8,(-13.13,0,13.0),(-1,0,0),seam,.04)
panel("rear_led",3.1,.7,.12,.25,(-13.27,0,13.0),(-1,0,0),led,.03)
# Continuous shallow grip facet edges follow the X5 rear illustration.
facet_edges=[((0,44),(0,13)),((-3.8,69),(-13.5,65)),((3.8,69),(13.5,65)),
             ((-20,88),(-3,71)),((20,88),(3,71)),((-20,78),(-13.5,65)),((20,78),(13.5,65)),
             ((-13.5,65),(-20,43)),((13.5,65),(20,43)),
             ((-13.5,65),(-3.5,13)),((13.5,65),(3.5,13)),
             ((-20,43),(-14,19)),((20,43),(14,19)),
             ((-20,43),(-3.5,13)),((20,43),(3.5,13)),
             ((-14,19),(-3.5,13)),((14,19),(3.5,13)),
             ((-14,19),(-17,3)),((14,19),(17,3)),
             ((-3.5,13),(-17,3)),((3.5,13),(17,3))]
for i,(start,end) in enumerate(facet_edges):
    line(f"rear_grip_facet_{i}",[(-13.115,*start),(-13.115,*end)],.032,body)

# Looking directly at the screen: battery LEFT (-Y), controls RIGHT (+Y).
# The shell is 45.3 mm wide; integrated panels and keys reach the 46 mm envelope.
panel("battery_seam",15.4,64,.16,3,(0,-22.64,49.4),(0,-1,0),seam,.04)
panel("battery_cover",14.8,63,.14,2.8,(0,-22.72,49.4),(0,-1,0),body,.04)
for z in [30.8,64.1]:
    panel("battery_latch_"+str(z),7.8,6.2,.40,1.4,(0,-22.8,z),(0,-1,0),rubber,.08)
    panel("battery_latch_lip_"+str(z),7.5,2.3,.11,1.0,(0,-22.925,z+(-1.6 if z<45 else 1.6)),(0,-1,0),body,.03)
panel("side_key_seal",14.2,32.8,.16,3.2,(0,22.65,57.9),(0,1,0),seam,.04)
panel("side_key_panel",13.5,31.9,.30,2.9,(0,22.74,57.9),(0,1,0),body,.06)
panel("side_power_button",11.4,11.4,.20,1.5,(0,22.82,67.4),(0,1,0),rubber,.04)
text_label("quick_key","Q",3.0,(0,22.92,47.8),(0,1,0),ink)
# Power glyph: upright gap and stem, in the side panel's local coordinates.
pts=to_world([(1.1*math.cos(t),1.1*math.sin(t),0) for t in np.linspace(math.pi/2+.45,math.pi/2+math.tau-.45,40)],(0,22.925,67.4),(0,1,0))
line("power_ring",pts,.075,ink)
line("power_stem",[(0,22.925,67.7),(0,22.925,68.85)],.075,ink)
panel("usb_door_seal",15.5,39.5,.16,3,(0,22.64,22),(0,1,0),seam,.04)
panel("usb_door",14.8,38.5,.16,2.8,(0,22.72,22),(0,1,0),body,.04)
line("usb_door_division",[(-7.3,22.815,27.8),(7.3,22.815,27.8)],.04,seam)
panel("usb_latch",8.7,4.6,.26,1.3,(0,22.85,13.5),(0,1,0),rubber,.05)
panel("usb_latch_lip",8.4,2.1,.08,.9,(0,22.95,12.5),(0,1,0),body,.02)
for side in [-1,1]:
    lathe(f"side_mic_seal_{side}",[(1.9,0),(1.9,.035)],(0,side*22.70,109.2),(0,side,0),metal,40)
    lathe(f"side_mic_port_{side}",[(1.05,0),(1.05,.020)],(0,side*22.75,109.2),(0,side,0),seam,32)
    # Upper slot on both sides; the control-side speaker has a second lower slot.
    for index,z in enumerate([101.2,90.7] if side==1 else [100.7]):
        panel(f"side_slot_{side}_{index}",3.7,9.3,.09,1.8,(0,side*22.73,z),(0,side,0),seam,.02)

# Bottom interface, visual-only recess and concentric thread hints.
panel("bottom_insert",15,27,.2,3,(0,0,.12),(0,0,-1),seam,.04)
lathe("quarter_inch_insert",[(4.3,0),(4.3,.08),(3.175,.08),(3.175,-1.8)],(0,0,.12),(0,0,-1),silver,80)
lathe("mount_hole_shadow",[(2.9,0),(2.9,.04)],(0,0,1.9),(0,0,-1),seam,64)
for i in range(3):
    lathe(f"thread_hint_{i}",[(3.17,0),(2.95,.12),(3.17,.24)],(0,0,.35+i*.5),(0,0,-1),metal,64)
for yy in [-10.5,10.5]:
    panel("quick_release_socket",4.6,6.5,.18,1.2,(0,yy,.12),(0,0,-1),metal,.04)
    panel("quick_release_recess",2.8,5.4,.19,.7,(0,yy,.12),(0,0,-1),seam,.04)

normal_texture(body,"polycarbonate_normal")
normal_texture(rubber,"diamond_grip_normal",True)

# Apply transforms; UVs use metric planar projection per vertex normal.
import bmesh
for obj in objects:
    bpy.context.view_layer.objects.active=obj
    obj.select_set(True)
    bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
    if obj.name.startswith("usb_"):
        # Follow the housing's rounded lower shoulder; an unwrapped flat door
        # would leave a disconnected vertical strip in the front silhouette.
        radius=P["corner_radius_mm"]*M
        for vertex in obj.data.vertices:
            if vertex.co.z<radius:
                shoulder=math.sqrt(max(0,radius**2-(vertex.co.z-radius)**2))
                vertex.co.y += shoulder-radius
    bm=bmesh.new(); bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=1e-9)
    bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
    bm.to_mesh(obj.data); bm.free()
    if not obj.data.uv_layers: obj.data.uv_layers.new(name="UVMap")
    uv=obj.data.uv_layers.active.data
    for face in obj.data.polygons:
        normal=face.normal
        for li in face.loop_indices:
            co=obj.data.vertices[obj.data.loops[li].vertex_index].co
            if abs(normal.x)>.6: value=(co.y/.046,co.z/.1245)
            elif abs(normal.y)>.6: value=(co.x/.0262,co.z/.1245)
            else: value=(co.x/.0262,co.y/.046)
            uv[li].uv=value
    tri=obj.modifiers.new("triangulate","TRIANGULATE")
    bpy.ops.object.modifier_apply(modifier=tri.name)
    bm=bmesh.new(); bm.from_mesh(obj.data)
    bmesh.ops.delete(bm,geom=[f for f in bm.faces if f.calc_area()<1e-16],context="FACES")
    bm.to_mesh(obj.data); bm.free()
    obj.select_set(False)

def select_all_model():
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects: obj.select_set(True)

select_all_model()
bpy.ops.export_scene.gltf(filepath=str(ROOT/"assets/meshes/x5_visual.glb"),export_format="GLB",use_selection=True,export_yup=True,export_materials="EXPORT")

def export_obj(path,group,mtl=False):
    # Ten decimal places avoid degenerate faces caused by six-decimal meter OBJ
    # exports when serializing sub-millimeter text and thin lens rim geometry.
    with path.open("w") as f:
        f.write("# Original procedural X5 mesh; meters; +X front, +Y screen-facing right, +Z up\n")
        if mtl:f.write("mtllib x5_visual.mtl\n")
        voff=1; loff=1
        for obj in group:
            data=obj.data; f.write(f"o {obj.name}\n")
            for v in data.vertices:f.write("v "+" ".join(f"{q:.10f}" for q in v.co)+"\n")
            for uv in data.uv_layers.active.data:f.write(f"vt {uv.uv.x:.8f} {uv.uv.y:.8f}\n")
            for n in data.corner_normals:f.write("vn "+" ".join(f"{q:.8f}" for q in n.vector)+"\n")
            if mtl:f.write("usemtl "+obj.data.materials[0].name+"\n")
            for face in data.polygons:
                f.write("f "+" ".join(f"{data.loops[i].vertex_index+voff}/{i+loff}/{i+loff}" for i in face.loop_indices)+"\n")
            voff+=len(data.vertices);loff+=len(data.loops)

export_obj(ROOT/"assets/meshes/x5_visual.obj",objects,True)
with (ROOT/"assets/meshes/x5_visual.mtl").open("w") as f:
    for name,mat in materials.items():
        p=mat.node_tree.nodes.get("Principled BSDF")
        f.write(f"newmtl {name}\nKd "+" ".join(f"{v:.6f}" for v in mat.diffuse_color[:3])+"\n")
        f.write(f"Ks 0.25 0.25 0.25\nNs {1000*(1-p.inputs['Roughness'].default_value)**2:.4f}\nd 1\nillum 2\n\n")

mtl_path=ROOT/"assets/meshes/x5_visual.mtl"
mtl_path.write_text(mtl_path.read_text().rstrip()+"\n")

# Material-separated URDF parts preserve explicit diffuse colors across importers.
manifest=[]
for stale in (ROOT/"assets/meshes/visual").glob("*.obj"): stale.unlink()
for name,mat in materials.items():
    bpy.ops.object.select_all(action="DESELECT")
    group=[o for o in objects if o.data.materials[0]==mat]
    for obj in group: obj.select_set(True)
    if not group: continue
    path=ROOT/"assets/meshes/visual"/(name+".obj")
    export_obj(path,group)
    manifest.append({"name":name,"file":"../assets/meshes/visual/"+name+".obj","rgba":list(mat.diffuse_color),"triangles":sum(len(o.data.polygons) for o in group)})
(ROOT/"assets/visual_manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
select_all_model()
for img in bpy.data.images:
    if img.name in ["polycarbonate_normal","diamond_grip_normal"]:
        img.pack()
        img.filepath="//textures/"+img.name+".png"
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/"assets/x5_source.blend"))
print("MODEL_EXPORT_COMPLETE",sum(len(o.data.polygons) for o in objects),flush=True)
