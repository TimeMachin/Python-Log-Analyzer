# main_window.py
import os
import re
import tempfile
import shutil
from xml.etree import ElementTree as ET

from PyQt6.QtCore import Qt, QObject, pyqtSignal, QThread, QRegularExpression
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QPushButton, QLineEdit, QComboBox, QLabel, QTableWidget,
    QTableWidgetItem, QFileDialog, QMessageBox, QTextEdit, QDialog,
    QDialogButtonBox, QHeaderView
)
from PyQt6.QtGui import QFont, QTextCursor, QSyntaxHighlighter, QTextCharFormat, QColor

# Import reader module if present
try:
    import event_log_reader as elr_mod
except Exception:
    elr_mod = None

# python-evtx fallback import (only for files)
try:
    from Evtx.Evtx import Evtx
except Exception:
    Evtx = None

# ---------------------------
# XML syntax highlighter
# ---------------------------
class XmlHighlighter(QSyntaxHighlighter):
    def __init__(self, doc):
        super().__init__(doc)
        # formats
        self.tagFormat = QTextCharFormat()
        self.tagFormat.setForeground(QColor("#6DD3FB"))  # tags
        self.attrNameFormat = QTextCharFormat()
        self.attrNameFormat.setForeground(QColor("#B9F18C"))  # attr names
        self.attrValueFormat = QTextCharFormat()
        self.attrValueFormat.setForeground(QColor("#FFD58A"))  # attr values
        self.commentFormat = QTextCharFormat()
        self.commentFormat.setForeground(QColor("#8a8f95"))  # comments
        self.textFormat = QTextCharFormat()
        self.textFormat.setForeground(QColor("#dfeffb"))

        # regex patterns
        self.re_comment = QRegularExpression(r'<!--[\s\S]*?-->')
        self.re_tag = QRegularExpression(r'(<\/?[A-Za-z0-9:_-]+)')
        self.re_attr = QRegularExpression(r'([A-Za-z_:-][A-Za-z0-9_:\-\.]*)\s*=')
        self.re_value = QRegularExpression(r'\"[^"]*\"')

    def highlightBlock(self, text):
        # comments
        it = self.re_comment.globalMatch(text)
        while it.hasNext():
            m = it.next()
            self.setFormat(m.capturedStart(), m.capturedLength(), self.commentFormat)

        it = self.re_tag.globalMatch(text)
        while it.hasNext():
            m = it.next()
            self.setFormat(m.capturedStart(), m.capturedLength(), self.tagFormat)
        it = self.re_attr.globalMatch(text)
        while it.hasNext():
            m = it.next()
            start = m.capturedStart(1)
            length = m.capturedLength(1)
            self.setFormat(start, length, self.attrNameFormat)
        it = self.re_value.globalMatch(text)
        while it.hasNext():
            m = it.next()
            self.setFormat(m.capturedStart(), m.capturedLength(), self.attrValueFormat)

# ---------------------------
# Helper: copy file to temp
# ---------------------------
def safe_copy_to_temp(path):
    dest_dir = tempfile.gettempdir()
    base = os.path.basename(path)
    dest = os.path.join(dest_dir, f"evtx_copy_{base}")
    shutil.copy2(path, dest)
    return dest

# ---------------------------
# Worker for reading (background)
# ---------------------------
class ReaderWorker(QObject):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, path_or_channel, max_events=5000):
        super().__init__()
        self.path_or_channel = path_or_channel
        self.max_events = max_events

    def run(self):
        try:
            p = self.path_or_channel
            # If p ends with .evtx -> treat as file
            if isinstance(p, str) and p.lower().endswith(".evtx"):
                # prefer event_log_reader.read_evtx_summary if present
                if elr_mod and hasattr(elr_mod, "read_evtx_summary"):
                    rows = elr_mod.read_evtx_summary(p, self.max_events)
                    self.finished.emit(rows)
                    return
                # fallback to python-evtx
                if Evtx:
                    rows = []
                    tmp = safe_copy_to_temp(p)
                    with Evtx(tmp) as log:
                        for i, r in enumerate(log.records()):
                            xml = r.xml()
                            rows.append({"__raw_xml": xml})
                            if i+1 >= self.max_events:
                                break
                    self.finished.emit(rows)
                    return
                self.error.emit("No available file reader. Install python-evtx or provide read_evtx_summary.")
                return
            else:
                # treat as channel name (Application/System/Security)
                # Build physical path to channel file and copy it to temp, then parse file
                system_root = os.environ.get("SystemRoot", r"C:\Windows")
                candidate = os.path.join(system_root, "System32", "winevt", "Logs", f"{p}.evtx")
                if not os.path.exists(candidate):
                    self.error.emit(f"Channel file not found: {candidate}")
                    return
                copied = safe_copy_to_temp(candidate)
                # Now parse copied file like a normal evtx
                if elr_mod and hasattr(elr_mod, "read_evtx_summary"):
                    rows = elr_mod.read_evtx_summary(copied, self.max_events)
                    self.finished.emit(rows)
                    return
                if Evtx:
                    rows = []
                    with Evtx(copied) as log:
                        for i, r in enumerate(log.records()):
                            xml = r.xml()
                            rows.append({"__raw_xml": xml})
                            if i+1 >= self.max_events:
                                break
                    self.finished.emit(rows)
                    return
                self.error.emit("No available reader for channel files. Install python-evtx or provide read_evtx_summary.")
                return
        except Exception as e:
            import traceback
            self.error.emit(traceback.format_exc())

