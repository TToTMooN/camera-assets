"""Smooth, portable detail geometry. Authoring mm, returned meshes in meters."""
from functools import lru_cache
from pathlib import Path
import math
import numpy as np
import trimesh


def basis(normal):
    n = np.asarray(normal, dtype=float)
    n /= np.linalg.norm(n)
    v = np.array([0., 0., 1.]) if abs(n[2]) < .9 else np.array([0., 1., 0.])
    u = np.cross(v, n)
    u /= np.linalg.norm(u)
    v = np.cross(n, u)
    return np.stack([u, v, n], axis=1)


def orient(mesh, center, normal=(1, 0, 0)):
    matrix = np.eye(4)
    matrix[:3, :3] = basis(normal)
    matrix[:3, 3] = np.asarray(center)*.001
    mesh.apply_transform(matrix)
    return mesh


def contour(width, height, radius, steps=24):
    r = max(.001, min(radius, width/2-.001, height/2-.001))
    result = []
    for x, y, start in [(width/2-r, height/2-r, 0), (-width/2+r, height/2-r, 90),
                         (-width/2+r, -height/2+r, 180), (width/2-r, -height/2+r, 270)]:
        for angle in np.linspace(start, start+90, steps, endpoint=False):
            t = math.radians(angle)
            result.append((x+r*math.cos(t), y+r*math.sin(t)))
    return np.array(result)


def rounded_panel(width, height, depth, radius, center, normal=(1, 0, 0), bevel=None, steps=24):
    """True circular edge bevel, smooth contour, and independently flat face normals."""
    radius = min(radius, width/2-.002, height/2-.002)
    b = min(depth*.48, radius*.48, 1.2 if bevel is None else bevel)
    vertices, normals, faces = [], [], []
    rings = []
    for sign in (-1, 1):
        angles = np.linspace(0, math.pi/2, 7)
        if sign == -1:
            angles = angles[::-1]
        for angle in angles:
            inset = b*(1-math.cos(angle))
            z = sign*(depth/2-b+b*math.sin(angle))
            ring = contour(width-2*inset, height-2*inset, radius-inset, steps)
            rings.append(ring)
            vertices.extend(np.column_stack([ring, np.full(len(ring), z)]))
            # Radius center offsets locate the contour's outward unit normal.
            normals_xy = []
            for quarter in range(4):
                for degrees in np.linspace(quarter*90, (quarter+1)*90, steps, endpoint=False):
                    a = math.radians(degrees)
                    normals_xy.append([math.cos(a)*math.cos(angle), math.sin(a)*math.cos(angle), sign*math.sin(angle)])
            normals.extend(normals_xy)
    n = len(rings[0])
    for i in range(len(rings)-1):
        for j in range(n):
            a, bidx = i*n+j, i*n+(j+1)%n
            c, d = (i+1)*n+(j+1)%n, (i+1)*n+j
            faces.extend([[a,bidx,c],[a,c,d]])
    # Separate caps prevent smoothed face normals from rounding the broad planes.
    for sign, ring in [(-1, rings[0]), (1, rings[-1])]:
        off = len(vertices)
        vertices.extend(np.column_stack([ring, np.full(n, sign*depth/2)]))
        normals.extend([[0,0,sign]]*n)
        vertices.append([0,0,sign*depth/2]); normals.append([0,0,sign])
        pole = len(vertices)-1
        for j in range(n):
            tri = [pole,off+j,off+(j+1)%n]
            faces.append(tri if sign == 1 else tri[::-1])
    result = trimesh.Trimesh(np.asarray(vertices)*.001, faces,
        vertex_normals=np.asarray(normals), process=False)
    return orient(result, center, normal)


def lathe(profile, center, normal=(1,0,0), segments=128):
    """Smooth arbitrary-axis solid or hollow radial profile; radius/offset in mm."""
    points, rings, faces = [], [], []
    for radius, offset in profile:
        if radius < 1e-8:
            rings.append([len(points)]); points.append([0,0,offset])
        else:
            rings.append(list(range(len(points),len(points)+segments)))
            points.extend([[radius*math.cos(t),radius*math.sin(t),offset]
                           for t in np.linspace(0,math.tau,segments,endpoint=False)])
    for a,b in zip(rings,rings[1:]):
        for j in range(segments):
            k=(j+1)%segments
            if len(a)==1: faces.append([a[0],b[j],b[k]])
            elif len(b)==1: faces.append([a[j],b[0],a[k]])
            else: faces.extend([[a[j],b[j],b[k]],[a[j],b[k],a[k]]])
    capped = [] if np.allclose(profile[0], profile[-1]) else list(enumerate((rings[0], rings[-1])))
    for side,ring in capped:
        if len(ring)>1:
            pole=len(points);points.append(np.asarray(points)[ring].mean(axis=0))
            for j in range(segments):
                faces.append([pole,ring[(j+1)%segments],ring[j]] if side==0 else [pole,ring[j],ring[(j+1)%segments]])
    mesh=trimesh.Trimesh(np.asarray(points)*.001,faces,process=True)
    mesh.fix_normals()
    mesh=trimesh.graph.smooth_shade(mesh,angle=math.radians(48),facet_minarea=None)
    return orient(mesh,center,normal)


