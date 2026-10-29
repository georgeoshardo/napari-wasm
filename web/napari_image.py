"""Stock napari with one 2D image layer."""

import os

import js
import wasm_shims

base = js.location.href.split("?")[0].rsplit("/", 1)[0]
await wasm_shims.install_napari(f"{base}/wheels")  # noqa: F704 -- run.html runs this with top-level await

os.environ["QT_API"] = "pyqt6"
wasm_shims.install()
wasm_shims.use_vispy(debug="debug" in js.location.search)

import napari
import napari._qt  # noqa: F401 -- napari.Viewer falls back to no window if this fails
import numpy as np

y, x = np.mgrid[0:512, 0:512]
data = (np.sin(x / 25.0) * np.cos(y / 40.0)).astype(np.float32)
data[np.hypot(x - 300, y - 200) < 60] = 1.5

viewer = napari.Viewer(show=True)
layer = viewer.add_image(data, colormap="viridis", name="test image")
print("viewer shown with", viewer.layers)