# ---------------------------
# Modal XML dialog
# ---------------------------
class XmlDialog(QDialog):
    def __init__(self, xml_text, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Event XML (detail)")
        self.resize(900, 600)
        layout = QVBoxLayout(self)
        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.text.setFontFamily("Consolas")
        self.text.setFontPointSize(10)
        layout.addWidget(self.text)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        copy_btn = QPushButton("Copy XML")
        btns.addButton(copy_btn, QDialogButtonBox.ButtonRole.ActionRole)
        layout.addWidget(btns)
        btns.rejected.connect(self.reject)
        copy_btn.clicked.connect(self.copy_xml)

        pretty = xml_text or ""
        self.text.setPlainText(pretty)
        XmlHighlighter(self.text.document())

    def copy_xml(self):
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.text.toPlainText())

# ---------------------------
# XML parser to dict
# ---------------------------
def parse_event_xml_to_dict(xml_text):
    """
    Parse an Event XML string and return a dict with canonical keys:
    Source (Provider), EventID, TimeCreated, Level, Computer, Message, plus any EventData fields.
    """
    if not xml_text:
        return {}
    try:
        # Remove default xmlns to simplify local-name matching
        xml2 = re.sub(r'\sxmlns="[^"]+"', '', xml_text, count=1)
        root = ET.fromstring(xml2)
    except Exception:
        # fallback: try direct parse (maybe already fine)
        try:
            root = ET.fromstring(xml_text)
        except Exception:
            return {}

    result = {}
    # find System node
    system = None
    for child in root:
        if child.tag.lower().endswith("system"):
            system = child
            break
    if system is None:
        # search deeper
        for elem in root.iter():
            if elem.tag.lower().endswith("system"):
                system = elem
                break

    if system is not None:
        for elem in system:
            tag = elem.tag
            lname = tag.split('}')[-1] if '}' in tag else tag
            if lname.lower() == "provider":
                name = elem.attrib.get("Name") or elem.text or ""
                if name:
                    result["Source"] = name
            elif lname.lower() == "eventid":
                # sometimes EventID is like: <EventID Qualifiers="0">1022</EventID>
                text = elem.text or ""
                if text:
                    result["EventID"] = text.strip()
            elif lname.lower() == "timecreated":
                st = elem.attrib.get("SystemTime") or elem.text or ""
                if st:
                    result["TimeCreated"] = st.strip()
            elif lname.lower() == "computer":
                text = elem.text or ""
                if text:
                    result["Computer"] = text.strip()
            elif lname.lower() == "level":
                text = elem.text or ""
                if text:
                    result["Level"] = text.strip()

    # try RenderingInfo/Message or EventData/Data
    # Message
    msg = ""
    for elem in root.iter():
        lname = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
        if lname.lower() == "renderinginfo":
            for sub in elem.iter():
                if sub.tag.split('}')[-1].lower() == "message":
                    msg = (sub.text or "").strip()
                    break
            if msg:
                break
    # fallback: look for Message element anywhere
    if not msg:
        for elem in root.iter():
            if elem.tag.split('}')[-1].lower() == "message":
                msg = (elem.text or "").strip()
                break
    # fallback EventData
    eventdata = {}
    for elem in root.iter():
        if elem.tag.split('}')[-1].lower() == "eventdata":
            for d in elem:
                if d.tag.split('}')[-1].lower() == "data":
                    name = d.attrib.get("Name") or ""
                    text = d.text or ""
                    key = name if name else f"Data_{len(eventdata)+1}"
                    eventdata[key] = text
            break

    if msg:
        result["Message"] = msg
    # merge eventdata
    for k, v in eventdata.items():
        # avoid overwriting main keys
        if k not in result:
            result[k] = v

    # ensure default keys exist
    if "Source" not in result:
        result["Source"] = ""
    if "EventID" not in result:
        result["EventID"] = ""
    if "TimeCreated" not in result:
        result["TimeCreated"] = ""
    if "Level" not in result:
        result["Level"] = ""
    if "Message" not in result:
        result["Message"] = ""

    return result

