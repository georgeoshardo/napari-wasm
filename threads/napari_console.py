"""napari's own console on the threaded build: an in-process IPython kernel,
its output carried by ZeroMQ from the kernel to the console's IOPub thread.

Opens the console; code is then typed into it in the browser.
"""

import os
import time
import traceback

import js

base = js.location.href.split("?")[0].rsplit("/", 1)[0]
source = await (await js.fetch(f"{base}/../web/wasm_shims.py")).text()  # noqa: F704
with open("/lib/python3.13/site-packages/wasm_shims.py", "w") as file:
    file.write(source)

import wasm_shims

log = js.threadsLog
start = time.perf_counter()
await wasm_shims.install_napari(  # noqa: F704
    f"{base}/../web/wheels", constraints=["pydantic==2.12.5"], console=True
)
log(f"napari and its console installed in {time.perf_counter() - start:.1f} s")

os.environ["QT_API"] = "pyqt6"
wasm_shims.install()
wasm_shims.use_vispy()

import napari
import napari._qt  # noqa: F401
from skimage import data

viewer = napari.Viewer(show=True, title="napari")
viewer.add_image(data.camera(), name="camera")
qt_viewer = viewer.window._qt_viewer

try:
    start = time.perf_counter()
    console = qt_viewer.console
    qt_viewer.dockConsole.setVisible(True)
    log(f"console opened in {time.perf_counter() - start:.1f} s: {type(console).__name__}")
except BaseException:
    log("opening the console failed:\n" + traceback.format_exc())
    raise

# typed input is checked through the browser (typing into the console);
# console.execute from here would run inside runPythonAsync's suspendable call
js.window.consoleControl = console._control.toPlainText
js.document.title = "threads test: done"
