"""Build lightweight convex collision meshes and portable URDF from visual parts."""
from pathlib import Path
import json
import math
import xml.etree.ElementTree as ET
import numpy as np
import trimesh

ROOT=Path(__file__).resolve().parents[2]/"models/x5"
P=json.loads((ROOT/"config/x5.json").read_text())
manifest=json.loads((ROOT/"assets/visual_manifest.json").read_text())
out=ROOT/"assets/meshes/collision"
out.mkdir(parents=True,exist_ok=True)
robot=ET.Element("robot",name="x5")
link=ET.SubElement(robot,"link",name="x5_link")
inertial=ET.SubElement(link,"inertial")
ET.SubElement(inertial,"origin",xyz=f'0 0 {P["com_height_mm"]*.001}',rpy="0 0 0")
m=P["mass_kg"]; x=P["body_depth_mm"]*.001; y=P["width_mm"]*.001; z=P["height_mm"]*.001
ET.SubElement(inertial,"mass",value=str(m))
# Explicit nominal homogeneous-box estimate; this is not measured mass distribution.
I=[m*(y*y+z*z)/12,m*(x*x+z*z)/12,m*(x*x+y*y)/12]
ET.SubElement(inertial,"inertia",ixx=f"{I[0]:.12g}",iyy=f"{I[1]:.12g}",izz=f"{I[2]:.12g}",ixy="0",ixz="0",iyz="0")
for part in manifest:
    visual=ET.SubElement(link,"visual",name=part["name"])
    ET.SubElement(visual,"origin",xyz="0 0 0",rpy="0 0 0")
    geo=ET.SubElement(visual,"geometry")
    ET.SubElement(geo,"mesh",filename=part["file"],scale="1 1 1")
    mat=ET.SubElement(visual,"material",name=part["name"])
    # Blender stores linear RGB; URDF colors are written as sRGB-like display values.
    rgba=np.asarray(part["rgba"])
    rgb=np.where(rgba[:3]<=.0031308,12.92*rgba[:3],1.055*rgba[:3]**(1/2.4)-.055)
    ET.SubElement(mat,"color",rgba=" ".join(f"{v:.5f}" for v in [*rgb,1]))

# Include modeled controls and face panels in the body hull. Lens protrusions
# remain separate, preventing a full-depth box from filling the entire camera.
visual=trimesh.load_scene(ROOT/"assets/meshes/x5_visual.obj").to_mesh()
body_points=visual.vertices[np.abs(visual.vertices[:,0])<=.01365]
body=trimesh.convex.convex_hull(body_points)
body.export(out/"body.stl")
collisions=[("body",body)]
# One convex hull per lens; visual ring and convex cap are covered with a tiny margin.
for sign,label in [(1,"front_lens"),(-1,"rear_lens")]:
    points=[]
    for depth,radius in [(12.8,16.1),(14.4,16.1),(15.5,14.7),(16.8,11.5),(18.4,6.4),(19.1,.0)]:
        for a in np.linspace(0,math.tau,48,endpoint=False):
            points.append([sign*depth*.001,radius*.001*math.cos(a),P["lens_center_height_mm"]*.001+radius*.001*math.sin(a)])
    hull=trimesh.convex.convex_hull(np.asarray(points));hull.export(out/(label+".stl"))
    collisions.append((label,hull))
for name,_ in collisions:
    co=ET.SubElement(link,"collision",name=name)
    ET.SubElement(co,"origin",xyz="0 0 0",rpy="0 0 0")
    geo=ET.SubElement(co,"geometry");ET.SubElement(geo,"mesh",filename=f"../assets/meshes/collision/{name}.stl",scale="1 1 1")

# Mount is exactly the URDF root origin. Lens surface frames are geometric markers,
# deliberately not named optical frames because optical centers are uncalibrated.
# Local +Z follows the outward surface normal, matching the catalog builders.
for name,pos,rpy in [("x5_mount",(0,0,0),(0,0,0)),("x5_front_lens_surface",(.0191,0,P["lens_center_height_mm"]*.001),(-math.pi/2,0,-math.pi/2)),("x5_rear_lens_surface",(-.0191,0,P["lens_center_height_mm"]*.001),(-math.pi/2,0,math.pi/2))]:
    ET.SubElement(robot,"link",name=name)
    joint=ET.SubElement(robot,"joint",name=name+"_fixed",type="fixed")
    ET.SubElement(joint,"parent",link="x5_link");ET.SubElement(joint,"child",link=name)
    ET.SubElement(joint,"origin",xyz=" ".join(map(str,pos)),rpy=" ".join(f"{value:.12g}" for value in rpy))
ET.indent(robot,space="  ")
ET.ElementTree(robot).write(ROOT/"urdf/x5.urdf",encoding="utf-8",xml_declaration=True)
print(json.dumps({"inertia_kg_m2":I,"collision_triangles":{n:len(mesh.faces) for n,mesh in collisions}},indent=2))
