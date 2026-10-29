"""Does a new thread make progress while the main thread is blocked?

Each case starts a fresh thread while the main thread sits in time.sleep (which
releases the GIL) and records how far the thread got after 2 s.
"""

import threading
import time

import js
import numpy as np


def run(label, work):
    progress = {"steps": 0}

    def target():
        for _ in range(20):
            work()
            progress["steps"] += 1

    thread = threading.Thread(target=target)
    thread.start()
    seen = []
    for _ in range(20):
        time.sleep(0.1)
        seen.append(progress["steps"])
    js.threadsLog(f"{label}: {seen}")
    thread.join()


def pure_python():
    sum(i * i for i in range(20_000))


rng = np.random.default_rng(0)
data = rng.random(400_000)


def numpy_sort():
    np.sort(data)


def numpy_random():
    np.random.default_rng(1).random(400_000)


for label, work in [
    ("pure Python, first thread", pure_python),
    ("pure Python, second thread", pure_python),
    ("np.sort", numpy_sort),
    ("np.random", numpy_random),
]:
    run(label, work)
js.document.title = "threads test: done"
