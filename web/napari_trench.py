"""A mother machine trench (images, segmentation, tracks) in napari.

Reads data/<trench>.zarr (&trench=trench_1061 by default) over HTTP and prints
how long each step takes and how long napari takes to change frame.
"""

import os
import time

import js
import micropip
import wasm_shims

params = dict(p.split("=", 1) if "=" in p else (p, "") for p in js.location.search[1:].split("&") if p)
trench = params.get("trench", "trench_1061")
base = js.location.href.split("?")[0].rsplit("/", 1)[0]
root = f"{base}/../data/{trench}.zarr"

timings = {}
start = time.perf_counter()
await wasm_shims.install_napari(f"{base}/wheels")  # noqa: F704 -- run.html runs this with top-level await
await micropip.install("zstandard")  # noqa: F704
timings["install packages"] = time.perf_counter() - start

os.environ["QT_API"] = "pyqt6"
wasm_shims.install()
wasm_shims.use_vispy(debug="debug" in params)

import napari
import napari._qt  # noqa: F401 -- napari.Viewer falls back to no window if this fails
import numpy as np
import zarr_fetch

start = time.perf_counter()
images = await zarr_fetch.read_array(f"{root}/images")  # noqa: F704
segmentation = await zarr_fetch.read_array(f"{root}/segmentation")  # noqa: F704
node_ids, props, edges = await zarr_fetch.read_geff(f"{root}/tracking_graph.geff")  # noqa: F704
timings["fetch and decode data"] = time.perf_counter() - start

# napari tracks: one row per node, [track id, t, y, x]; a division links each
# daughter tracklet to its mother
tracklet = props["tracklet"].astype(np.int64)
tracks = np.column_stack([tracklet, props["time"], props["y"], props["x"]]).astype(float)
tracks = tracks[np.lexsort((tracks[:, 1], tracks[:, 0]))]
tracklet_of = dict(zip(node_ids.tolist(), tracklet.tolist()))
graph = {}
for source, target in edges.tolist():
    mother, daughter = tracklet_of[source], tracklet_of[target]
    if mother != daughter:
        graph.setdefault(daughter, []).append(mother)

start = time.perf_counter()
viewer = napari.Viewer(show=True, title=trench)
image_layer = viewer.add_image(images, name="images", colormap="gray")
labels_layer = viewer.add_labels(segmentation, name="segmentation", opacity=0.4)
tracks_layer = viewer.add_tracks(tracks, graph=graph, name="tracks", tail_length=60)
timings["create viewer and layers"] = time.perf_counter() - start

print(
    f"{trench}: images {images.shape} {images.dtype}, segmentation {segmentation.dtype} "
    f"with {len(np.unique(segmentation)) - 1} labels, {len(node_ids)} nodes, "
    f"{len(edges)} edges, {len(graph)} divisions"
)


def frame_rate(frames=100):
    """Change frame ``frames`` times and report napari's slicing time per frame."""
    first = viewer.dims.current_step[0]
    start = time.perf_counter()
    for t in range(first, first + frames):
        viewer.dims.set_current_step(0, t % images.shape[0])
    per_frame = (time.perf_counter() - start) / frames
    print(f"changing frame: {per_frame * 1000:.1f} ms per frame (slicing, without drawing)")
    return per_frame


for step, seconds in timings.items():
    print(f"{step}: {seconds:.1f} s")
frame_rate()
print("viewer shown with", [layer.name for layer in viewer.layers])