# ---------------------------
# MainWindow
# ---------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Windows Event Log Analyzer")
        self.resize(1200, 800)

        # Top bar
        top = QWidget()
        top_l = QHBoxLayout(top)
        top_l.setContentsMargins(0,0,0,0)
        top_l.setSpacing(6)
        top.setLayout(top_l)

        top.setFixedHeight(42)


        self.channel_combo = QComboBox()
        self.channel_combo.addItems(["Application", "System", "Security"])
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter by keyword...")
        self.load_btn = QPushButton("Load Events")
        self.load_file_btn = QPushButton("Load From File")
        self.export_btn = QPushButton("Export CSV")
        self.status_label = QLabel("Ready")

        top_l.addWidget(self.channel_combo)
        top_l.addWidget(self.filter_edit, 1)
        top_l.addWidget(self.load_btn)
        top_l.addWidget(self.load_file_btn)
        top_l.addWidget(self.export_btn)
        top_l.addWidget(self.status_label)

        # Table (left)
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Source", "Event ID", "Time", "Level", "Message"])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(self.table.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)

        # XML panel (right)
        self.xml_view = QTextEdit()
        self.xml_view.setReadOnly(True)
        self.xml_view.setFontFamily("Consolas")
        self.xml_view.setFontPointSize(10)
        XmlHighlighter(self.xml_view.document())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        left_w = QWidget()
        left_l = QVBoxLayout()
        left_l.setContentsMargins(0,0,0,0)
        left_l.addWidget(self.table)
        left_w.setLayout(left_l)
        splitter.addWidget(left_w)
        splitter.addWidget(self.xml_view)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        # Root layout
        root = QWidget()
        root_l = QVBoxLayout()
        root_l.setContentsMargins(6,6,6,6)
        root_l.setSpacing(8)
        root_l.addWidget(top)
        root_l.addWidget(splitter)
        root.setLayout(root_l)
        self.setCentralWidget(root)

        # signals
        self.load_btn.clicked.connect(self.load_channel)
        self.load_file_btn.clicked.connect(self.load_from_file)
        self.export_btn.clicked.connect(self.export_csv)
        self.filter_edit.textChanged.connect(self.on_filter_text)
        self.table.cellClicked.connect(self.on_row_clicked)
        self.table.cellDoubleClicked.connect(self.on_row_double_clicked)

        # state
        self.records = []
        # canonical display order
        self.canonical_cols = ["Source", "EventID", "TimeCreated", "Level", "Message", "Computer"]
        self.header_keys = ["Source", "EventID", "TimeCreated", "Level", "Message"]

        # threading
        self.thread = None
        self.worker = None

    # ---------------------------
    # Status / helpers
    # ---------------------------
    def _set_status(self, text):
        self.status_label.setText(text)

    def _clear_table(self):
        self.table.setRowCount(0)
        self.records = []

    # ---------------------------
    # Loading
    # ---------------------------
    def load_channel(self):
        channel = self.channel_combo.currentText()
        self._start_read(channel)

    def load_from_file(self):
        # default folder is the Windows event logs folder
        default_dir = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "winevt", "Logs")
        path, _ = QFileDialog.getOpenFileName(self, "Select EVTX", default_dir, "Event Log Files (*.evtx)")
        if not path:
            return
        self._start_read(path)

    def _start_read(self, path_or_channel):
        # disable UI
        self.load_btn.setEnabled(False)
        self.load_file_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
        self._set_status("Reading...")
        # start worker
        self.thread = QThread()
        self.worker = ReaderWorker(path_or_channel)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self._on_read_finished)
        self.worker.error.connect(self._on_read_error)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def _on_read_error(self, msg):
        self._set_status("Error")
        QMessageBox.critical(self, "Read error", str(msg))
        self.load_btn.setEnabled(True)
        self.load_file_btn.setEnabled(True)
        self.export_btn.setEnabled(True)

    def _on_read_finished(self, records):
        # Expect records = list of dicts each containing '__raw_xml'
        self.records = records or []
        # Parse XML for each record to extract canonical fields
        parsed_records = []
        for rec in self.records:
            raw = rec.get("__raw_xml", "")
            parsed = parse_event_xml_to_dict(raw)
            # ensure __raw_xml preserved
            parsed["__raw_xml"] = raw
            parsed_records.append(parsed)
        self.records = parsed_records

        # Build header order: prefer canonical cols existing in union
        keys_union = set()
        for r in self.records:
            keys_union.update(k for k in r.keys() if k != "__raw_xml")

        final_keys = []
        for c in self.canonical_cols:
            for k in keys_union:
                if k.lower() == c.lower() and k not in final_keys:
                    final_keys.append(k)
        others = [k for k in sorted(keys_union) if k not in final_keys]
        final_keys.extend(others)
        if not final_keys:
            final_keys = ["Source", "EventID", "TimeCreated", "Level", "Message"]
        display_keys = final_keys[:12]
        self.header_keys = display_keys

        # Populate table
        self.table.setColumnCount(len(display_keys))
        header_labels = []
        for k in display_keys:
            lab = k
            lab = lab.replace("EventID", "Event ID").replace("TimeCreated", "Time")
            header_labels.append(lab)
        self.table.setHorizontalHeaderLabels(header_labels)
        self.table.setRowCount(len(self.records))
        for r_idx, rec in enumerate(self.records):
            for c_idx, key in enumerate(display_keys):
                v = rec.get(key, "")
                if v is None:
                    v = ""
                if not isinstance(v, str):
                    v = str(v)
                item = QTableWidgetItem(v)
                item.setToolTip(v)
                self.table.setItem(r_idx, c_idx, item)

        self.table.resizeColumnsToContents()
        self._set_status(f"Loaded {len(self.records)} records")
        self.load_btn.setEnabled(True)
        self.load_file_btn.setEnabled(True)
        self.export_btn.setEnabled(True)
        self.xml_view.clear()

    # ---------------------------
    # Row interactions
    # ---------------------------
    def on_row_clicked(self, row, col):
        if 0 <= row < len(self.records):
            raw = self.records[row].get("__raw_xml", "")
            pretty = self._pretty_xml(raw)
            self.xml_view.setPlainText(pretty)

    def on_row_double_clicked(self, row, col):
        if 0 <= row < len(self.records):
            raw = self.records[row].get("__raw_xml", "")
            pretty = self._pretty_xml(raw)
            dlg = XmlDialog(pretty, self)
            dlg.exec()

    # ---------------------------
    # Utilities
    # ---------------------------
    def _pretty_xml(self, xml_text):
        if not xml_text:
            return ""
        try:
            from xml.dom import minidom
            # Remove default xmlns for prettier display (without modifying original)
            txt = re.sub(r'\sxmlns="[^"]+"', '', xml_text, count=1)
            dom = minidom.parseString(txt)
            pretty = dom.toprettyxml(indent="  ")
            pretty = "\n".join([line for line in pretty.splitlines() if line.strip() != ""])
            return pretty
        except Exception:
            return xml_text

    def on_filter_text(self, txt):
        t = txt.lower().strip()
        for r in range(self.table.rowCount()):
            visible = False
            if t == "":
                visible = True
            else:
                for c in range(self.table.columnCount()):
                    item = self.table.item(r, c)
                    if item and t in item.text().lower():
                        visible = True
                        break
            self.table.setRowHidden(r, not visible)

    def export_csv(self):
        if not self.records or not self.header_keys:
            QMessageBox.information(self, "No data", "No records to export.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save CSV", "", "CSV Files (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(",".join(self.header_keys) + "\n")
                for rec in self.records:
                    row = []
                    for k in self.header_keys:
                        v = rec.get(k, "")
                        if v is None:
                            v = ""
                        if not isinstance(v, str):
                            v = str(v)
                        row.append(v.replace("\n"," ").replace(",",";"))
                    f.write(",".join(row) + "\n")
            QMessageBox.information(self, "Exported", f"Saved CSV to: {path}")
        except Exception as e:
            QMessageBox.critical(self, "Export error", str(e))
