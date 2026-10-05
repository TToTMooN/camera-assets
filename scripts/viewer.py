"""Local camera viewer: python scripts/viewer.py --model go3s --port 8080."""
from pathlib import Path
import argparse
import json
import threading
import time

ROOT = Path(__file__).resolve().parents[1]


def available_models():
    return {p.name: json.loads((p / "model.json").read_text())
            for p in sorted((ROOT / "models").iterdir())
            if p.is_dir() and (p / "model.json").is_file()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    available = available_models()
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--model", choices=available, default="x5" if "x5" in available else next(iter(available), None))
    parser.add_argument("--list", action="store_true", help="List available camera models and exit")
    args = parser.parse_args(argv)
    if args.list:
        for model_id, meta in available.items():
            print(f"{model_id}\t{meta['name']}")
        return
    if args.model is None:
        parser.error("No models have model.json metadata; build the assets first")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    import trimesh
    import viser

    def load_model(model_id):
        model_dir = ROOT / "models" / model_id
        meta = available[model_id]
        params = json.loads((model_dir / meta["config"]).read_text())
        stats = json.loads((model_dir / "assets/visual_manifest.json").read_text())
        glb = (model_dir / meta["visual"]).read_bytes()
        collision = [(path.stem, trimesh.load_mesh(path))
                     for path in sorted((model_dir / "assets/meshes/collision").glob("*.stl"))]
        return meta, params, stats, glb, collision

    try:
        initial_data = load_model(args.model)
    except (OSError, KeyError, ValueError) as error:
        parser.error(f"Cannot load {args.model}: {error}")
    server = viser.ViserServer(host=args.host, port=args.port, label="Camera Model Library")
    server.gui.configure_theme(dark_mode=True, show_logo=False,
                               show_share_button=False, brand_color=(58, 185, 206))
    server.gui.main_panel.dock_right()
    server.scene.set_up_direction("+z")
    server.scene.configure_default_lights(False)
    server.scene.configure_environment_map("studio", environment_intensity=1.2)
    labels = {f"{meta['name']} ({model_id})": model_id for model_id, meta in available.items()}
    initial_label = next(label for label, model_id in labels.items() if model_id == args.model)
    camera = server.gui.add_dropdown("Camera / accessory", list(labels), initial_value=initial_label)
    description = server.gui.add_markdown("")
    mode = server.gui.add_dropdown("Display", ["PBR visual", "Visual + collision", "Collision only"])
    show_axes = server.gui.add_checkbox("Reference axes", False)
    show_grid = server.gui.add_checkbox("Ground / 10 mm grid", True)
    light = server.gui.add_slider("Studio light", min=.15, max=2.0, step=.05, initial_value=1.2)
    details = server.gui.add_markdown("")
    error_message = server.gui.add_markdown("")
    grid = server.scene.add_grid("/ground", width=.35, height=.35, cell_size=.01, section_size=.05,
        plane="xy", position=(0, 0, -.0005), cell_color=(60, 64, 74), section_color=(89, 98, 113),
        plane_color=(32, 35, 43), plane_opacity=.9, shadow_opacity=.2)
    state = {"handles": [], "visual": None, "wire": [], "axes": None, "views": {}, "target": (0, 0, 0)}
    switch_lock = threading.Lock()

    def set_view(client, name):
        client.camera.up_direction = (0, 1, 0) if name == "Top" else (0, 0, 1)
        client.camera.position = state["views"][name]
        client.camera.look_at = state["target"]
        client.camera.fov = .58
        client.camera.near = .001
        client.camera.far = 10

    def update_visibility():
        state["visual"].visible = mode.value != "Collision only"
        for item in state["wire"]:
            item.visible = mode.value != "PBR visual"

    def display_model(model_id, data=None):
        meta, params, stats, glb, collision = data or load_model(model_id)
        # Finish loading files before removing the previous selection.
        for handle in state["handles"]:
            handle.remove()
        visual = server.scene.add_glb("/camera_visual", glb, wxyz=(2**-.5, 2**-.5, 0, 0))
        wire = [server.scene.add_mesh_simple("/collision/" + name, mesh.vertices, mesh.faces,
                    color=(53, 215, 229), wireframe=True, visible=False, opacity=.55)
                for name, mesh in collision]
        span = max(params[key] for key in ("width_mm", "height_mm", "overall_depth_mm")) * .001
        height = params["height_mm"] * .001
        axes = server.scene.add_frame("/reference", axes_length=span * .24, axes_radius=span * .0028,
                                      visible=show_axes.value)
        target = (0, 0, height / 2)
        offsets = {"Front ¾": (1.8, 1.2, .6), "Back ¾": (-1.8, -1.2, .6),
                   "Front (+X)": (2.3, 0, 0), "Back (−X)": (-2.3, 0, 0),
                   "Right (+Y)": (0, 2.3, 0), "Left (−Y)": (0, -2.3, 0),
                   "Top": (0, 0, 2.3), "Bottom": (.8, .8, -2.3)}
        views = {name: tuple(target[i] + offset[i] * span for i in range(3))
                 for name, offset in offsets.items()}
        state.update(handles=[visual, *wire, axes], visual=visual, wire=wire, axes=axes, views=views, target=target)
        description.content = (f"## {meta['name']}\n{meta.get('status', 'Independent procedural reconstruction.')}\n\n"
            f"**{params['width_mm']:g} × {params['height_mm']:g} × {params['overall_depth_mm']:g} mm · "
            f"{params['mass_kg'] * 1000:g} g**\n\nWidth × height × depth · meter units")
        origin = meta.get("origin_description", "Bottom reference point; physical mount fit is not measured.")
        fidelity = {"detailed_reference_exterior": "Reference-based exterior with modeled controls and materials.",
                    "reference_detailed_exterior": "Reference-informed exterior with independent assemblies, curved optics, modeled controls and surface materials.",
                    "envelope_proxy": "Simplified envelope proxy; exterior details are schematic."}.get(
                        meta.get("fidelity"), meta.get("fidelity", "Published envelope and mass; inferred exterior details."))
        details.content = (f"**{sum(item['triangles'] for item in stats):,} triangles** · {len(stats)} materials\n\n"
            f"Drag to orbit · scroll to zoom\n\n**Geometry:** {fidelity}\n\n"
            f"{params.get('notes', 'Detail positions, COM and inertia are estimates. No optical calibration is supplied.')}\n\n"
            f"**Origin:** {origin}\n\n+X front, +Y right, +Z up. Lens markers are surface references, not calibrated optical frames.")
        error_message.content = ""
        update_visibility()
        for client in server.get_clients().values():
            set_view(client, "Front ¾")

    display_model(args.model, initial_data)

    @camera.on_update
    def _(_event):
        with switch_lock:
            model_id = labels[camera.value]
            try:
                display_model(model_id)
            except (OSError, KeyError, ValueError) as error:
                error_message.content = f"**Could not load {model_id}:** {error}"

    @mode.on_update
    def _(_event):
        update_visibility()

    @show_axes.on_update
    def _(_event):
        state["axes"].visible = show_axes.value

    @show_grid.on_update
    def _(_event):
        grid.visible = show_grid.value

    @light.on_update
    def _(_event):
        server.scene.configure_environment_map("studio", environment_intensity=light.value)

    with server.gui.add_folder("Viewpoints"):
        for name in state["views"]:
            button = server.gui.add_button(name)

            @button.on_click
            def _(event, name=name):
                if event.client is not None:
                    set_view(event.client, name)

    @server.on_client_connect
    def _(client):
        set_view(client, "Front ¾")

    print(f"{available[args.model]['name']} viewer ready: http://{args.host}:{args.port}", flush=True)
    try:
        while True:
            time.sleep(.25)
    except KeyboardInterrupt:
        server.stop()


if __name__ == "__main__":
    main()
