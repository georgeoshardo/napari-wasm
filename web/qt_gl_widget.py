"""Clear a QOpenGLWidget by calling GL from Python through ctypes.

vispy calls OpenGL the same way. ctypes.CDLL(None) opens the main module, where
Pyodide links Emscripten's WebGL-backed GL layer.
"""

import ctypes

from PyQt6.QtGui import QOpenGLContext, QSurfaceFormat
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtWidgets import QApplication

GL_VERSION = 0x1F02
GL_RENDERER = 0x1F01
GL_SHADING_LANGUAGE_VERSION = 0x8B8C
GL_COLOR_BUFFER_BIT = 0x4000

gl = ctypes.CDLL(None)
gl.glClearColor.argtypes = [ctypes.c_float] * 4
gl.glClear.argtypes = [ctypes.c_uint]
gl.glGetString.argtypes = [ctypes.c_uint]
gl.glGetString.restype = ctypes.c_char_p
gl.glGetError.restype = ctypes.c_uint
print("GL functions found:", gl.glClear, gl.glGetString)


class GreenWidget(QOpenGLWidget):
    def initializeGL(self):
        context = QOpenGLContext.currentContext()
        print("current context:", context, context.format().version() if context else None)
        for name, enum in [
            ("GL_VERSION", GL_VERSION),
            ("GL_RENDERER", GL_RENDERER),
            ("GLSL", GL_SHADING_LANGUAGE_VERSION),
        ]:
            print(f"{name}: {gl.glGetString(enum)}")

    def paintGL(self):
        gl.glClearColor(0.15, 0.65, 0.35, 1.0)
        gl.glClear(GL_COLOR_BUFFER_BIT)
        print("paintGL done, glGetError =", gl.glGetError())


fmt = QSurfaceFormat()
fmt.setVersion(3, 0)  # WebGL 2
QSurfaceFormat.setDefaultFormat(fmt)

app = QApplication([])
widget = GreenWidget()
widget.setWindowTitle("QOpenGLWidget")
widget.resize(400, 300)
widget.show()
print("widget shown")
