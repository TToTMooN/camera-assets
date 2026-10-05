# Geometry and materials

Exterior models are built independently from manufacturer product views, component
diagrams and mechanical drawings, constrained by the nominal envelopes in
[the catalog](../catalog/cameras.json). They are reference-based approximations,
not physical scans or manufacturer CAD.

| Model group | Modeled exterior features |
| --- | --- |
| X6, X4 Air, X4, X3 | Model-specific displays and controls, curved dual lenses, retaining rings, layered housings, wind guards, side doors and bottom interfaces |
| ONE X, ONE X2 | Different circular displays, shutter and status controls, capsule-shaped lens heads and body seams |
| GO 2, GO 3, GO 3S | Integrated capture faces, smooth capsule shells, distinct guards and curved lens layers, rear contacts and ribs |
| GO Ultra | Upper-right lens, perforated microphone, ambient light window, full-face button, rear magnetic ring and contacts |
| GO accessories | Recessed Action Pod wells, inner walls, trays, contacts, folded displays and hinges; closed GO 2 case seams, folded tripod legs and interfaces |
| Ace, Ace Pro, Ace Pro 2 | Separate front displays, model-specific indicators, square guards and lens layers, folded rear displays, side doors and latches; Ace Pro 2 perforated wind guard |
| ONE R, ONE RS | Separate lens, core and battery geometry, core rear displays, speaker layouts, square 4K guards, knurled 1-inch rings and dual-sided 360 lenses |
| ONE RS 1-Inch 360 | Wide lens head, core and black battery sections, bracket rails, clips and rear display |
| RealSense, ZED, OAK-D | Distinct housings, optical windows and layers, rear interfaces and mounting holes; D455 four-window layout and original OAK-D T-shaped enclosure |

Rounded bevels use curved geometry. Planar panel and edge normals are separated
to preserve flat faces. Glass, retaining rings, seals and inner lens layers are
separate parts. Lettering uses vector outlines, so these details remain present
in GLB, OBJ, URDF and MJCF exports.

GLB materials distinguish plastic, rubber, metal, displays and coated glass.
Surface normal textures are generated independently and embedded in each GLB;
material color factors use linear RGB. Glass uses reflection and clearcoat
without requiring transmission rendering. URDF and default MJCF exports retain
geometry and colors; PBR and normal-map appearance depends on the renderer.

The `preview/studio_hero.png` and `preview/studio_back.png` images are rendered
from the delivered GLB in Blender Cycles. `preview/studio_render.json` records
the GLB SHA256, views, samples and exposure. Catalog tiles use individual framing;
their dimension labels indicate physical size. `make_catalog_preview.py --software`
produces an overview with a shared physical scale.

Visual and collision meshes are separate. Collision meshes use conservative
convex approximations instead of every small exterior feature. Validation checks
closure, convexity, coverage, envelope dimensions, mass properties and portable
file references. MuJoCo tests check loading and bounded floor contact; they do
not establish measured dynamics or mounting fit.

Nominal envelopes and masses have published sources. Small feature dimensions,
lens profiles, mounting interfaces, center of mass and inertia remain estimates.
Displays are off, accessories are folded or closed, and modular configurations
remain fixed. Imaging parameters and optical frames require separate calibration.

## Reference indexes

- [X series product views](../references/appearance/xseries_sources.json)
- [GO series images and manuals](../references/wearable/SOURCES.json)
- [Ace and ONE R / RS component views](../references/appearance/action/SOURCES.json)
- [Depth and stereo camera references](../references/appearance/stereo/SOURCES.json)

The indexes retain source URLs and modeling observations. Downloaded photographs
and manuals are local references excluded by `.gitignore`; they are not exported
as model textures. No redistribution license for manufacturer imagery is asserted.
