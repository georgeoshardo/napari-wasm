"""napari on the threaded build: does it start, and do its worker threads run?

Checks that napari gets Qt's real QThread, then runs a napari thread_worker
that blurs an image with scipy and yields each result to a layer while the
main thread stays in the browser.
"""

import os
import threading
import time

import js
import micropip  # noqa: F401 -- loaded by test.html

base = js.location.href.split("?")[0].rsplit("/", 1)[0]
site_packages = "/lib/python3.13/site-packages"
source = await (await js.fetch(f"{base}/../web/wasm_shims.py")).text()  # noqa: F704
with open(f"{site_packages}/wasm_shims.py", "w") as file:
    file.write(source)

import wasm_shims

start = time.perf_counter()
await wasm_shims.install_napari(  # noqa: F704
    f"{base}/../web/wheels", constraints=["pydantic==2.12.5"]
)
js.threadsLog(f"napari installed in {time.perf_counter() - start:.1f} s")

os.environ["QT_API"] = "pyqt6"
wasm_shims.install()
wasm_shims.use_vispy()

import napari
import napari._qt  # noqa: F401
import numpy as np
from napari.qt.threading import thread_worker
from qtpy.QtCore import QThread
from scipy import ndimage
from skimage import data

js.threadsLog(f"QThread is Qt's own: {QThread.__module__ == 'PyQt6.QtCore'}")

viewer = napari.Viewer(show=True, title="napari")
image = data.camera().astype(np.float32)
layer = viewer.add_image(image, name="camera")
main_thread = threading.get_ident()


@thread_worker
def blur():
    for sigma in range(1, 9):
        yield sigma, threading.get_ident() != main_thread, ndimage.gaussian_filter(image, sigma)


def show(result):
    sigma, elsewhere, blurred = result
    layer.data = blurred
    js.threadsLog(f"sigma {sigma}: blurred on another thread: {elsewhere}")


def finished():
    js.threadsLog("worker finished")
    js.document.title = "threads test: done"


worker = blur()
worker.yielded.connect(show)
worker.finished.connect(finished)
worker.start()
