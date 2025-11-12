"""
MAIN FILE
Provides:
- Permissions verification
- Program style definition
- Beggining of the file
"""

# ---------------------------
# Import libraries and modules
# ---------------------------
import sys
import ctypes
import os
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication
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


def load_stylesheet(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        print(f"Stylesheet not valid")
        return ""

if __name__ == "__main__":
    if not is_admin():
        restart_as_admin()

    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon("icon.ico"))
    style_path = os.path.join(os.path.dirname(__file__), "style.qss")
    app.setStyleSheet(load_stylesheet(style_path))
    win = MainWindow()
    win.showMaximized()
    sys.exit(app.exec())
