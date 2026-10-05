# GO camera exterior references

These manufacturer-authored renders and annotated manuals are the exterior
references for `scripts/appearance/wearable.py`. They are retained as modeling
references, not used as output model textures. Envelope and mass values remain
the source-grounded values in `catalog/cameras.json`. Small detail proportions,
depths, sealing gaps, docking cavities and mounts are estimated from the views.

| File | Manufacturer source | Applied observations |
| --- | --- | --- |
| `go3s_official.png` | https://res.insta360.com/static/a3b716298df7f6da544fcdaf70ffe21f/GO3S.png | Larger replaceable lens guard and white integrated quick-capture face |
| `go3_official.png` | https://res.insta360.com/static/d78e79ba23e097dc53578184664348ca/GO3.png | Smaller GO 3 lens protector; shared capsule silhouette |
| `go3s_actionpod_official.png` | https://res.insta360.com/dynamic/store/eb7db16e0bde83d9b32b97c18c4fc12e/731_5501c62c-446e-4e6f-a6f6-7c8719e046bf.png | Empty horizontal docking well, diagonal traction ribs and circular six-point contact plate |
| `go3s_manual.pdf` (PDF p. 4 / printed p. 1) | https://res.insta360.com/static/d70a8e271d0c8e5a4b14a658777c1e31/GO%203S_UserManual_EN.pdf | Microphone, front button, status, charging plate, rear ribs and speaker; pod shutter, power/Q buttons, release, USB-C, flip display and mounting latch |
| `go_ultra_official.png`, `go_ultra_gallery.jpg` | https://store.insta360.com/product/go-ultra | Upper-right lens, left mesh microphone, ALS below it, horizontal lower indicator and vertical grip identifier |
| `go_ultra_manual.pdf` (PDF p. 3 / printed p. 1) | https://res.insta360.com/static/780b3076f6404c5ea75e6d56ad04dc34/GOUltra_UserManual_EN.pdf | Square camera, magnetic rear ring and lower contact arc, side lock tabs, microSD door, speaker and lanyard anchor; square pod well |
| `go2_quickstart.pdf` (PDF p. 3 / printed p. 1) | https://res.insta360.com/static/infr_base/ec55c2c18e0035eb799da088ec11ffe8/GO2%20QuickStart%20Guide.pdf | GO 2 round indicator under lens, six rear contacts; closed case lid seam, rear pinhole, USB-C, threaded mounting socket and folded tripod legs |
| `go2_camera_official.svg`, `go2_case_official.svg` | https://www.insta360.com/product/insta360-go2 | Official in-box line drawings for overall component silhouette |

The catalog entries for pods and the charging case remain standalone accessories
in a folded/closed pose, without an installed camera. The cavity is visibly
recessed but has not been measured to validate real docking clearance. The closed
GO 2 case has no exterior display: its controller display and buttons are inside.
