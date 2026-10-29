"""Does tokio's multi-threaded runtime run in the threaded Pyodide? (polars
needs it from 1.34 on)."""

import js
import micropip

base = js.location.href.split("?")[0].rsplit("/", 1)[0]
await micropip.install(  # noqa: F704
    f"{base}/../build/threads/dist-tokio/tokio_threads_test-0.1.0-cp313-cp313-pyodide_2025_0_wasm32.whl"
)

import tokio_threads_test

js.threadsLog(tokio_threads_test.run(16))
js.document.title = "threads test: done"
