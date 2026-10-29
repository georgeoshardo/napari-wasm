"""Does a thread that imports an extension module stall while the main thread blocks?

Importing an extension module dlopens it, and Emscripten then waits until every
other thread, the main one included, has loaded it too. Each case imports a
numpy extension module the main thread hasn't loaded, from a new thread, while
the main thread waits in time.sleep or in thread.join (with a timeout).
"""

import threading
import time

import js
import numpy  # noqa: F401 -- numpy itself is loaded; its submodules below aren't


def import_in_thread(label, module, wait):
    done = {}

    def target():
        start = time.perf_counter()
        __import__(module)
        done["seconds"] = time.perf_counter() - start

    thread = threading.Thread(target=target)
    thread.start()
    wait(thread)
    result = f"imported in {done['seconds']:.2f} s" if done else "still importing after 5 s"
    js.threadsLog(f"{label}: {result}")
    thread.join()


def sleep_wait(thread):
    for _ in range(50):
        time.sleep(0.1)
        if not thread.is_alive():
            return


def join_wait(thread):
    thread.join(timeout=5)


import_in_thread("numpy.fft, main in time.sleep", "numpy.fft", sleep_wait)
import_in_thread("random, main in time.sleep", "random", sleep_wait)
import_in_thread("numpy.random, main in thread.join", "numpy.random", join_wait)
js.document.title = "threads test: done"
