"""mm_track on the threaded build: install it and open a trench in the kymograph.

The trench is a copy (data/one_trench.zarr.zip, git-ignored), unpacked into the
browser's in-memory filesystem; mm_track's autosave writes there, never to disk.
"""

import io
import os
import re
import time
import traceback
import zipfile

import js
import micropip

base = js.location.href.split("?")[0].rsplit("/", 1)[0]
log = js.threadsLog
source = await (await js.fetch(f"{base}/../web/wasm_shims.py")).text()  # noqa: F704
with open("/lib/python3.13/site-packages/wasm_shims.py", "w") as file:
    file.write(source)

import wasm_shims

# the mm_track wheel built from the fork, and the versions it is tested with
# (threads/build_mm_track.py)
listing = await (await js.fetch(f"{base}/../build/threads/dist-mmtrack/")).text()  # noqa: F704
mm_track_wheel = re.search(r'href="(mm_track-[^"]+\.whl)"', listing).group(1)
constraints = (
    await (await js.fetch(f"{base}/../build/threads/dist-mmtrack/constraints.txt")).text()  # noqa: F704
).split()
versions = dict(line.split("==") for line in constraints)

# compiled dependencies that curation never imports: the ILP solver, image codecs,
# an HTML cleaner and OpenCV (for the orthogonal views)
for name in ["pyscipopt", "imagecodecs", "lxml-html-clean", "opencv-python-headless"]:
    micropip.add_mock_package(name, versions[name], modules={})

start = time.perf_counter()
await wasm_shims.install_napari(  # noqa: F704
    f"{base}/../web/wheels",
    constraints=constraints,
    requirements=[
        f"{base}/../build/threads/dist-mmtrack/{mm_track_wheel}",
        f"{base}/../web/wheels/numba-0.67.0+python-py3-none-any.whl",
        # the standard library module mm_track keeps its sessions in, which
        # Pyodide ships as a package of its own
        "sqlite3",
    ],
)
log(f"napari and mm_track installed in {time.perf_counter() - start:.1f} s")

data = await (await js.fetch(f"{base}/../data/one_trench.zarr.zip")).arrayBuffer()  # noqa: F704
zipfile.ZipFile(io.BytesIO(data.to_py())).extractall("/home/pyodide")

os.environ["QT_API"] = "pyqt6"
wasm_shims.install()
wasm_shims.use_vispy()

import napari
import napari._qt  # noqa: F401

try:
    start = time.perf_counter()
    from mm_track.__main__ import load_startup_data
    from mm_track.application_menus.main_app import StartupWidget

    log(f"mm_track imported in {time.perf_counter() - start:.1f} s")
    viewer = napari.Viewer(show=True, title="mm_track")
    StartupWidget(viewer, mode="editing")
    start = time.perf_counter()
    load_startup_data(viewer, "/home/pyodide/one_trench.zarr", "trench_1061", kymograph=True)
    log(f"trench loaded in {time.perf_counter() - start:.1f} s: {[layer.name for layer in viewer.layers]}")
except BaseException:
    log("failed:\n" + traceback.format_exc())
    raise
js.document.title = "threads test: done"
