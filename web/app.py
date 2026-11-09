"""The landing page's napari: the whole window, with scikit-image's camera image."""

import os

import js
import wasm_shims

base = js.location.href.split("?")[0].split("#")[0].rsplit("/", 1)[0]

js.napariStatus("Installing napari")
await wasm_shims.install_napari(  # noqa: F704 -- index.html runs this with top-level await
    f"{base}/web/wheels",
    # the pydantic of the threaded build's pydantic-core
    constraints=["pydantic==2.13.5"],
    console=True,
)

js.napariStatus("Starting napari")
os.environ["QT_API"] = "pyqt6"
wasm_shims.install()
wasm_shims.use_vispy()

import napari
import napari._qt  # noqa: F401 -- napari.Viewer falls back to no window if this fails
from skimage import data

viewer = napari.Viewer(show=True, title="napari")
viewer.add_image(data.camera(), name="camera")
# fill the page with no title bar (its close button would leave an empty page)
viewer.window._qt_window.showFullScreen()
js.napariReady()
