"""Read single-chunk zarr arrays over HTTP, without zarr-python.

The trench datasets store each array (zarr v3 for images and segmentation,
zarr v2 inside the GEFF graph) as one zstd-compressed chunk. zarr-python 3
needs a newer numcodecs than Pyodide 0.29 ships, so this reads the metadata
and the one chunk directly; zstandard is a Pyodide package.
"""

from __future__ import annotations

import json

import numpy as np
import zstandard
from pyodide.http import pyfetch

_V3_DTYPES = {
    "bool": "|b1", "int8": "|i1", "uint8": "|u1",
    "int16": "<i2", "uint16": "<u2", "int32": "<i4", "uint32": "<u4",
    "int64": "<i8", "uint64": "<u8", "float32": "<f4", "float64": "<f8",
}


async def _fetch(url):
    response = await pyfetch(url)
    if not response.ok:
        return None
    return await response.bytes()


def _decompress(data, nbytes):
    return zstandard.ZstdDecompressor().decompress(data, max_output_size=nbytes)


async def read_array(url):
    """The numpy array stored at ``url`` (a zarr v3 or v2 array directory)."""
    url = url.rstrip("/")
    meta = await _fetch(f"{url}/zarr.json")
    if meta is not None:
        meta = json.loads(meta)
        shape = tuple(meta["shape"])
        dtype = np.dtype(_V3_DTYPES[meta["data_type"]])
        chunks = tuple(meta["chunk_grid"]["configuration"]["chunk_shape"])
        separator = meta["chunk_key_encoding"]["configuration"].get("separator", "/")
        key = "c" + separator + separator.join("0" * len(shape))
        codecs = [codec["name"] for codec in meta["codecs"]]
        compressed = "zstd" in codecs
        if set(codecs) - {"bytes", "zstd"}:
            raise NotImplementedError(f"zarr codecs {codecs}")
    else:
        meta = json.loads(await _fetch(f"{url}/.zarray"))
        shape = tuple(meta["shape"])
        dtype = np.dtype(meta["dtype"])
        chunks = tuple(meta["chunks"])
        separator = meta.get("dimension_separator", ".")
        key = separator.join("0" * len(shape))
        compressor = meta.get("compressor")
        compressed = compressor is not None
        if compressed and compressor["id"] != "zstd" or meta.get("filters"):
            raise NotImplementedError(f"zarr compressor {compressor}")
    if chunks != shape:
        raise NotImplementedError(f"{url}: {chunks} chunks of a {shape} array")
    data = await _fetch(f"{url}/{key}")
    if data is None:  # chunk never written: all fill value
        return np.full(shape, meta.get("fill_value") or 0, dtype)
    nbytes = int(np.prod(shape)) * dtype.itemsize
    if compressed:
        data = _decompress(data, nbytes)
    return np.frombuffer(data, dtype).reshape(shape).copy()


async def read_geff(url):
    """Nodes and edges of a GEFF graph: ``(node_ids, {prop: values}, edges)``."""
    url = url.rstrip("/")
    attrs = json.loads(await _fetch(f"{url}/.zattrs"))["geff"]
    node_ids = await read_array(f"{url}/nodes/ids")
    edges = await read_array(f"{url}/edges/ids")
    props = {}
    for name in attrs.get("node_props_metadata", {}):
        props[name] = await read_array(f"{url}/nodes/props/{name}/values")
    return node_ids, props, edges
