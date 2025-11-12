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

# Checks if the current process is running with administrator privileges on Windows
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

# Restarts the application with administrator privileges (Windows only)
# Uses ShellExecuteW to request elevation and re-run the script with admin rights
def restart_as_admin():
    script = os.path.abspath(sys.argv[0])
    pythonw = sys.executable.replace("python.exe", "pythonw.exe")
    try:
        ctypes.windll.shell32.ShellExecuteW(None, "runas", pythonw, f'"{script}"', None, 1)
        sys.exit(0)
    except Exception as e:
        print("Elevation failed:", e)


# Loads and reads a QSS stylesheet file from the given file path
# Returns the stylesheet content as a string, or an empty string if the file is not found
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
