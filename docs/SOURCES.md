# References and accuracy

The authoritative project data is [catalog/cameras.json](../catalog/cameras.json).
Every entry has `sources` with a URL, title and `fields` identifying exactly which
nominal values the source supports. `estimated_geometry` identifies inferred
geometry; `accuracy_notes` records configuration and version limits. Catalog
dimensions are normalized to width, height and depth in millimeters, and mass is
converted to kilograms. A dimension order printed on a manufacturer page should
not be assumed to match the project coordinate order.

Exterior details use manufacturer product photographs, parts diagrams and
mechanical views to distinguish each model. Reference indexes
are linked in [appearance notes](APPEARANCE.md). Images remain local references;
exported texture maps are independently generated surface normals. Fine geometry
and optical layers are estimates, even where their layout follows an official view.

## Specification sources

- [X6 hardware specifications and X series comparison](https://onlinemanual.insta360.com/x6/en-us/specs/hardware): X6, X5, X4 Air, X4, X3, ONE X2 and ONE X nominal envelope and mass; published body depth where available.
- [GO 3S hardware specifications](https://onlinemanual.insta360.com/go3s/en-us/specs/hardware): standalone GO 3S and GO 3, and folded Action Pod.
- [GO Ultra official product specifications](https://www.insta360.com/product/insta360-go-ultra): standalone GO Ultra dimensions with and without Lens Guard. The [GO series hardware manual](https://onlinemanual.insta360.com/go3s/en-us/specs/hardware) supplies the folded Ultra Action Pod envelope, including the unrounded 33.25 mm depth, and Pod-only mass.
- [GO 2 official product specifications](https://www.insta360.com/product/insta360-go2): standalone camera and closed Charging Case.
- [Ace Pro 2 hardware specifications](https://onlinemanual.insta360.com/acepro2/en-us/specs/hardware): Ace Pro 2, Ace Pro and Ace nominal dimensions and mass.
- [ONE RS official product specifications](https://www.insta360.com/product/insta360-oners): complete 4K Boost, 360 Lens and 1-Inch Wide Angle configurations.
- [ONE RS 1-Inch 360 Edition official product specifications](https://www.insta360.com/product/insta360-oners/1inch-360): complete vertical 360 configuration.
- [ONE R Twin Edition official product specifications](https://www.insta360.com/product/insta360-oner_twin-edition): complete 4K Wide Angle and Dual-Lens 360 configurations.
- [ONE R 1-Inch Edition official product specifications](https://www.insta360.com/product/insta360-oner_1inch-edition): complete 1-Inch configuration.
- [RealSense D400 series datasheet, Revision 021, October 2025](https://dev.realsenseai.com/download/42003/): D435i nominal envelope and mass (Table 3-52), and D455 nominal envelope and mass (Table 3-53).
- [Stereolabs ZED 2i official store](https://www.stereolabs.com/store/products/zed-2i): nominal exterior and mass.
- [Luxonis OAK-D official datasheet](https://github.com/luxonis/oak-hardware/blob/master/BW1098OAK_USB3C/Datasheet/OAK-D_Datasheet.pdf): December 2021 mechanical drawing on page 5 gives the original enclosure dimensions.
- [Archived Luxonis hardware documentation, mirrored by Distrelec](https://media.distrelec.com/Web/Downloads/_t/ds/A00110-INTL_eng_tds.pdf): manufacturer-authored Dimensions and Weight section gives 115 g total original OAK-D mass; this is a legacy nominal value rather than a certification of the currently sold SKU.

The X5 exterior also uses [official component diagrams](https://onlinemanual.insta360.com/x5/en-us/camera/productdescription/first)
and [official product photographs](https://store.insta360.com/product/x5) as visual
references. No product photograph or purchased mesh is redistributed.

## Modeling limits

Published envelope dimensions, display dimensions where provided, and nominal
mass are sourced values. Body depth is estimated when the source publishes only overall
depth. Lens curvature and position, controls, ports, screen placement, body
rounding, colors, mounts, center of mass and inertia are independently estimated.
The detailed X5 display size follows official specifications; its other small
features are still inferred. None of the assets has been checked against a
physical specimen or a calibrated imaging model.

Action Pod and Charging Case masses exclude their standalone cameras. Folded or
closed accessory envelopes describe the listed pose; they do not establish the
fit of a docked camera, a docking transform or articulated motion. Modular ONE R
and ONE RS entries represent fixed complete configurations, including the
manufacturer's nominal core, lens and battery combination.

GO 3 and GO 3S share the Action Pod catalog geometry. The [official GO 3S Action
Pod listing](https://store.insta360.com/product/go-3s-action-pod) confirms support
for both cameras; the [GO 3S user manual](https://res.insta360.com/static/d70a8e271d0c8e5a4b14a658777c1e31/GO%203S_UserManual_EN.pdf)
requires updated firmware for GO 3S with an original GO 3 Action Pod. This hardware
compatibility does not validate the proxy's docking geometry.

Ace Pro 2 official pages contain version-dependent mass values. The catalog uses
the hardware manual's standard version and records the alternate published
values in that entry's accuracy notes. For a measured payload or mass-sensitive
simulation, replace the nominal value with the mass of the actual hardware.

RealSense masses have a manufacturer ±10% tolerance; the datasheet notes that bulk
units can omit an approximately 2.3 g USB cap. The ZED 2i [official hardware
documentation](https://www.stereolabs.com/docs/products/cameras/zed/specifications)
and Rev 1.2 datasheet use rounded dimensions and 229 g; this catalog consistently
uses the store values and records the discrepancy. The OAK-D datasheet p1 has a
conflicting compact-envelope line; the original enclosure uses its p5 drawing.
The archived OAK-D 115 g mass has not been independently checked for the current
retail hardware. Reweigh the actual device for mass-sensitive work.

Depth and stereo entries are exterior hardware proxies. Their aperture positions,
optical centers and mounting reference remain estimated. They do not provide
calibrated stereo baselines, disparity, depth output or a simulated sensing model.
Cables, brackets and connector operating clearance are not part of the envelopes.

Validation checks asset consistency, nominal envelope, file portability,
collision coverage and physical-property plausibility. It does not certify
optical performance, measured dynamics, waterproofing, mount strength or
simulator-specific appearance.
