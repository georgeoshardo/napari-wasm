"""Stand-ins that let vispy and napari import and draw in Pyodide.

Call ``install()`` before importing vispy or napari. Each patch fills a gap in
the browser build rather than changing behaviour:

* Qt is built without processes, and the default build without threads, so
  ``QProcess`` (and, without threads, ``QThread``, ``QThreadPool``,
  ``QRunnable`` and the mutex classes) are missing from ``PyQt6.QtCore``.
  napari and superqt import them at module level. Without threads the
  stand-ins run thread-pool work on the event loop and leave
  ``QThread.start()`` as a no-op; the threaded build (../threads) has the
  real classes and gets no stand-ins. ``QtTest`` isn't built either.
* ``psutil`` has no WebAssembly build; napari only asks it for total memory.
* vispy reaches OpenGL through ``ctypes``. Its ES2 backend accepts a library
  through ``ctypes.TEST_DLL``; ``ctypes.CDLL(None)`` is Pyodide's main module,
  where Emscripten's WebGL-backed GL functions live.
* A ``QOpenGLWidget``'s drawing never reaches the page in Qt for WebAssembly,
  but a ``QOpenGLWindow`` embedded with ``createWindowContainer`` does. vispy's
  Qt canvas is a ``QOpenGLWidget`` subclass, so ``QOpenGLWidget`` is replaced
  by a widget with the same interface that hosts such a window.
* vispy's font loader and screen-DPI query only know Linux, macOS and
  Windows; glyphs are drawn with Qt instead of FreeType, and the DPI is CSS's
  96.
* vispy's Cython distance-field function is replaced with a scipy one.
* Pyodide gives every thread its browser event loop, which only runs on the
  main thread, and every new loop is another browser loop. Other threads, and
  new loops made after the main thread's own, get asyncio's selector loop
  instead, woken through a pipe since Emscripten has no socket pairs (the
  threaded build's pipes work across threads).
* napari's console runs code in an in-process IPython kernel, which hands each
  request to a new thread when the calling thread's event loop is running, as
  Pyodide's always is. The request runs as an eager task on the main thread
  instead: ordinary code finishes at once, code with top-level ``await``
  finishes in the browser's event loop.
"""

from __future__ import annotations

import ctypes
import re
import sys
import types

import numpy as np


def install():
    _install_qt_thread_stand_ins()
    _install_qt_process_and_test_stand_ins()
    _install_psutil()
    _install_gl_library()
    _install_gl_window_widget()
    _install_vispy_fonts()
    _install_vispy_dpi()
    _install_vispy_sdf()
    _install_thread_event_loops()
    _install_inprocess_kernel_dispatch()


# --- Qt threads ---------------------------------------------------------------


def _install_thread_event_loops():
    import asyncio
    import os
    import threading

    from pyodide.webloop import WebLoopPolicy

    if isinstance(asyncio.get_event_loop_policy(), _ThreadedLoopPolicy):
        return

    class PipeEnd:
        """The part of a socket asyncio uses to wake its loop."""

        def __init__(self, fd):
            self._fd = fd

        def fileno(self):
            return self._fd

        def setblocking(self, flag):
            os.set_blocking(self._fd, flag)

        def recv(self, size):
            return os.read(self._fd, size)

        def send(self, data):
            return os.write(self._fd, data)

        def close(self):
            os.close(self._fd)

    class SelectorLoop(asyncio.SelectorEventLoop):
        def _make_self_pipe(self):
            read_fd, write_fd = os.pipe()
            self._ssock, self._csock = PipeEnd(read_fd), PipeEnd(write_fd)
            self._ssock.setblocking(False)
            self._csock.setblocking(False)
            self._internal_fds += 1
            self._add_reader(self._ssock.fileno(), self._read_from_self)

    class Policy(WebLoopPolicy, _ThreadedLoopPolicy):
        def __init__(self, main_loop):
            super().__init__()
            self._default_loop = main_loop
            self._local = threading.local()

        def get_event_loop(self):
            if threading.current_thread() is threading.main_thread():
                return super().get_event_loop()
            loop = getattr(self._local, "loop", None)
            if loop is None:
                raise RuntimeError(
                    f"There is no current event loop in thread {threading.current_thread().name!r}."
                )
            return loop

        def new_event_loop(self):
            # a loop made on the main thread may be run in another one
            # (tornado's IOLoop, for one)
            if threading.current_thread() is threading.main_thread() and not self._default_loop:
                return super().new_event_loop()
            return SelectorLoop()

        def set_event_loop(self, loop):
            if threading.current_thread() is threading.main_thread():
                super().set_event_loop(loop)
            else:
                self._local.loop = loop

    asyncio.set_event_loop_policy(Policy(asyncio.get_event_loop_policy()._default_loop))

    # Pyodide's asyncio.run reads its JavaScript config, which a thread other
    # than the main one can't touch
    pyodide_run = asyncio.run

    def run(main, *, debug=None, loop_factory=None):
        if threading.current_thread() is threading.main_thread():
            return pyodide_run(main, debug=debug, loop_factory=loop_factory)
        with asyncio.Runner(debug=debug, loop_factory=loop_factory) as runner:
            return runner.run(main)

    asyncio.run = run


