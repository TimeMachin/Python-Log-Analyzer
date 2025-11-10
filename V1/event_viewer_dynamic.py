# main.py (robust EVTX parser, drop-in replacement)
import sys
import os
import re
import tempfile
import shutil
import traceback
import ctypes

from PyQt6.QtCore import Qt, QObject, pyqtSignal, QThread
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QFileDialog, QMessageBox, QLabel, QProgressBar,
    QTextEdit, QSplitter, QHeaderView
)

# try import Evtx
try:
    from Evtx.Evtx import Evtx
except Exception:
    Evtx = None

# ---------------- elevation helpers ----------------
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

def restart_as_admin_no_console():
    script = os.path.abspath(sys.argv[0])
    python_exec = sys.executable
    if python_exec.lower().endswith("python.exe"):
        python_exec = python_exec[:-len("python.exe")] + "pythonw.exe"
    params = " ".join([f'"{arg}"' for arg in sys.argv[1:]])
    try:
        ctypes.windll.shell32.ShellExecuteW(None, "runas", python_exec, f'"{script}" {params}', None, 1)
        sys.exit(0)
    except Exception as e:
        QMessageBox.critical(None, "Elevation failed", f"Could not request admin rights: {e}")
        sys.exit(1)

# ---------------- utilities ----------------
XMLNS_RE = re.compile(r'\sxmlns="[^"]+"', re.IGNORECASE)

def strip_namespace_once(s):
    """Remove first xmlns declaration to simplify parsing if needed."""
    return XMLNS_RE.sub('', s, count=1) if s else s

def safe_copy_evtx(path: str) -> str:
    tmpdir = tempfile.gettempdir()
    base = os.path.basename(path)
    dest = os.path.join(tmpdir, f"evtx_copy_{base}")
    shutil.copy2(path, dest)
    return dest