def revolved(profile, center, sign=1, segments=128):
    return lathe(profile,center,(sign,0,0),segments)


def ring(outer, inner, depth, center, normal=(1,0,0), segments=96):
    """Closed annular part, with an actual hole."""
    return lathe([(inner,-depth/2),(outer,-depth/2),(outer,depth/2),
                  (inner,depth/2),(inner,-depth/2)],center,normal,segments)


def frame_ring(width, height, depth, radius, border, center, normal=(1,0,0)):
    from shapely.geometry import Polygon
    outer=Polygon(contour(width,height,radius)*.001)
    inner=Polygon(contour(width-2*border,height-2*border,max(.05,radius-border))*.001)
    mesh=trimesh.creation.extrude_polygon(outer.difference(inner),height=depth*.001,engine='earcut')
    mesh.apply_translation([0,0,-depth*.0005])
    return orient(mesh,center,normal)


def tube_line(points, radius=.08, sections=8):
    """Fine seams or engraving strokes in world-space millimeters."""
    meshes=[]
    for a,b in zip(points,points[1:]):
        a,b=np.asarray(a),np.asarray(b)
        if np.linalg.norm(b-a)>1e-10:
            mesh=trimesh.creation.cylinder(radius=radius,segment=np.array([a,b]),sections=sections)
            mesh.apply_scale(.001)
            meshes.append(mesh)
    return trimesh.util.concatenate(meshes) if meshes else trimesh.Trimesh()


def outline(width,height,radius,center,normal=(1,0,0),stroke=.08):
    xy=contour(width,height,radius,24)
    xy=np.vstack([xy,xy[0]])
    points=np.column_stack([xy,np.zeros(len(xy))])@basis(normal).T+np.asarray(center)
    return tube_line(points,stroke)


def screw(radius, center, normal=(1,0,0)):
    mesh=lathe([(0,-.08),(radius,-.08),(radius*.92,0),(0,0)],center,normal,48)
    return mesh


@lru_cache(maxsize=1)
def _font():
    from fontTools.ttLib import TTFont
    candidates=[Path('/System/Library/Fonts/Helvetica.ttc'),
                Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
                Path('/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf')]
    path=next((p for p in candidates if p.exists()),None)
    if path is None:
        raise RuntimeError('Vector markings require Helvetica, DejaVu Sans, or Liberation Sans')
    return TTFont(path,fontNumber=0)


@lru_cache(maxsize=256)
def _text_shape(text):
    from fontTools.pens.basePen import BasePen
    from shapely.geometry import Polygon, GeometryCollection
    from shapely.affinity import translate
    font=_font();glyphs=font.getGlyphSet();cmap=font.getBestCmap()
    class FlattenPen(BasePen):
        def __init__(self):
            super().__init__(glyphs);self.paths=[];self.path=[]
        def _moveTo(self,p): self.path=[p]
        def _lineTo(self,p): self.path.append(p)
        def _curveToOne(self,p1,p2,p3):
            p0=np.asarray(self.path[-1]);p1,p2,p3=map(np.asarray,(p1,p2,p3))
            for t in np.linspace(0,1,13)[1:]: self.path.append((1-t)**3*p0+3*(1-t)**2*t*p1+3*(1-t)*t*t*p2+t**3*p3)
        def _qCurveToOne(self,p1,p2):
            p0=np.asarray(self.path[-1]);p1,p2=map(np.asarray,(p1,p2))
            for t in np.linspace(0,1,11)[1:]:self.path.append((1-t)**2*p0+2*(1-t)*t*p1+t*t*p2)
        def _closePath(self):
            if len(self.path)>2:self.paths.append(self.path)
            self.path=[]
        def _endPath(self): self._closePath()
    shape=GeometryCollection();advance=0
    for char in text:
        name=cmap.get(ord(char),'.notdef');pen=FlattenPen();glyphs[name].draw(pen)
        glyph=GeometryCollection()
        for points in pen.paths:
            polygon=Polygon(points).buffer(0)
            glyph=glyph.symmetric_difference(polygon)
        shape=shape.union(translate(glyph,xoff=advance))
        advance+=glyphs[name].width
    return shape


def text_mesh(text, height, depth, center, normal=(1,0,0), width=None, angle=0):
    """Actual font outlines with holes, no raster pixels or texture dependency."""
    from shapely.affinity import scale,translate
    shape=_text_shape(text)
    if shape.is_empty:return trimesh.Trimesh()
    x0,y0,x1,y1=shape.bounds
    factor=height/(y1-y0)
    if width is not None:factor=min(factor,width/(x1-x0))
    shape=scale(translate(shape,xoff=-(x0+x1)/2,yoff=-(y0+y1)/2),xfact=factor*.001,yfact=factor*.001,origin=(0,0))
    geoms=list(shape.geoms) if shape.geom_type=='MultiPolygon' else [shape]
    mesh=trimesh.util.concatenate([trimesh.creation.extrude_polygon(p,height=max(depth,.003)*.001,engine='earcut') for p in geoms])
    if angle:mesh.apply_transform(trimesh.transformations.rotation_matrix(angle,[0,0,1]))
    return orient(mesh,center,normal)