def _install_inprocess_kernel_dispatch():
    import asyncio
    import importlib.util

    if importlib.util.find_spec("ipykernel") is None:
        return
    from ipykernel.inprocess.client import InProcessKernelClient

    def _dispatch_to_kernel(self, msg):
        kernel = self.kernel
        if kernel is None:
            raise RuntimeError("Cannot send request. No kernel exists.")
        stream = kernel.shell_stream
        self.session.send(stream, msg)
        msg_parts = stream.recv_multipart()

        def reply(task):
            task.result()
            _idents, reply_msg = self.session.recv(stream, copy=False)
            self.shell_channel.call_handlers_later(reply_msg)

        task = asyncio.Task(
            kernel.dispatch_shell(msg_parts), loop=asyncio.get_event_loop(), eager_start=True
        )
        if task.done():
            reply(task)
        else:
            task.add_done_callback(reply)

    InProcessKernelClient._dispatch_to_kernel = _dispatch_to_kernel


class _ThreadedLoopPolicy:
    """Marks the event loop policy installed by _install_thread_event_loops."""


def _install_qt_thread_stand_ins():
    from PyQt6 import QtCore

    if hasattr(QtCore, "QThread"):
        return

    class QThread(QtCore.QObject):
        started = QtCore.pyqtSignal()
        finished = QtCore.pyqtSignal()

        class Priority:
            InheritPriority = 7

        _main = None

        @classmethod
        def currentThread(cls):
            if cls._main is None:
                cls._main = cls()
            return cls._main

        def start(self, priority=None):
            print(f"wasm_shims: {type(self).__name__}.start() ignored (no threads)")

        def run(self):
            pass

        def isRunning(self):
            return False

        def loopLevel(self):
            return 1  # the browser's event loop is always running

        def isFinished(self):
            return True

        def quit(self):
            pass

        def exit(self, code=0):
            pass

        def wait(self, *args):
            return True

        def requestInterruption(self):
            pass

        def isInterruptionRequested(self):
            return False

        @staticmethod
        def msleep(ms):
            pass

        @staticmethod
        def sleep(s):
            pass

    class QRunnable:
        def __init__(self):
            self._auto_delete = True

        def run(self):
            pass

        def autoDelete(self):
            return self._auto_delete

        def setAutoDelete(self, value):
            self._auto_delete = value

    class QThreadPool(QtCore.QObject):
        _global = None

        @classmethod
        def globalInstance(cls):
            if cls._global is None:
                cls._global = cls()
            return cls._global

        def start(self, runnable, priority=0):
            # run on the event loop, after the caller has connected its signals
            QtCore.QTimer.singleShot(0, runnable.run)

        def tryStart(self, runnable):
            self.start(runnable)
            return True

        def maxThreadCount(self):
            return 1

        def setMaxThreadCount(self, count):
            pass

        def activeThreadCount(self):
            return 0

        def waitForDone(self, msecs=-1):
            return True

        def clear(self):
            pass

    class QMutex:
        def lock(self):
            pass

        def unlock(self):
            pass

        def tryLock(self, *args):
            return True

    class QMutexLocker:
        def __init__(self, mutex):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def unlock(self):
            pass

        def relock(self):
            pass

    for cls in (QThread, QRunnable, QThreadPool, QMutex, QMutexLocker):
        setattr(QtCore, cls.__name__, cls)
    QtCore.QRecursiveMutex = QMutex
    QtCore.QObject.thread = lambda self: QThread.currentThread()
    QtCore.QObject.moveToThread = lambda self, thread: None


def _install_qt_process_and_test_stand_ins():
    """QProcess and QtTest are left out of both builds, with or without threads."""
    import PyQt6
    from PyQt6 import QtCore

    if not hasattr(QtCore, "QProcess"):

        class QProcess(QtCore.QObject):
            """napari only uses this to restart itself."""

            @staticmethod
            def startDetached(*args, **kwargs):
                return False

        QtCore.QProcess = QProcess

    if "PyQt6.QtTest" not in sys.modules:
        # vispy's Qt backend imports QtTest for QTest.qWait only
        class QTest:
            @staticmethod
            def qWait(ms):
                QtCore.QCoreApplication.processEvents()

        qt_test = types.ModuleType("PyQt6.QtTest")
        qt_test.QTest = QTest
        sys.modules["PyQt6.QtTest"] = qt_test
        PyQt6.QtTest = qt_test


# --- psutil -------------------------------------------------------------------