def dump_debug_xml(xml_text):
    """Save a debug copy of the first raw XML to temp for inspection."""
    try:
        tmp = tempfile.gettempdir()
        path = os.path.join(tmp, "evtx_debug_first_record.xml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(xml_text)
        return path
    except Exception:
        return None

# ---------------- robust parser ----------------
def tag_local_name(tag):
    """Return local-name part of an Element tag (works with namespaces)."""
    if not tag:
        return ""
    if '}' in tag:
        return tag.split('}', 1)[1]
    return tag

def collect_text(e):
    """Safely collect text from an element."""
    if e is None:
        return ""
    text = e.text or ""
    return text.strip()

def parse_event_xml_to_dict_robust(xml_text, enable_debug_dump=False):
    """
    Parse XML by walking tree and matching local-names, tolerant to namespaces.
    Returns (fields_dict, raw_xml).
    """
    import xml.etree.ElementTree as ET
    if not xml_text:
        return None, None
    xml_to_parse = xml_text
    try:
        # Some EVTX XML hold a default xmlns; try parsing; if fails fallback to stripping
        try:
            root = ET.fromstring(xml_to_parse)
        except ET.ParseError:
            xml_to_parse = strip_namespace_once(xml_to_parse)
            root = ET.fromstring(xml_to_parse)

        result = {}

        # Find System node by searching children with local-name == 'System'
        system = None
        for child in root:
            if tag_local_name(child.tag) == "System":
                system = child
                break
        # If not found at top, search deeper
        if system is None:
            for elem in root.iter():
                if tag_local_name(elem.tag) == "System":
                    system = elem
                    break

        if system is not None:
            # Provider
            for ch in system:
                ln = tag_local_name(ch.tag)
                if ln == "Provider":
                    # Provider may have Name attribute
                    name = ch.attrib.get("Name") or collect_text(ch)
                    if name:
                        result["Provider"] = name
                elif ln == "EventID":
                    v = collect_text(ch)
                    if v:
                        result["EventID"] = v
                elif ln == "Level":
                    v = collect_text(ch)
                    if v:
                        result["Level"] = v
                elif ln == "TimeCreated":
                    # attribute SystemTime preferred
                    st = ch.attrib.get("SystemTime") or collect_text(ch)
                    if st:
                        result["TimeCreated"] = st
                elif ln == "Computer":
                    v = collect_text(ch)
                    if v:
                        result["Computer"] = v

        # EventData: find element with local-name 'EventData' then its 'Data' children
        eventdata = None
        for elem in root.iter():
            if tag_local_name(elem.tag) == "EventData":
                eventdata = elem
                break
        if eventdata is not None:
            idx = 0
            for d in eventdata:
                if tag_local_name(d.tag) != "Data":
                    continue
                idx += 1
                name = d.attrib.get("Name")
                if not name:
                    name = f"Data_{idx}"
                # ensure unique key
                base = name
                i = 1
                while name in result:
                    i += 1
                    name = f"{base}_{i}"
                result[name] = collect_text(d)

        # RenderingInfo/Message fallback (some logs put the text here)
        # We search for any element with local-name 'RenderingInfo' and inside find 'Message'
        if "Message" not in result:
            for elem in root.iter():
                if tag_local_name(elem.tag) == "RenderingInfo":
                    for sub in elem.iter():
                        if tag_local_name(sub.tag) == "Message":
                            msg = collect_text(sub)
                            if msg:
                                result["Message"] = msg
                                break
                    if "Message" in result:
                        break

        # As additional fallback: look for any child with local-name 'Message' anywhere
        if "Message" not in result:
            for elem in root.iter():
                if tag_local_name(elem.tag) == "Message":
                    msg = collect_text(elem)
                    if msg:
                        result["Message"] = msg
                        break

        # If nothing parsed at all, return parse error marker for inspection
        if not result:
            if enable_debug_dump:
                dump_debug_xml(xml_text)
            return None, xml_text

        return result, xml_text

    except Exception as ex:
        # Dump debug xml for analysis and return parse error
        if enable_debug_dump:
            dump_debug_xml(xml_text)
        return {"__parse_error": str(ex)}, xml_text

# ---------------- background worker ----------------
class EvtxReadWorker(QObject):
    finished = pyqtSignal(list, list)   # records, headers
    progress = pyqtSignal(int)
    error = pyqtSignal(str)

    def __init__(self, filepath: str, limit: int = 5000, enable_debug_dump=False):
        super().__init__()
        self.filepath = filepath
        self.limit = limit
        self.enable_debug_dump = enable_debug_dump

    def run(self):
        if Evtx is None:
            self.error.emit("python-evtx not installed. Install with: pip install python-evtx")
            return
        try:
            tmp = safe_copy_evtx(self.filepath)
            records = []
            headers_set = set()
            count = 0
            with Evtx(tmp) as log:
                for rec in log.records():
                    xml_text = rec.xml()
                    parsed, raw = parse_event_xml_to_dict_robust(xml_text, enable_debug_dump=self.enable_debug_dump)
                    if parsed:
                        entry = {"__raw_xml": raw}
                        entry.update(parsed)
                        records.append(entry)
                        headers_set.update(parsed.keys())
                    count += 1
                    if self.limit and count >= self.limit:
                        break
                    if count % 100 == 0:
                        self.progress.emit(count)
            headers = sorted(list(headers_set))
            self.finished.emit(records, headers)
        except Exception:
            tb = traceback.format_exc()
            self.error.emit(f"Error reading EVTX:\n{tb}")

# ---------------- header mapping (same as before) ----------------
CANONICAL_ORDER = ["Time", "Source", "EventID", "Level", "Computer", "Message"]
CANONICAL_MAP = {
    "TimeCreated": "Time",
    "Provider": "Source",
    "EventID": "EventID",
    "Level": "Level",
    "Computer": "Computer",
    "Message": "Message",
}

def build_final_headers(found_headers):
    mapped = {}
    remaining = []
    for h in found_headers:
        if h in CANONICAL_MAP:
            mapped[h] = CANONICAL_MAP[h]
        else:
            low = h.lower()
            if low in ("timecreated", "time", "timestamp"):
                mapped[h] = "Time"
            elif low in ("provider", "source"):
                mapped[h] = "Source"
            elif low in ("eventid", "event id"):
                mapped[h] = "EventID"
            elif low in ("level", "severity"):
                mapped[h] = "Level"
            elif low in ("computer", "host"):
                mapped[h] = "Computer"
            else:
                remaining.append(h)

    front = []
    used = set()
    for canon in CANONICAL_ORDER:
        chosen = None
        for orig, mapped_name in mapped.items():
            if mapped_name == canon and orig not in used:
                chosen = orig
                break
        if chosen:
            front.append(chosen)
            used.add(chosen)
    tail = [h for h in found_headers if h not in used]
    final = front + tail
    display_names = []
    for orig in final:
        display = CANONICAL_MAP.get(orig, None)
        if not display:
            low = orig.lower()
            if low in ("timecreated", "time"):
                display = "Time"
            elif low in ("provider", "source"):
                display = "Source"
            elif low in ("eventid", "event id"):
                display = "EventID"
            elif low in ("level", "severity"):
                display = "Level"
            elif low in ("computer", "host"):
                display = "Computer"
            else:
                display = orig
        display_names.append(display)
    return final, display_names

# ---------------- GUI (casi igual que a la otra, pero con menor diseño) ----------------
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EVTX Dynamic Viewer (robust)")
        self.resize(1200, 720)

        # Controls
        self.load_btn = QPushButton("Load EVTX file...")
        self.load_sys_btn = QPushButton("Open System.evtx")
        self.export_btn = QPushButton("Export CSV")
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Global filter (type to filter rows)")
        self.progress = QProgressBar()
        self.progress.setMaximum(100)
        self.status_label = QLabel("Ready")

        top_layout = QHBoxLayout()
        top_layout.addWidget(self.load_btn)
        top_layout.addWidget(self.load_sys_btn)
        top_layout.addWidget(self.export_btn)
        top_layout.addWidget(self.filter_edit)
        top_layout.addWidget(self.progress)
        top_layout.addWidget(self.status_label)

        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAlternatingRowColors(True)

        self.xml_view = QTextEdit()
        self.xml_view.setReadOnly(True)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.table)
        splitter.addWidget(self.xml_view)
        splitter.setSizes([800, 400])

        main_layout = QVBoxLayout(self)
        main_layout.addLayout(top_layout)
        main_layout.addWidget(splitter)

        # Signals
        self.load_btn.clicked.connect(self.on_load)
        self.load_sys_btn.clicked.connect(self.on_load_system)
        self.export_btn.clicked.connect(self.on_export)
        self.filter_edit.textChanged.connect(self.on_filter_text)
        self.table.cellClicked.connect(self.on_row_clicked)

        # state
        self.records = []
        self.headers = []
        self.display_headers = []
        self.thread = None
        self.worker = None

    def on_load(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select EVTX file", "C:\\Windows\\System32\\winevt\\Logs", "EVTX files (*.evtx)")
        if not path:
            return
        # enable debug dump for this load (set to True if you want XML saved)
        self.start_worker(path, enable_debug_dump=True)

    def on_load_system(self):
        sys_path = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "System32", "winevt", "Logs", "System.evtx")
        if not os.path.exists(sys_path):
            QMessageBox.warning(self, "Not found", f"{sys_path} not found.")
            return
        self.start_worker(sys_path, enable_debug_dump=True)

    def start_worker(self, filepath, enable_debug_dump=False):
        self.records = []
        self.headers = []
        self.display_headers = []
        self.table.clear()
        self.xml_view.clear()
        self.progress.setValue(0)
        self.status_label.setText("Reading...")

        self.thread = QThread()
        self.worker = EvtxReadWorker(filepath, limit=5000, enable_debug_dump=enable_debug_dump)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.on_read_finished)
        self.worker.progress.connect(self.on_progress)
        self.worker.error.connect(self.on_error)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def on_progress(self, n):
        self.progress.setValue(min(99, (n % 200) // 2 + 1))
        self.status_label.setText(f"Read {n} records...")

    def on_error(self, msg):
        QMessageBox.critical(self, "Error", msg)
        self.status_label.setText("Error")
        self.progress.setValue(0)

    def on_read_finished(self, records, headers):
        self.records = records
        self.headers = headers
        final_headers, display_names = build_final_headers(self.headers)
        self.display_headers = display_names
        self.populate_table_with_headers(final_headers, display_names)
        self.status_label.setText(f"Loaded {len(records)} records")
        self.progress.setValue(100)
        # If a debug dump was created, inform the user where it is
        dbg_path = os.path.join(tempfile.gettempdir(), "evtx_debug_first_record.xml")
        if os.path.exists(dbg_path):
            QMessageBox.information(self, "Debug XML dumped", f"A debug XML was saved at:\n{dbg_path}\nIf parsing failed, please attach this file.")

    def populate_table_with_headers(self, header_keys, display_names):
        self.table.clear()
        self.table.setColumnCount(len(header_keys))
        self.table.setRowCount(len(self.records))
        self.table.setHorizontalHeaderLabels(display_names)
        self.header_keys = header_keys
        for r_idx, rec in enumerate(self.records):
            for c_idx, key in enumerate(header_keys):
                v = rec.get(key, "")
                if v is None:
                    v = ""
                elif not isinstance(v, str):
                    v = str(v)
                item = QTableWidgetItem(v)
                item.setToolTip(v)
                self.table.setItem(r_idx, c_idx, item)
        self.table.resizeColumnsToContents()

    def on_row_clicked(self, row, col):
        if 0 <= row < len(self.records):
            raw = self.records[row].get("__raw_xml", "")
            if raw:
                self.xml_view.setPlainText(raw)
            else:
                self.xml_view.setPlainText("<no raw xml available>")

    def on_filter_text(self, text):
        t = text.lower().strip()
        for r in range(self.table.rowCount()):
            if t == "":
                visible = True
            else:
                visible = any(
                    (self.table.item(r, c) and t in self.table.item(r, c).text().lower())
                    for c in range(self.table.columnCount())
                )
            self.table.setRowHidden(r, not visible)

    def on_export(self):
        if not self.records or not hasattr(self, "header_keys"):
            QMessageBox.information(self, "No data", "No records to export.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save CSV", "", "CSV Files (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(",".join(self.display_headers) + "\n")
                for rec in self.records:
                    row_vals = []
                    for key in self.header_keys:
                        v = rec.get(key, "")
                        if not isinstance(v, str):
                            v = str(v)
                        row_vals.append(v.replace("\n", " ").replace(",", ";"))
                    f.write(",".join(row_vals) + "\n")
            QMessageBox.information(self, "Exported", f"Saved CSV to {path}")
        except Exception as e:
            QMessageBox.critical(self, "Export error", str(e))

# ---------------- entry point ----------------
def main():
    if not is_admin():
        restart_as_admin_no_console()

    if Evtx is None:
        app = QApplication(sys.argv)
        QMessageBox.critical(None, "Missing dependency", "python-evtx not found. Install with:\n\npip install python-evtx")
        return

    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
