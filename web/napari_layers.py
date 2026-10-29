"""One layer of each 2D type napari ships, to find what fails to draw in WebGL.

Add &nofix to turn off wasm_shims' shader repair and see the raw errors. A
moment after start-up it prints each kind of visual that failed to draw, and why.
"""

import os

import js
import wasm_shims

base = js.location.href.split("?")[0].rsplit("/", 1)[0]
await wasm_shims.install_napari(f"{base}/wheels")  # noqa: F704 -- run.html runs this with top-level await

os.environ["QT_API"] = "pyqt6"
wasm_shims.install()
wasm_shims.use_vispy(
    debug="debug" in js.location.search,
    repair_shaders="nofix" not in js.location.search,
)

import napari
import napari._qt  # noqa: F401 -- napari.Viewer falls back to no window if this fails
import numpy as np
from PyQt6.QtCore import QTimer
from vispy.scene.visuals import VisualNode

# record which visuals fail to draw, and why
failures = {}
node_draw = VisualNode.draw


def recording_draw(self):
    try:
        return node_draw(self)
    except Exception as error:
        failures.setdefault(type(self).__name__, str(error).splitlines()[:4])
        raise


VisualNode.draw = recording_draw

rng = np.random.default_rng(0)
y, x = np.mgrid[0:512, 0:512]
image = (np.sin(x / 25.0) * np.cos(y / 40.0)).astype(np.float32)

labels = np.zeros((512, 512), np.uint16)
labels[40:140, 40:200] = 1
labels[300:450, 80:170] = 2
labels[200:260, 380:480] = 3

viewer = napari.Viewer(show=True)
viewer.add_image(image, colormap="gray", name="image")
viewer.add_labels(labels, name="labels")
viewer.add_shapes(
    [np.array([[60, 300], [160, 300], [160, 420], [60, 420]])],
    shape_type="rectangle", edge_color="cyan", face_color="transparent",
    edge_width=4, name="shapes",
)
viewer.add_vectors(
    np.stack([rng.uniform(0, 512, (30, 2)), rng.normal(0, 15, (30, 2))], axis=1),
    edge_color="yellow", name="vectors",
)
tracks = np.array([[i, t, 100 + 30 * i + 5 * t, 250 + 8 * t] for i in range(3) for t in range(10)])
viewer.add_tracks(tracks, name="tracks")
viewer.add_points(rng.uniform(20, 490, (25, 2)), size=14, face_color="red", name="points")
viewer.reset_view()


def report():
    print("failed visuals:", failures if failures else "none")


QTimer.singleShot(1500, report)
print("viewer shown with", [layer.name for layer in viewer.layers])