def _install_psutil():
    if "psutil" in sys.modules:
        return
    psutil = types.ModuleType("psutil")
    total = 2 * 1024**3  # Pyodide's WebAssembly memory limit

    def virtual_memory():
        return types.SimpleNamespace(total=total, available=total, percent=0.0)

    class Process:
        """What dask asks of the current process (it checks for cpu_affinity)."""

        def __init__(self, pid=None):
            self.pid = 1

        def memory_info(self):
            return types.SimpleNamespace(rss=0, vms=0)

    psutil.virtual_memory = virtual_memory
    psutil.cpu_count = lambda logical=True: 1
    psutil.Process = Process
    sys.modules["psutil"] = psutil


# --- OpenGL -------------------------------------------------------------------


class _MainModuleLoader:
    """What vispy's es2 backend expects in ``ctypes.TEST_DLL``."""

    @staticmethod
    def LoadLibrary(name):
        return ctypes.CDLL(None)


def _install_gl_library():
    ctypes.TEST_DLL = _MainModuleLoader()
    # PyOpenGL (napari imports it for GLError and 3D textures) picks a platform
    # plugin by sys.platform; register one for "emscripten"
    try:
        from OpenGL import PlatformPlugin
    except ImportError:  # PyOpenGL not installed
        return
    if not any(plugin.name == "emscripten" for plugin in PlatformPlugin.registry):
        PlatformPlugin("emscripten", f"{__name__}.EmscriptenPlatform")


def __getattr__(name):
    # PyOpenGL loads its platform plugin while OpenGL.platform is still being
    # imported, so the class can only be defined once it's asked for
    if name == "EmscriptenPlatform":
        return _make_pyopengl_platform()
    raise AttributeError(name)


def _make_pyopengl_platform():
    from OpenGL.platform import baseplatform
    from OpenGL.platform.egl import EGLPlatform

    main = ctypes.CDLL(None)

    class EmscriptenPlatform(EGLPlatform):
        """PyOpenGL platform whose GL and EGL functions come from Pyodide's main module."""

        GLES1 = GLU = GLUT = GLE = None

        @baseplatform.lazy_property
        def GLES2(self):
            return main

        @baseplatform.lazy_property
        def GL(self):
            return main

        @baseplatform.lazy_property
        def EGL(self):
            return main

        @baseplatform.lazy_property
        def GetCurrentContext(self):
            # Qt creates its WebGL contexts through Emscripten's html5 API, not EGL
            current = main.emscripten_webgl_get_current_context
            current.restype = ctypes.c_void_p
            return current

    globals()["EmscriptenPlatform"] = EmscriptenPlatform
    return EmscriptenPlatform


async def install_napari(
    wheel_dir_url, version="0.7.1", mocks=(), requirements=(), constraints=(), console=False
):
    """Install napari and its dependencies with micropip.

    Requirements with no WebAssembly build are registered as installed so the
    resolver skips them: psutil (stood in for here) and, unless ``console`` is
    set, the IPython console chain, which napari only loads for its console
    and which needs the threaded build's pyzmq. Everything else resolves
    normally: Pyodide's builds through the lock file, pure-Python wheels from
    PyPI, and vispy from the wheel made by make_vispy_wheel.py.

    ``mocks`` adds (name, version) pairs to register as installed,
    ``requirements`` adds requirement strings and ``constraints`` limits the
    versions chosen, e.g. to keep a pure-Python package at the version matching
    a compiled one in the lock file.
    """
    import micropip

    for name, mock_version in [
        ("psutil", "7.0.0"),
        *([] if console else [("napari-console", "0.1.4")]),
        ("freetype-py", "2.5.1"),
        *mocks,
    ]:
        micropip.add_mock_package(name, mock_version)
    if console:
        # ipykernel's debugger attaches over sockets, and debugpy's wheel holds
        # Linux libraries; with no module to import, ipykernel goes without it
        micropip.add_mock_package("debugpy", "1.8.17", modules={})
    await micropip.install(
        [
            f"napari=={version}",
            f"{wheel_dir_url}/vispy-0.16.2-py3-none-any.whl",
            *(["napari-console"] if console else []),
            *requirements,
        ],
        # platformdirs 4.14 imports os.geteuid, which Emscripten doesn't have
        constraints=["platformdirs<4.14", *constraints],
    )


