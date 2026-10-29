"""Does a Rust (PyO3) extension built for the threaded Pyodide load and work?

Checks plain calls, a Rust error and a Rust panic turning into Python
exceptions, and a counter updated with atomics from four threads at once,
outside the GIL.
"""

import threading

import js
import micropip

base = js.location.href.split("?")[0].rsplit("/", 1)[0]
await micropip.install(  # noqa: F704 -- test.html runs this with top-level await
    f"{base}/../build/threads/dist-rust/rust_threads_test-0.1.0-cp313-cp313-pyodide_2025_0_wasm32.whl"
)

import rust_threads_test as rt

js.threadsLog(f"add(2, 3) = {rt.add(2, 3)}")
try:
    rt.fails()
except ValueError as error:
    js.threadsLog(f"error from Rust: ValueError({error})")
try:
    rt.panics()
except BaseException as error:  # PyO3 raises PanicException, a BaseException
    js.threadsLog(f"panic from Rust: {type(error).__name__}({error})")

results = []
threads = [threading.Thread(target=lambda: results.append(rt.count(250_000))) for _ in range(4)]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join()
js.threadsLog(f"counter after 4 threads x 250000: {rt.count(0)} (expected 1000000)")
js.document.title = "threads test: done"
