"""Do Python threads run, alongside the main thread and in parallel, with numpy loaded?

1. A thread does numpy work and counts while the main thread, which is the
   browser's, waits in two ways:
   a. time.sleep, which releases the GIL but blocks the page;
   b. asyncio.sleep, which hands control back to the browser. Pyodide doesn't
      release the GIL when it does that, so the thread may get no time here.
2. The same numpy work is timed in one thread, then split across two. numpy
   releases the GIL while sorting, so two threads should take less wall time.
"""

import asyncio
import threading
import time

import js
import numpy as np

js.threadsLog(f"numpy {np.__version__}, threading.active_count() = {threading.active_count()}")

# 1. a background thread while the main thread waits
def start_counting(steps=40):
    progress = {"steps": 0, "done": False, "error": None}

    def background():
        try:
            rng = np.random.default_rng(0)
            for _ in range(steps):
                np.sort(rng.random(400_000))
                progress["steps"] += 1
        except Exception as error:  # reported from the main thread
            progress["error"] = repr(error)
        progress["done"] = True

    start = time.perf_counter()
    thread = threading.Thread(target=background)
    thread.start()
    js.threadsLog(f"thread started in {(time.perf_counter() - start) * 1000:.0f} ms")
    return thread, progress


def report(label, thread, progress, seen):
    if progress["error"]:
        js.threadsLog(f"{label}: thread error {progress['error']}")
    js.threadsLog(f"{label}: count seen by the main thread {seen}, finished: {progress['done']}")


thread, progress = start_counting()
seen = []
for _ in range(100):
    time.sleep(0.1)
    seen.append(progress["steps"])
    if progress["done"]:
        break
report("1a, main thread in time.sleep", thread, progress, seen)
thread.join()

thread, progress = start_counting()
seen = []
for _ in range(50):
    await asyncio.sleep(0.1)  # noqa: F704 -- hands control back to the browser
    seen.append(progress["steps"])
    if progress["done"]:
        break
report("1b, main thread back in the browser", thread, progress, seen)
thread.join()

# 2. parallel speed-up
arrays = [np.random.default_rng(i).random(2_000_000) for i in range(8)]


def sort_all(chunk):
    for array in chunk:
        np.sort(array)


start = time.perf_counter()
sort_all(arrays)
one = time.perf_counter() - start

start = time.perf_counter()
workers = [threading.Thread(target=sort_all, args=(arrays[i::2],)) for i in range(2)]
for worker in workers:
    worker.start()
for worker in workers:
    worker.join()
two = time.perf_counter() - start
js.threadsLog(f"sorting: one thread {one:.2f} s, two threads {two:.2f} s, speed-up {one / two:.2f}x")

js.document.title = "threads test: done"