def use_vispy(debug=False, repair_shaders=True):
    """Select vispy's PyQt6 canvas with GL ES 2 calls; call after ``install()``.

    ``debug`` checks for a GL error after every call; ``repair_shaders``
    retries shaders that fail to compile with float literals (see
    ``_adapt_shaders``).

    vispy pairs its ES2 GL backend with an EGL canvas when the backend is chosen
    first, so the Qt backend is loaded while the default (desktop GL) is still
    configured, and only then are the GL functions switched to ES2, which also
    makes vispy translate its shaders to GLSL ES 1.00 (raised to 3.00 here).
    """
    import vispy
    from vispy.gloo import gl
    from vispy.gloo.gl import es2

    vispy.use(app="pyqt6")
    _translate_texture_formats(es2)
    _adapt_shaders(es2, repair=repair_shaders)
    target = "es2 debug" if debug else "es2"
    gl.use_gl(target)

    # napari asks for "gl+" (PyOpenGL, for instanced point rendering) and falls
    # back to GL points when that raises; gl+ would skip the GLSL ES translation
    use_gl = gl.use_gl

    def use_es2_only(requested=None):
        if requested and not requested.startswith("es2"):
            raise RuntimeError(f"only vispy's es2 GL backend works in WebGL, not {requested!r}")
        use_gl(requested or target)

    gl.use_gl = use_es2_only


_GL_COMPILE_STATUS = 0x8B81
_SHADER_ERROR = re.compile(r"ERROR: \d+:(\d+):(.*)")
# a float and an int expression in one operation (napari's labels shader:
# "$selection != int(t)", with $selection a float)
_MIXED_OPERANDS = re.compile(r"wrong operand types.*(float.*int|int.*float)")
_INT_CAST = re.compile(r"(?<![\w.])int\s*\(")
# an integer literal: not part of an identifier, a float or a hex number
_INT_LITERAL = re.compile(r"(?<![\w.])(\d+)(?![\w.])")


def _float_literals(line):
    """Write the integer literals in ``line`` as floats, outside ``[...]``."""
    out, depth, start = [], 0, 0
    for i, char in enumerate(line + "\0"):
        if char in "[\0" and depth == 0:
            out.append(_INT_LITERAL.sub(r"\1.0", line[start:i]))
            start = i
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                out.append(line[start : i + 1])
                start = i + 1
    out.append(line[start:])
    return "".join(out)


def _float_casts(line):
    """Wrap the ``int(...)`` casts in ``line`` in ``float(...)``."""
    out, start = [], 0
    for match in _INT_CAST.finditer(line):
        if match.start() < start or line[: match.start()].rstrip().endswith("float("):
            continue
        depth, end = 0, None
        for i in range(match.end() - 1, len(line)):
            depth += {"(": 1, ")": -1}.get(line[i], 0)
            if depth == 0:
                end = i + 1
                break
        if end is None:
            break
        out.append(line[start : match.start()] + f"float({line[match.start() : end]})")
        start = end
    out.append(line[start:])
    return "".join(out)


_GL_FRAGMENT_SHADER = 0x8B30
_ES3_HEADER = """#version 300 es
precision highp float;
precision highp int;
precision highp sampler2D;
precision highp sampler3D;
vec4 _wasm_texture2D(sampler2D s, vec2 uv) { return texture(s, uv); }
vec4 _wasm_texture3D(sampler3D s, vec3 uv) { return texture(s, uv); }
"""
# texture() with a LOD bias only exists in fragment shaders
_ES3_FRAGMENT_HEADER = """vec4 _wasm_texture2D(sampler2D s, vec2 uv, float bias) { return texture(s, uv, bias); }
out vec4 _wasm_FragColor;
"""
# words GLSL ES 3.00 reserves that GLSL ES 1.00 code can use as names (vispy's
# text shader has a variable called "sample")
_ES3_RESERVED = re.compile(
    r"\b(sample|filter|input|output|active|common|partition|resource|patch|"
    r"flat|smooth|centroid|layout|fixed|half|cast|interface|external|"
    r"superp|namespace|using|sizeof)\b"
)
_ES3_RENAMES = [
    (_ES3_RESERVED, r"_wasm_\1"),
    (re.compile(r"\btexture2D\s*\("), "_wasm_texture2D("),
    (re.compile(r"\btexture3D\s*\("), "_wasm_texture3D("),
    (re.compile(r"\bgl_FragDepthEXT\b"), "gl_FragDepth"),
]


# functions that older GLSL lacked, so vispy's shaders define their own; GLSL
# ES 3.00 has them built in and refuses redefinitions
_ES3_BUILTIN_FUNCTION = re.compile(r"^[ \t]*\w+\s+(isnan|isinf|round|trunc)\s*\([^)]*\)\s*\{", re.M)


# built-ins vispy overloads with other signatures (agg.vert: float cross(vec2,
# vec2)): the shader's own function and its calls are renamed, and an overload
# under the new name keeps the built-in signature working
_ES3_OVERLOADED_BUILTINS = {
    "cross": "vec3 _wasm_cross(vec3 a, vec3 b) { return cross(a, b); }\n",
}


def _rename_builtin_overloads(body):
    helpers = ""
    for name, passthrough in _ES3_OVERLOADED_BUILTINS.items():
        if re.search(rf"^[ \t]*\w+\s+{name}\s*\(", body, re.M):
            body = re.sub(rf"\b{name}\s*\(", f"_wasm_{name}(", body)
            helpers += passthrough
    return body, helpers


