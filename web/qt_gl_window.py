"""Clear a QOpenGLWindow embedded in a widget layout, calling GL from Python.

The QOpenGLWidget in qt_gl_widget.py gets a working WebGL 2 context, but its output
never reaches the page. A QOpenGLWindow draws straight to its own canvas;
QWidget.createWindowContainer puts it inside an ordinary widget layout, the
way napari needs its canvas.
"""

import ctypes

from PyQt6.QtGui import QOpenGLContext, QSurfaceFormat
from PyQt6.QtOpenGL import QOpenGLWindow
from PyQt6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

GL_VERSION = 0x1F02
GL_COLOR_BUFFER_BIT = 0x4000

gl = ctypes.CDLL(None)
gl.glClearColor.argtypes = [ctypes.c_float] * 4
gl.glClear.argtypes = [ctypes.c_uint]
gl.glGetString.argtypes = [ctypes.c_uint]
gl.glGetString.restype = ctypes.c_char_p


class GreenWindow(QOpenGLWindow):
    def __init__(self, color):
        super().__init__()
        self.color = color
        self.inits = 0

    def initializeGL(self):
        self.inits += 1
        context = QOpenGLContext.currentContext()
        print(f"{self.color}: initializeGL #{self.inits}", gl.glGetString(GL_VERSION))

    def paintGL(self):
        gl.glClearColor(*self.color, 1.0)
        gl.glClear(GL_COLOR_BUFFER_BIT)


fmt = QSurfaceFormat()
fmt.setVersion(3, 0)
QSurfaceFormat.setDefaultFormat(fmt)

app = QApplication([])

main = QWidget()
main.setWindowTitle("QOpenGLWindow")
main.resize(700, 500)
layout = QVBoxLayout(main)
layout.addWidget(QLabel("Above: a QLabel. Below: a QOpenGLWindow in a container (should be green)."))
embedded = GreenWindow((0.15, 0.65, 0.35))
container = QWidget.createWindowContainer(embedded, main)
container.setMinimumSize(400, 300)
layout.addWidget(container)
main.show()
print("window shown")
