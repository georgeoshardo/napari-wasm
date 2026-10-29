"""Do Qt's threads work: a QThread and a QThreadPool job doing numpy work, reporting
back to a widget on the main thread through queued signals?

The page stays responsive while they run: the label shows each result as it
arrives, and a QTimer on the main thread keeps ticking.
"""

import threading
import time

import js
import numpy as np
from PyQt6.QtCore import QObject, QRunnable, QThread, QThreadPool, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

app = QApplication([])
window = QWidget()
layout = QVBoxLayout(window)
thread_label = QLabel("QThread: waiting")
pool_label = QLabel("QThreadPool: waiting")
timer_label = QLabel("main-thread timer: 0")
for label in (thread_label, pool_label, timer_label):
    layout.addWidget(label)
window.show()

main_thread = threading.get_ident()


class Worker(QThread):
    progress = pyqtSignal(int, int, bool)

    def run(self):
        rng = np.random.default_rng(0)
        data = rng.random(400_000)
        for step in range(1, 21):
            np.sort(data)
            self.progress.emit(step, threading.get_ident(), threading.get_ident() != main_thread)


class Signals(QObject):
    done = pyqtSignal(float, bool)


class Job(QRunnable):
    def __init__(self):
        super().__init__()
        self.signals = Signals()

    def run(self):
        start = time.perf_counter()
        np.sort(np.random.default_rng(1).random(2_000_000))
        self.signals.done.emit(time.perf_counter() - start, threading.get_ident() != main_thread)


def on_progress(step, ident, other_thread):
    thread_label.setText(f"QThread: step {step}/20, ran on another thread: {other_thread}")
    if step == 20:
        js.threadsLog(f"QThread finished 20 steps on another thread: {other_thread}")


def on_done(seconds, other_thread):
    pool_label.setText(f"QThreadPool: sorted in {seconds:.2f} s, on another thread: {other_thread}")
    js.threadsLog(f"QThreadPool job sorted in {seconds:.2f} s, on another thread: {other_thread}")


ticks = 0


def tick():
    global ticks
    ticks += 1
    timer_label.setText(f"main-thread timer: {ticks}")


timer = QTimer()
timer.timeout.connect(tick)
timer.start(50)

worker = Worker()
worker.progress.connect(on_progress)
worker.finished.connect(lambda: js.threadsLog(f"QThread finished; main-thread timer ticked {ticks} times meanwhile"))
worker.start()

job = Job()
job.signals.done.connect(on_done)
QThreadPool.globalInstance().start(job)

js.threadsLog("QThread and QThreadPool job started")
js.document.title = "threads test: done"
