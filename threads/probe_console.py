"""What the console's stack needs from the threaded build: pipes that threads
share, poll() with a timeout, and an asyncio loop in a thread that the main
thread can wake."""

import asyncio
import os
import select
import threading
import time

import js

source = await (await js.fetch("../web/wasm_shims.py")).text()  # noqa: F704
with open("/lib/python3.13/site-packages/wasm_shims.py", "w") as file:
    file.write(source)

import wasm_shims

wasm_shims._install_thread_event_loops()
log = js.threadsLog


def check(label, func):
    try:
        log(f"{label}: {func()}")
    except BaseException as error:
        log(f"{label}: {type(error).__name__}: {error}")


def poll_timeout():
    read_fd, write_fd = os.pipe()
    poller = select.poll()
    poller.register(read_fd, select.POLLIN)
    start = time.perf_counter()
    events = poller.poll(200)
    return f"{events} after {(time.perf_counter() - start) * 1000:.0f} ms (200 asked)"


def pipe_across_threads():
    read_fd, write_fd = os.pipe()
    sent = {}

    def writer():
        time.sleep(0.1)
        sent["at"] = time.perf_counter()
        os.write(write_fd, b"ping")

    thread = threading.Thread(target=writer)
    thread.start()
    poller = select.poll()
    poller.register(read_fd, select.POLLIN)
    poller.poll(2000)
    latency = (time.perf_counter() - sent["at"]) * 1000
    data = os.read(read_fd, 4)
    thread.join()
    return f"{data!r}, woken {latency:.1f} ms after the write"


def loop_in_thread():
    ready = threading.Event()
    result = {}

    async def main():
        result["loop"] = type(asyncio.get_running_loop()).__name__
        result["future"] = asyncio.get_running_loop().create_future()
        ready.set()
        result["value"] = await asyncio.wait_for(result["future"], 5)

    thread = threading.Thread(target=lambda: asyncio.run(main()))
    thread.start()
    ready.wait(5)
    loop = result["future"].get_loop()
    start = time.perf_counter()
    loop.call_soon_threadsafe(result["future"].set_result, "set from the main thread")
    thread.join(5)
    elapsed = (time.perf_counter() - start) * 1000
    return f"{result['loop']}: {result.get('value')!r} in {elapsed:.1f} ms"


check("poll timeout", poll_timeout)
check("pipe across threads", pipe_across_threads)
check("asyncio loop in a thread", loop_in_thread)
check("main loop still Pyodide's", lambda: type(asyncio.get_event_loop()).__name__)
js.document.title = "threads test: done"
