"""Render the delivered GLB itself with Cycles, physical studio lights and shadows.

Use the separate Python 3.13 Blender environment from requirements-blender.txt.
The renderer never substitutes product photographs or render-only geometry.
"""
from pathlib import Path
import argparse
import json
import math
import sys
import hashlib
import bpy
from mathutils import Vector

ROOT=Path(__file__).resolve().parents[1]


def aim(obj,target):
    obj.rotation_euler=(Vector(target)-obj.location).to_track_quat('-Z','Y').to_euler()


def render(model_id,views,size,samples):
    bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
    bpy.data.orphans_purge(do_recursive=True)
    folder=ROOT/'models'/model_id
    meta=json.loads((folder/'model.json').read_text())
    p=json.loads((folder/meta['config']).read_text())
    bpy.ops.import_scene.gltf(filepath=str(folder/meta['visual']))
    meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
    points=[o.matrix_world@Vector(v) for o in meshes for v in o.bound_box]
    low=Vector([min(v[i] for v in points) for i in range(3)])
    high=Vector([max(v[i] for v in points) for i in range(3)])
    center=(low+high)/2;span=max(high-low)
    scene=bpy.context.scene
    scene.render.engine='CYCLES'
    scene.cycles.samples=samples
    scene.cycles.use_denoising=True
    scene.cycles.max_bounces=8
    scene.cycles.diffuse_bounces=3
    scene.cycles.glossy_bounces=5
    scene.render.resolution_x=size;scene.render.resolution_y=size
    scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG'
    scene.render.image_settings.color_mode='RGBA'
    scene.render.film_transparent=False
    scene.world.use_nodes=True
    scene.world.node_tree.nodes['Background'].inputs['Color'].default_value=(.78,.80,.84,1)
    scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value=.6
    scene.view_settings.view_transform='AgX'
    scene.view_settings.look='AgX - Medium High Contrast'
    scene.view_settings.exposure=.6
    # Every light uses the same size/energy per physical scale, so white capsules
    # and black action cameras get comparable studio illumination.
    scale=span/.1
    for name,offset,energy,dims,color in [
        ('large_softbox',(1.8,-1.4,2.1),9,(2.2,2.8),(1,.96,.90)),
        ('front_fill',(2.3,2.0,.8),3,(1.8,2.2),(.90,.95,1)),
        ('edge_strip',(-1.4,.9,1.8),7,(.55,2.5),(1,1,1)),
        ('overhead',(.3,.1,3.2),4,(1.8,1.8),(1,1,1))]:
        data=bpy.data.lights.new(name,'AREA');data.shape='RECTANGLE'
        data.energy=energy*.04*scale*scale;data.size=dims[0]*span;data.size_y=dims[1]*span;data.color=color
        obj=bpy.data.objects.new(name,data);scene.collection.objects.link(obj)
        obj.location=center+Vector(offset)*span;aim(obj,center)
    bpy.ops.mesh.primitive_plane_add(size=span*200,location=(0,0,low.z-.00012))
    floor=bpy.context.object;floor.name='studio_floor'
    mat=bpy.data.materials.new('studio_neutral');mat.use_nodes=True
    mat.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value=(.68,.70,.72,1)
    mat.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value=.82
    floor.data.materials.append(mat)
    data=bpy.data.cameras.new('product_camera');cam=bpy.data.objects.new('product_camera',data)
    scene.collection.objects.link(cam);scene.camera=cam
    data.type='ORTHO';data.ortho_scale=span*1.34;data.clip_start=.0001;data.clip_end=100
    directions={'hero':(1.8,1.1,.55),'back':(-1.8,-1.1,.55),'front':(3,0,.0),
                'rear':(-3,0,0),'right':(0,3,0),'left':(0,-3,0),'top':(.001,0,3)}
    target=center.copy()
    output=folder/'preview';output.mkdir(exist_ok=True)
    record_path=output/'studio_render.json'
    record=json.loads(record_path.read_text()) if record_path.exists() else {}
    glb_sha=hashlib.sha256((folder/meta['visual']).read_bytes()).hexdigest()
    if record.get('glb_sha256')!=glb_sha:record={}
    record.update(glb_sha256=glb_sha,renderer='Blender Cycles',
                  light_scale=.04,world_strength=.6,exposure=.6)
    for view in views:
        cam.location=target+Vector(directions[view])*span
        aim(cam,target)
        scene.render.filepath=str(output/f'studio_{view}.png')
        bpy.ops.render.render(write_still=True)
        record.setdefault('views',{})[view]={'file':f'studio_{view}.png','size_px':size,'samples':samples}
        record_path.write_text(json.dumps(record,indent=2)+'\n')
        print(f'{model_id}: {scene.render.filepath}',flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',default='all')
    parser.add_argument('--views',nargs='+',default=['hero'],choices=['hero','back','front','rear','right','left','top'])
    parser.add_argument('--size',type=int,default=900)
    parser.add_argument('--samples',type=int,default=48)
    args=parser.parse_args()
    ids=[c['id'] for c in json.loads((ROOT/'catalog/cameras.json').read_text())['cameras']]
    if args.model!='all' and args.model not in ids:parser.error('Unknown camera ID')
    for model_id in ids:
        if args.model in ('all',model_id):render(model_id,args.views,args.size,args.samples)


if __name__=='__main__':main()
