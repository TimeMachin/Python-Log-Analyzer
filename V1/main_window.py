# ----------------------------------------------------------------------
# Defincion de librerias
# ----------------------------------------------------------------------
import os
import tempfile
import shutil
import re
import xml.etree.ElementTree as ET
from PyQt6.QtCore import Qt

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QComboBox, QLineEdit, QTableWidget, QTableWidgetItem, QFileDialog, QMessageBox
)
from event_log_reader import EventLogReader
# Intenta importar la librería para leer archivos EVTX
try:
    from Evtx.Evtx import Evtx
except ImportError:
    Evtx = None


# ----------------------------------------------------------------------
# Funciones auxiliares
# ----------------------------------------------------------------------
"""Copia temporalmente el archivo EVTX (los de System32 suelen estar bloqueados)."""
def safe_copy_evtx(path):
    tmpdir = tempfile.gettempdir()
    dest = os.path.join(tmpdir, os.path.basename(path))
    shutil.copy2(path, dest)
    return dest

"""Elimina xmlns del XML para que ElementTree pueda procesarlo."""
def strip_xml_namespace(xml_text: str) -> str:
    return re.sub(r'\sxmlns="[^"]+"', '', xml_text, count=1)

"""Parses a single EVTX event XML and returns a dictionary with main fields."""
def parse_event_xml(xml_text):
    try:
        if not xml_text:
            return None
        print("Este es el evento: ", xml_text)
        xml_text = strip_xml_namespace(xml_text)
        root = ET.fromstring(xml_text)

        system = root.find("System")
        event_data = root.find("EventData")

        provider = ""
        if system is not None:
            prov = system.find("Provider")
            if prov is not None:
                provider = prov.attrib.get("Name", prov.text or "")

        event_id = system.findtext("EventID", "") if system is not None else ""
        level = system.findtext("Level", "") if system is not None else ""
        time_created = ""
        if system is not None:
            tc = system.find("TimeCreated")
            if tc is not None:
                time_created = tc.attrib.get("SystemTime", tc.text or "")
        computer = system.findtext("Computer", "") if system is not None else ""

        message_parts = []
        if event_data is not None:
            for d in event_data.findall("Data"):
                val = d.text or ""
                name = d.attrib.get("Name")
                if name:
                    message_parts.append(f"{name}={val.strip()}")
                else:
                    message_parts.append(val.strip())

        # Fallback: algunos eventos tienen <RenderingInfo><Message>
        if not message_parts:
            rend = root.find("RenderingInfo")
            if rend is not None:
                msg = rend.findtext("Message", "")
                if msg:
                    message_parts.append(msg.strip())

        message = " | ".join(message_parts)

        return {
            "Fecha": time_created,
            "Origen": provider,
            "Evento ID": str(event_id),
            "Nivel": level,
            "Equipo": computer,
            "Mensaje": message  # limitar tamaño de mensaje
        }

    except ET.ParseError:
        return None
    except Exception:
        return None

"""Lee un archivo .evtx y devuelve una lista de diccionarios con sus registros."""
def read_evtx_summary(file_path):
    if not Evtx:
        raise ImportError("python-evtx no está instalado. Ejecuta: pip install python-evtx")
    rows = []
    with Evtx(file_path) as log:
        for i, record in enumerate(log.records()):
            parsed = parse_event_xml(record.xml())
            if parsed:
                rows.append(parsed)
    return rows

# ----------------------------------------------------------------------
# Clase principal de la ventana
# ----------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Windows Event Log Analyzer")
        self.resize(1920, 1080)

        self.reader = EventLogReader()
        self.current_records = []

        self._setup_ui()

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)
        top_bar = QHBoxLayout()

        self.channel_combo = QComboBox()
        self.channel_combo.addItems(["Application", "System", "Security"])

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter by keyword...")

        self.load_btn = QPushButton("Load Events")
        self.load_btn.clicked.connect(self.load_events)

        self.load_file_btn = QPushButton("Load From File")
        self.load_file_btn.clicked.connect(self.load_from_file)

        self.export_btn = QPushButton("Export CSV")
        self.export_btn.clicked.connect(self.export_csv)

        top_bar.addWidget(self.channel_combo)
        top_bar.addWidget(self.filter_edit)
        top_bar.addWidget(self.load_btn)
        top_bar.addWidget(self.load_file_btn)
        top_bar.addWidget(self.export_btn)

        layout.addLayout(top_bar)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Source", "Event ID", "Time", "Message"])
        layout.addWidget(self.table)

    def load_events(self):
        channel = self.channel_combo.currentText()
        self.current_records = self.reader.read_channel(channel)
        self.update_table(self.current_records)

    def load_from_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select EVTX File",
            "C:\\Windows\\System32\\winevt\\Logs",
            "Event Log Files (*.evtx)"
        )
        if not file_path:
            return
        try:
            tmp_copy = safe_copy_evtx(file_path)
            self.records = read_evtx_summary(tmp_copy)
            self.last_path = file_path
            self.populate_table(self.records)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
        self.current_records = self.reader.read_channel(file_path)
        if not self.current_records:
            QMessageBox.warning(self, "Error", "No se pudieron leer eventos del archivo.")
        else:
            self.update_table(self.current_records)

    def populate_table(self, records):
        """Llena la tabla con los eventos parseados."""
        if not records:
            QMessageBox.information(self, "Sin resultados", "No se encontraron registros o no pudieron parsearse.")
            return

        headers = list(records[0].keys())
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(len(records))

        for row_idx, rec in enumerate(records):
            for col_idx, key in enumerate(headers):
                item = QTableWidgetItem(rec.get(key, ""))
                item.setFlags(item.flags() ^ Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row_idx, col_idx, item)

        self.table.resizeColumnsToContents()

    def update_table(self, records):
        self.table.setRowCount(len(records))
        for row, rec in enumerate(records):
            self.table.setItem(row, 0, QTableWidgetItem(rec.source))
            self.table.setItem(row, 1, QTableWidgetItem(str(rec.event_id)))
            self.table.setItem(row, 2, QTableWidgetItem(rec.time_generated))
            self.table.setItem(row, 3, QTableWidgetItem(rec.message))

    def export_csv(self):
        import csv
        path, _ = QFileDialog.getSaveFileName(self, "Save CSV", "", "CSV Files (*.csv)")
        if not path:
            return

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Source", "Event ID", "Time", "Message"])
            for rec in self.current_records:
                writer.writerow([rec.source, rec.event_id, rec.time_generated, rec.message])
