# ----------------------------------------------------------------------
# Defincion de librerias
# ----------------------------------------------------------------------
import sys
import ctypes
import tempfile
import shutil
import re
import os
from main_window import MainWindow
from PyQt6.QtWidgets import QApplication

# ----------------------------------------------------------------------
# Funciones auxiliares
# ----------------------------------------------------------------------
"""Verifica si el script se está ejecutando con privilegios de administrador."""
def is_admin():

    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

"""Relanza el script con permisos de administrador usando pythonw.exe (sin consola)."""
def restart_as_admin():
    script = os.path.abspath(sys.argv[0])
    pythonw = sys.executable.replace("python.exe", "pythonw.exe")
    ctypes.windll.shell32.ShellExecuteW(None, "runas", pythonw, f'"{script}"', None, 1)
    sys.exit(0)

# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------
if __name__ == "__main__":
    if not is_admin():
        restart_as_admin()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())