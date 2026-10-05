"""Physical material separation and conservative, low-resolution collision shells."""
from functools import lru_cache
import numpy as np
from PIL import Image
import trimesh


@lru_cache(maxsize=3)
def normal_image(kind):
    size=512
    yy,xx=np.mgrid[:size,:size]
    rng=np.random.default_rng(7201)
    if kind=='rubber':
        # Shallow crossed molded texture, not colored photographic imitation.
        height=.5*np.cos((xx+yy)*np.pi/12)+.5*np.cos((xx-yy)*np.pi/12)
        height+=rng.normal(0,.07,(size,size))
        strength=.33
    elif kind=='metal':
        height=np.repeat(rng.normal(0,.2,(size,1)),size,axis=1)
        strength=.13
    else:
        height=rng.normal(0,.24,(size,size))
        strength=.55
    dy,dx=np.gradient(height)
    n=np.stack([-dx*strength,-dy*strength,np.ones_like(height)],axis=-1)
    n/=np.linalg.norm(n,axis=-1,keepdims=True)
    return Image.fromarray(np.clip((n*.5+.5)*255,0,255).astype(np.uint8),'RGB')


def material_properties(name,overrides):
    optical=any(s in name for s in ('glass','screen','optical'))
    rubber=any(s in name for s in ('rubber','grip','gasket'))
    metal=any(s in name for s in ('metal','silver','mount','screw','ring','aluminum'))
    rough=.085 if optical else .82 if rubber else .3 if metal else .55
    metallic=.08 if optical else .72 if metal else 0.
    params=dict(roughnessFactor=rough,metallicFactor=metallic)
    params.update(overrides.get(name,{}))
    return params


def apply_materials(parts,colors,overrides):
    for name,mesh,material,_ in parts:
        rgba=np.asarray(colors[material],dtype=float)
        props=material_properties(material,overrides)
        kind=None
        if any(s in material for s in ('rubber','grip','gasket')):kind='rubber'
        elif any(s in material for s in ('housing','body','shell','polycarbonate','polymer','battery')):kind='grain'
        elif any(s in material for s in ('aluminum','brushed')):kind='metal'
        if kind:
            props['normalTexture']=normal_image(kind)
        normals=mesh.vertex_normals
        vertices=mesh.vertices
        # Triplanar projection chosen at vertices; mapping scale is physical.
        axes=np.argmax(np.abs(normals),axis=1)
        uv=np.empty((len(vertices),2))
        for axis,pair in [(0,(1,2)),(1,(0,2)),(2,(0,1))]:
            take=axes==axis
            uv[take]=vertices[take][:,pair]*10.
        mesh.visual=trimesh.visual.TextureVisuals(uv=uv,
            material=trimesh.visual.material.PBRMaterial(name=material,
                baseColorFactor=np.round(rgba*255).astype(np.uint8),**props))


def collision_hull(points):
    """Conservative support planes, with exact axial extents and few triangles."""
    from scipy.spatial import HalfspaceIntersection
    points=np.unique(np.asarray(points),axis=0)
    if len(points)<5:return trimesh.convex.convex_hull(points)
    directions=trimesh.creation.icosphere(subdivisions=2).vertices
    directions=np.unique(np.vstack([directions,np.eye(3),-np.eye(3)]),axis=0)
    support=np.max(points@directions.T,axis=0)
    interior=points.mean(axis=0)
    if np.min(support-directions@interior)<1e-10:
        return trimesh.convex.convex_hull(points)
    halfspaces=np.column_stack([directions,-support-1e-10])
    hull=HalfspaceIntersection(halfspaces,interior)
    # STL stores float32 positions. Quantizing before hull construction avoids
    # almost coincident intersections becoming cracks after float32 welding.
    vertices=np.unique(np.round(hull.intersections/1e-6)*1e-6,axis=0)
    return trimesh.convex.convex_hull(vertices.astype(np.float32).astype(np.float64))
