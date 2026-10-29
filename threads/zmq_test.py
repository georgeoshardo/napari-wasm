"""Does ZeroMQ work between threads: libzmq's own I/O thread, a PUB socket on
the main thread and a SUB socket in another, and zmq.asyncio in a thread's
event loop (how ipykernel's IOPub thread reads)."""

import asyncio
import threading
import time

import js

await js.pyodide.loadPackage("pyzmq")  # noqa: F704
source = await (await js.fetch("../web/wasm_shims.py")).text()  # noqa: F704
with open("/lib/python3.13/site-packages/wasm_shims.py", "w") as file:
    file.write(source)

import wasm_shims
import zmq
import zmq.asyncio

wasm_shims._install_thread_event_loops()
log = js.threadsLog
log(f"pyzmq {zmq.__version__}, libzmq {zmq.zmq_version()}")

context = zmq.Context.instance()

# a PAIR socket in each thread, blocking receive in the thread
received = []
ready = threading.Event()


def pair_thread():
    socket = context.socket(zmq.PAIR)
    socket.connect("inproc://pair")
    ready.set()
    for _ in range(3):
        received.append(socket.recv_string())
    socket.send_string("thanks")
    socket.close()


server = context.socket(zmq.PAIR)
server.bind("inproc://pair")
thread = threading.Thread(target=pair_thread)
thread.start()
ready.wait(5)
start = time.perf_counter()
for word in ["one", "two", "three"]:
    server.send_string(word)
reply = server.recv_string() if server.poll(5000) else None
log(f"PAIR: thread got {received}, replied {reply!r} in {(time.perf_counter() - start) * 1000:.1f} ms")
thread.join(5)
server.close()

# PUB on the main thread, zmq.asyncio SUB in a thread's event loop
messages = []
subscribed = threading.Event()


async def subscriber():
    socket = zmq.asyncio.Context.instance().socket(zmq.SUB)
    socket.connect("inproc://iopub")
    socket.subscribe(b"")
    subscribed.set()
    while True:
        message = await asyncio.wait_for(socket.recv_string(), 5)
        messages.append(message)
        if message == "done":
            break
    socket.close()


publisher = zmq.asyncio.Context.instance().socket(zmq.PUB)
publisher.bind("inproc://iopub")
thread = threading.Thread(target=lambda: asyncio.run(subscriber()))
thread.start()
subscribed.wait(5)
time.sleep(0.2)  # a SUB socket only gets messages sent after it has joined
start = time.perf_counter()
for message in ["stdout: hello", "stderr: world", "done"]:
    publisher.send_string(message)
thread.join(5)
log(f"PUB/SUB with zmq.asyncio in a thread: {messages} in {(time.perf_counter() - start) * 1000:.1f} ms")
publisher.close()
js.document.title = "threads test: done"
