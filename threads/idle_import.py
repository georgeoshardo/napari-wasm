"""Can a thread import an extension module while the main thread is idle in the browser?

napari's worker threads import scipy and scikit-image modules while the main
thread sits in the event loop. The main thread has to load each new module too,
which it does outside Python, without the GIL.
"""

import asyncio
import threading
import time

import js

await js.pyodide.loadPackage("scipy")  # noqa: F704 -- test.html runs this with top-level await

done = {}


def target():
    start = time.perf_counter()
    import scipy.ndimage  # noqa: F401

    done["seconds"] = time.perf_counter() - start


thread = threading.Thread(target=target)
thread.start()
for _ in range(100):
    await asyncio.sleep(0.1)  # noqa: F704
    if not thread.is_alive():
        break
result = f"imported in {done['seconds']:.2f} s" if done else "still importing after 10 s"
js.threadsLog(f"scipy.ndimage in a thread, main idle: {result}")
js.document.title = "threads test: done"
