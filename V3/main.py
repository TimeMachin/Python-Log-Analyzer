# main.py
import sys
import ctypes
import os
from PyQt6.QtWidgets import QApplication
from PyQt6 import QtGui
from main_window import MainWindow

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

def restart_as_admin():
    script = os.path.abspath(sys.argv[0])
    pythonw = sys.executable.replace("python.exe", "pythonw.exe")
    try:
        ctypes.windll.shell32.ShellExecuteW(None, "runas", pythonw, f'"{script}"', None, 1)
        sys.exit(0)
    except Exception as e:
        print("Elevation failed:", e)

DARK_STYLESHEET = """
QWidget { background-color: #151617; color: #e6e6e6; font-family: "Segoe UI", sans-serif; font-size: 10pt; }
QTableWidget { background-color: #1f2124; gridline-color: #2b2d31; alternate-background-color: #202225; selection-background-color: #0aa3e6; selection-color: #ffffff; }
QHeaderView::section { background-color: #2a2d31; padding: 6px; border: 1px solid #222; color: #cfd6dc; }
QPushButton { background-color: #2a2d31; border: 1px solid #333; padding: 6px 10px; border-radius: 6px; }
QPushButton:hover { background-color: #32363b; }
QLineEdit, QComboBox { background-color: #202427; border: 1px solid #2f3336; padding: 6px; border-radius: 6px; }
QTreeWidget, QTextEdit { background-color: #0f1112; border: 1px solid #252728; padding: 6px; font-family: "Consolas", monospace; font-size: 10pt; color: #dfeffb; border-radius: 6px; }
QProgressBar { border: 1px solid #2b2d31; background-color: #171819; text-align: center; }
QProgressBar::chunk { background-color: #0aa3e6; }
"""

if __name__ == "__main__":
    if not is_admin():
        restart_as_admin()

    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_STYLESHEET)
    app.setWindowIcon(QtGui.QIcon('./icon.ico'))
    win = MainWindow()
    win.showMaximized()
    sys.exit(app.exec())
