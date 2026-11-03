"""Does polars 1.44 (threaded build) work: eager and lazy queries, the streaming
engine (tokio), Float16 (which tracksdata needs), IPC round trips, and its thread
pool?"""

import io
import time

import js
import micropip

# polars-runtime-32 comes from the threaded build's lock file, polars from PyPI
await micropip.install("polars==1.44.1")  # noqa: F704
source = await (await js.fetch("../web/wasm_shims.py")).text()  # noqa: F704
with open("/lib/python3.13/site-packages/wasm_shims.py", "w") as file:
    file.write(source)

import wasm_shims

wasm_shims._configure_thread_pools()  # as wasm_shims.install() does

import polars as pl

log = js.threadsLog
log(f"polars {pl.__version__}, thread pool {pl.thread_pool_size()}")
df = pl.DataFrame({"track": [1, 1, 2, 2, 3], "t": [0, 1, 0, 1, 0], "x": [1.0, 2.0, 3.0, 4.0, 5.0]})
log(f"group_by: {df.group_by('track').agg(pl.col('x').mean()).sort('track').to_dicts()}")
log(f"lazy streaming: {df.lazy().filter(pl.col('t') > 0).select(pl.col('x').sum()).collect(engine='streaming').item()}")
log(f"Float16: {pl.Series([1.5, 2.5], dtype=pl.Float16).dtype}")
buffer = io.BytesIO()
df.write_ipc(buffer)
buffer.seek(0)
log(f"IPC round trip equal: {pl.read_ipc(buffer).equals(df)}")
big = pl.DataFrame({"a": range(5_000_000)}).with_columns((pl.col("a") * 2).alias("b"))
start = time.perf_counter()
total = big.select((pl.col("a") * pl.col("b")).sum()).item()
log(f"sum over 5M rows: {total} in {(time.perf_counter() - start) * 1000:.0f} ms")
js.document.title = "threads test: done"
