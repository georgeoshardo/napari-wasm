"""PyQt6 widgets in the browser: a label and a button wired to a Python slot."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget

app = QApplication([])

window = QWidget()
window.setWindowTitle("Qt")
window.resize(400, 200)
layout = QVBoxLayout(window)
label = QLabel("Clicked 0 times")
label.setAlignment(Qt.AlignmentFlag.AlignCenter)
layout.addWidget(label)
button = QPushButton("Click me")
layout.addWidget(button)

clicks = 0


def on_click():
    global clicks
    clicks += 1
    label.setText(f"Clicked {clicks} times")
    print(f"clicked {clicks}")


button.clicked.connect(on_click)
window.show()
print("window shown")