def _remove_builtin_redefinitions(source):
    while match := _ES3_BUILTIN_FUNCTION.search(source):
        depth, end = 0, len(source)
        for i in range(match.end() - 1, len(source)):
            if source[i] == "{":
                depth += 1
            elif source[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        source = source[: match.start()] + source[end:]
    return source


def _to_glsl_es3(source, fragment):
    """Rewrite a GLSL ES 1.00 shader (what vispy's es2 backend emits) as GLSL ES 3.00.

    WebGL 2 only gives ES 1.00 shaders the ES 2 feature set: no fwidth/dFdx
    (vispy's text and napari's shapes antialias with them) and no sampler3D.
    ``texture2D``/``texture3D`` calls go through helpers defined before any
    vispy code, so they still work inside vispy functions whose sampler
    parameter is named ``texture``, which hides ES 3.00's ``texture()``.
    """
    if "#version 300" in source:
        return source
    lines = [
        line
        for line in source.split("\n")
        if not line.lstrip().startswith(("#version", "#extension"))
    ]
    body = _remove_builtin_redefinitions("\n".join(lines))
    body, overloads = _rename_builtin_overloads(body)
    body = re.sub(r"\battribute\b", "in", body)
    body = re.sub(r"\bvarying\b", "in" if fragment else "out", body)
    for pattern, replacement in _ES3_RENAMES:
        body = pattern.sub(replacement, body)
    header = _ES3_HEADER + overloads
    if fragment:
        body = re.sub(r"\bgl_FragData\s*\[\s*0\s*\]", "_wasm_FragColor", body)
        body = re.sub(r"\bgl_FragColor\b", "_wasm_FragColor", body)
        header += _ES3_FRAGMENT_HEADER
    return header + body


def _repair_shader(source, errors):
    """Rewrite the lines in ``errors`` (line number -> messages) for GLSL ES."""
    lines = source.split("\n")
    for number, messages in errors.items():
        line = lines[number - 1] if 0 < number <= len(lines) else ""
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("for"):
            continue
        line = _float_literals(line)
        if any(_MIXED_OPERANDS.search(message) for message in messages):
            line = _float_casts(line)
        lines[number - 1] = line
    return "\n".join(lines)


def _shader_info_log(shader):
    """The whole compile log (vispy's glGetShaderInfoLog stops at 1024 bytes)."""
    main = ctypes.CDLL(None)
    size = 1 << 16
    length = ctypes.c_int(0)
    log = ctypes.create_string_buffer(size)
    main.glGetShaderInfoLog(ctypes.c_uint(shader), size, ctypes.byref(length), log)
    return log.raw[: length.value].decode("utf-8", "replace")


def _adapt_shaders(es2, repair=True, attempts=40):
    """Compile vispy's shaders as GLSL ES 3.00, repairing integer literals.

    Every shader is rewritten as GLSL ES 3.00 (``_to_glsl_es3``). vispy's and
    napari's shaders are desktop GLSL, which converts ``int`` to ``float``
    implicitly (``a_size / 2``, ``mod(t, 256)``, ``f != int(t)``); GLSL ES
    never does. With ``repair``, when a compile fails the integer literals on
    the lines WebGL reports are rewritten as floats (``2`` -> ``2.0``), except
    array indices and ``for`` headers, and on lines where WebGL reports a float
    and an int in one operation ``int(...)`` casts become ``float(int(...))``.
    The shader is compiled again, until it compiles or a pass changes nothing.
    Lines that compile are never touched.
    """
    if getattr(es2, "_wasm_shaders_adapted", False):
        return
    create_shader = es2.glCreateShader
    shader_source, compile_shader = es2.glShaderSource, es2.glCompileShader
    fragment_shaders = set()
    sources = {}

    def glCreateShader(type):
        shader = create_shader(type)
        if type == _GL_FRAGMENT_SHADER:
            fragment_shaders.add(shader)
        return shader

    def glShaderSource(shader, source):
        source = source if isinstance(source, str) else "".join(source)
        source = _to_glsl_es3(source, fragment=shader in fragment_shaders)
        sources[shader] = source
        shader_source(shader, source)

    def glCompileShader(shader):
        compile_shader(shader)
        source = sources.get(shader)
        for _ in range(attempts if repair else 0):
            if source is None or es2.glGetShaderParameter(shader, _GL_COMPILE_STATUS):
                break
            errors = {}
            for number, message in _SHADER_ERROR.findall(_shader_info_log(shader)):
                errors.setdefault(int(number), []).append(message)
            repaired = _repair_shader(source, errors)
            if repaired == source:
                break
            source = repaired
            shader_source(shader, source)
            compile_shader(shader)
        sources.pop(shader, None)

    es2.glCreateShader = glCreateShader
    es2.glShaderSource = glShaderSource
    es2.glCompileShader = glCompileShader
    es2._wasm_shaders_adapted = True


# GL enums used by the texture translation
_UNSIGNED_BYTE, _FLOAT = 0x1401, 0x1406
_ALPHA, _RGB, _RGBA, _LUMINANCE, _LUMINANCE_ALPHA = 0x1906, 0x1907, 0x1908, 0x1909, 0x190A
_RED, _RG = 0x1903, 0x8227
_BASE_FORMATS = {_LUMINANCE: _RED, _ALPHA: _RED, _LUMINANCE_ALPHA: _RG, _RGB: _RGB, _RGBA: _RGBA}
# sized internal format -> (base format, upload type)
_SIZED = {
    0x822E: (_RED, _FLOAT), 0x8230: (_RG, _FLOAT),  # R32F, RG32F
    0x8815: (_RGB, _FLOAT), 0x8814: (_RGBA, _FLOAT),  # RGB32F, RGBA32F
    0x822D: (_RED, _FLOAT), 0x822F: (_RG, _FLOAT),  # R16F, RG16F
    0x881B: (_RGB, _FLOAT), 0x881A: (_RGBA, _FLOAT),  # RGB16F, RGBA16F
    0x8229: (_RED, _UNSIGNED_BYTE), 0x822B: (_RG, _UNSIGNED_BYTE),  # R8, RG8
    0x8051: (_RGB, _UNSIGNED_BYTE), 0x8058: (_RGBA, _UNSIGNED_BYTE),  # RGB8, RGBA8
}
_FLOAT_FORMATS = {_RED: 0x822E, _RG: 0x8230, _RGB: 0x8815, _RGBA: 0x8814}
# 16-bit normalized formats (napari's labels use r16) aren't in WebGL 2: use
# 32-bit float, which holds every 16-bit value exactly (uploads are divided by
# 65535, so they sample the same)
_UNORM16 = {0x822A: _RED, 0x822C: _RG, 0x8054: _RGB, 0x805B: _RGBA}  # R16, RG16, RGB16, RGBA16
# desktop-only capabilities vispy enables (line/point/polygon smoothing, program
# point size, point sprites, multisample): WebGL has no switch for them
_DESKTOP_CAPS = {0x0B20, 0x0B10, 0x0B41, 0x8642, 0x8861, 0x809D}
# unsized renderbuffer format -> sized: RGBA8, RGB8, DEPTH_COMPONENT24, STENCIL_INDEX8
_RENDERBUFFER_FORMATS = {_RGBA: 0x8058, _RGB: 0x8051, 0x1902: 0x81A6, 0x1901: 0x8D48}


def _translate_texture_formats(es2):
    """Make vispy's desktop-style 2D texture and renderbuffer calls valid in WebGL 2.

    vispy allocates every texture as unsigned bytes and uploads the real data
    later, sized formats such as ``r32f`` come paired with ``LUMINANCE``, and
    float data goes into unsized ``LUMINANCE`` textures. Desktop GL converts;
    WebGL 2 needs a sized internal format with a matching ``RED``/``RG``/...
    format and type. Single-channel textures become ``RED``, which samples as
    (r, 0, 0, 1) instead of (l, l, l, 1); vispy's and napari's shaders read
    ``.r``.
    """
    if getattr(es2, "_wasm_translated", False):
        return
    bind_texture, tex_image, tex_sub_image = (
        es2.glBindTexture, es2.glTexImage2D, es2.glTexSubImage2D
    )
    bound = {}  # target -> texture handle
    textures = {}  # texture handle -> [shape, base format, upload type]

    def allocate(target, internalformat, base, gtype, shape):
        tex_image(target, 0, internalformat, base, gtype, shape)
        textures[bound.get(target)] = [shape, base, gtype]

    def glBindTexture(target, texture):
        bound[target] = texture
        bind_texture(target, texture)

    def glTexImage2D(target, level, internalformat, format, type, pixels):
        if level != 0 or not isinstance(pixels, (tuple, list)):
            return tex_image(target, level, internalformat, format, type, pixels)
        if internalformat in _UNORM16:
            base = _UNORM16[internalformat]
            allocate(target, _FLOAT_FORMATS[base], base, _FLOAT, pixels)
        elif internalformat in _SIZED:
            base, gtype = _SIZED[internalformat]
            allocate(target, internalformat, base, gtype, pixels)
        else:
            # unsized: keep it until the first upload says what the data is
            tex_image(target, level, internalformat, format, type, pixels)
            textures[bound.get(target)] = [tuple(pixels), None, type, format]

    def glTexSubImage2D(target, level, xoffset, yoffset, format, type, pixels):
        info = textures.get(bound.get(target))
        if info is None:
            return tex_sub_image(target, level, xoffset, yoffset, format, type, pixels)
        shape, base, gtype = info[:3]
        if base is None:  # unsized texture, first upload
            unsized = info[3]
            if type == _UNSIGNED_BYTE:
                info[1], info[2] = unsized, _UNSIGNED_BYTE
                base, gtype = unsized, _UNSIGNED_BYTE
            else:
                base = _BASE_FORMATS[unsized]
                gtype = _FLOAT
                allocate(target, _FLOAT_FORMATS[base], base, gtype, shape)
        if gtype == _FLOAT and pixels.dtype != np.float32:
            if pixels.dtype == np.uint8:  # normalized, as desktop GL would
                pixels = pixels.astype(np.float32) / 255
            elif pixels.dtype == np.uint16:
                pixels = pixels.astype(np.float32) / 65535
            else:
                pixels = pixels.astype(np.float32)
            type = _FLOAT
        elif gtype == _UNSIGNED_BYTE and type != _UNSIGNED_BYTE:
            pixels = np.clip(np.asarray(pixels) * 255, 0, 255).astype(np.uint8)
            type = _UNSIGNED_BYTE
        tex_sub_image(target, level, xoffset, yoffset, base, type, pixels)

    renderbuffer_storage = es2.glRenderbufferStorage

    def glRenderbufferStorage(target, internalformat, width, height):
        # vispy's color renderbuffers are unsized RGBA
        format = _RENDERBUFFER_FORMATS.get(internalformat, internalformat)
        renderbuffer_storage(target, format, width, height)

    enable, disable = es2.glEnable, es2.glDisable

    def glEnable(cap):
        if cap not in _DESKTOP_CAPS:
            enable(cap)

    def glDisable(cap):
        if cap not in _DESKTOP_CAPS:
            disable(cap)

    es2.glEnable = glEnable
    es2.glDisable = glDisable
    es2.glBindTexture = glBindTexture
    es2.glTexImage2D = glTexImage2D
    es2.glTexSubImage2D = glTexSubImage2D
    es2.glRenderbufferStorage = glRenderbufferStorage
    es2._wasm_translated = True


def _install_gl_window_widget():
    from PyQt6 import QtOpenGLWidgets

    if getattr(QtOpenGLWidgets.QOpenGLWidget, "_wasm_window_widget", False):
        return
    QtOpenGLWidgets.QOpenGLWidget = _make_gl_window_widget()


def _make_gl_window_widget():
    from PyQt6.QtCore import QCoreApplication, QEvent, pyqtSignal
    from PyQt6.QtOpenGL import QOpenGLWindow
    from PyQt6.QtWidgets import QVBoxLayout, QWidget

    forwarded = {
        QEvent.Type.MouseButtonPress,
        QEvent.Type.MouseButtonRelease,
        QEvent.Type.MouseButtonDblClick,
        QEvent.Type.MouseMove,
        QEvent.Type.Wheel,
        QEvent.Type.KeyPress,
        QEvent.Type.KeyRelease,
        QEvent.Type.Enter,
        QEvent.Type.Leave,
        QEvent.Type.NativeGesture,
    }

    class _GLWindow(QOpenGLWindow):
        """Draws for its owner widget and hands it the input events."""

        def __init__(self, owner):
            super().__init__()
            self._owner = owner

        def initializeGL(self):
            self._owner.initializeGL()

        def resizeGL(self, w, h):
            self._owner.aboutToResize.emit()
            self._owner.resizeGL(w, h)
            self._owner.resized.emit()

        def paintGL(self):
            self._owner.aboutToCompose.emit()
            self._owner.paintGL()
            self._owner.frameSwapped.emit()

        def event(self, event):
            if event.type() in forwarded:
                return QCoreApplication.sendEvent(self._owner, event)
            return super().event(event)

    class GLWindowWidget(QWidget):
        """The parts of QOpenGLWidget's interface vispy uses, drawn by a QOpenGLWindow."""

        _wasm_window_widget = True
        aboutToCompose = pyqtSignal()
        frameSwapped = pyqtSignal()
        aboutToResize = pyqtSignal()
        resized = pyqtSignal()

        def __init__(self, parent=None, flags=None):
            if flags is None:
                super().__init__(parent)
            else:
                super().__init__(parent, flags)
            self._gl_window = _GLWindow(self)
            self._gl_container = QWidget.createWindowContainer(self._gl_window, self)
            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(self._gl_container)

        # overridden by subclasses, as with QOpenGLWidget
        def initializeGL(self):
            pass

        def resizeGL(self, w, h):
            pass

        def paintGL(self):
            pass

        def update(self, *args):
            self._gl_window.update()
            super().update(*args)

        def makeCurrent(self):
            self._gl_window.makeCurrent()

        def doneCurrent(self):
            self._gl_window.doneCurrent()

        def context(self):
            return self._gl_window.context()

        def isValid(self):
            return self._gl_window.isValid()

        def format(self):
            return self._gl_window.format()

        def setFormat(self, fmt):
            self._gl_window.setFormat(fmt)

        def defaultFramebufferObject(self):
            return self._gl_window.defaultFramebufferObject()

        def grabFramebuffer(self):
            return self._gl_window.grabFramebuffer()

        def setCursor(self, cursor):
            super().setCursor(cursor)
            self._gl_window.setCursor(cursor)

    return GLWindowWidget


# --- vispy fonts ----------------------------------------------------------------


def _install_vispy_fonts():
    name = "vispy.util.fonts._triage"
    if name in sys.modules:
        return
    triage = types.ModuleType(name)
    triage._load_glyph = _load_glyph
    triage.list_fonts = _list_fonts
    triage._list_fonts = _list_fonts
    sys.modules[name] = triage


_qt_families: dict[str, str] = {}


def _family(face, bold, italic):
    """Qt family for a vispy face, registering vispy's bundled fonts with Qt."""
    from PyQt6.QtGui import QFontDatabase

    from vispy.util.fonts._vispy_fonts import _get_vispy_font_filename, _vispy_fonts

    if face not in _vispy_fonts:
        return face
    key = f"{face}-{bold}-{italic}"
    if key not in _qt_families:
        font_id = QFontDatabase.addApplicationFont(
            _get_vispy_font_filename(face, bold, italic)
        )
        families = QFontDatabase.applicationFontFamilies(font_id)
        _qt_families[key] = families[0] if families else face
    return _qt_families[key]


def _load_glyph(f, char, glyphs_dict):
    """Render one glyph the way vispy's FreeType loader does, but with Qt."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QFont, QFontMetrics, QImage, QPainter

    font = QFont(_family(f["face"], f["bold"], f["italic"]))
    font.setPixelSize(int(f["size"]))
    font.setBold(bool(f["bold"]))
    font.setItalic(bool(f["italic"]))
    metrics = QFontMetrics(font)
    # the ink rectangle relative to the pen position on the baseline, with a
    # pixel of margin for antialiasing
    rect = metrics.tightBoundingRect(char).adjusted(-1, -1, 1, 1)
    width, height = max(rect.width(), 0), max(rect.height(), 0)
    if width and height:
        image = QImage(width, height, QImage.Format.Format_Grayscale8)
        image.fill(0)
        painter = QPainter(image)
        painter.setFont(font)
        painter.setPen(Qt.GlobalColor.white)
        painter.drawText(-rect.left(), -rect.top(), char)
        painter.end()
        ptr = image.constBits()
        ptr.setsize(image.sizeInBytes())
        rows = np.frombuffer(ptr, np.uint8).reshape(height, image.bytesPerLine())
        bitmap = rows[:, :width].copy()
    else:
        bitmap = np.zeros((0, 0), np.uint8)
    glyph = dict(
        char=char,
        offset=(rect.left(), -rect.top()),
        bitmap=bitmap,
        advance=float(metrics.horizontalAdvance(char)),
        kerning={},
    )
    glyphs_dict[char] = glyph
    for other_char, other_glyph in glyphs_dict.items():
        glyph["kerning"][other_char] = 0.0
        other_glyph["kerning"][char] = 0.0


def _list_fonts():
    from PyQt6.QtGui import QFontDatabase

    return list(QFontDatabase.families())


# --- vispy screen DPI -------------------------------------------------------------


def _install_vispy_dpi():
    name = "vispy.util.dpi"
    if name in sys.modules:
        return
    dpi = types.ModuleType(name)
    dpi.__all__ = ["get_dpi"]
    dpi.get_dpi = lambda raise_error=True: 96.0
    sys.modules[name] = dpi


# --- vispy signed distance fields -------------------------------------------------


def _install_vispy_sdf():
    name = "vispy.visuals.text._sdf_cpu"
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    module._calc_distance_field = _calc_distance_field
    sys.modules[name] = module


def _calc_distance_field(pixels, w, h, sp_f):
    """scipy version of vispy's Cython 8SSEDT: fills ``pixels`` in place."""
    from scipy.ndimage import distance_transform_edt

    inner = np.zeros((h, w), bool)
    inner[1:-1, 1:-1] = True
    far = 1e6 * np.sqrt(2)

    def distance_to(seeds):
        if not seeds.any():
            return np.full((h, w), far, np.float32)
        return distance_transform_edt(~seeds).astype(np.float32)

    outside = distance_to(inner & (pixels <= 0))
    inside = distance_to(inner & (pixels >= 1))
    signed = outside - inside
    scale = 1.0 / (sp_f * 2.0)
    signed = np.where(signed < 0, (signed + sp_f) * scale, 0.5 + signed * scale)
    pixels[1:-1, 1:-1] = np.clip(signed, 0, 1)[1:-1, 1:-1]
