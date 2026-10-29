"""A vispy SceneCanvas showing an image, inside Qt, in the browser."""

import js
import micropip

base = js.location.href.split("?")[0].rsplit("/", 1)[0]
await micropip.install(  # noqa: F704 -- run.html runs this with top-level await
    ["numpy", "scipy", f"{base}/wheels/vispy-0.16.2-py3-none-any.whl"]
)

import wasm_shims

wasm_shims.install()

import numpy as np
from PyQt6.QtWidgets import QApplication

app = QApplication([])

wasm_shims.use_vispy(debug="debug" in js.location.search)
from vispy import scene

y, x = np.mgrid[0:256, 0:256]
data = (np.sin(x / 20.0) * np.cos(y / 30.0)).astype(np.float32)
data[np.hypot(x - 160, y - 100) < 40] = 1.5

canvas = scene.SceneCanvas(size=(600, 400), title="vispy", show=True)
view = canvas.central_widget.add_view()
image = scene.visuals.Image(data, cmap="viridis", clim=(-1, 1.5), parent=view.scene)
view.camera = scene.PanZoomCamera(aspect=1)
view.camera.set_range()
print("canvas shown:", canvas.context.shared.parser.capabilities)
