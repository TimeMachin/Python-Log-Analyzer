# main_window.py
import os
import re
import tempfile
import shutil
from xml.etree import ElementTree as ET

from PyQt6.QtCore import Qt, QObject, pyqtSignal, QThread, QRegularExpression, QPoint
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QPushButton, QLineEdit, QComboBox, QLabel, QTableWidget,
    QTableWidgetItem, QFileDialog, QMessageBox, QTextEdit, QDialog,
    QDialogButtonBox, QHeaderView, QTreeWidget, QTreeWidgetItem,
    QSizePolicy, QStyle, QMenu, QInputDialog
)
from PyQt6.QtGui import QFont, QTextCursor, QSyntaxHighlighter, QTextCharFormat, QColor, QBrush, QAction

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
# Helper: copy file to temp
# ---------------------------
def safe_copy_to_temp(path):
    dest_dir = tempfile.gettempdir()
    base = os.path.basename(path)
    dest = os.path.join(dest_dir, f"evtx_copy_{base}")
    shutil.copy2(path, dest)
    return dest

# ---------------------------
# ReaderWorker
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
            if isinstance(p, str) and p.lower().endswith(".evtx"):
                if elr_mod and hasattr(elr_mod, "read_evtx_summary"):
                    rows = elr_mod.read_evtx_summary(p, self.max_events)
                    self.finished.emit(rows)
                    return
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
                # treat as channel name -> copy real file from System32\winevt\Logs
                system_root = os.environ.get("SystemRoot", r"C:\Windows")
                candidate = os.path.join(system_root, "System32", "winevt", "Logs", f"{p}.evtx")
                if not os.path.exists(candidate):
                    self.error.emit(f"Channel file not found: {candidate}")
                    return
                copied = safe_copy_to_temp(candidate)
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
# XML tree functions (previously implemented)
# ---------------------------
def add_xml_element_to_tree(tree_parent, element, level=0, expand_level=1):
    tag = element.tag.split("}")[-1] if "}" in element.tag else element.tag
    item = QTreeWidgetItem([f"<{tag}>"])

    # Attributes shown as "Attribute: name = value" (option 2A)
    for k, v in element.attrib.items():
        attr_item = QTreeWidgetItem([f'Attribute: {k} = "{v}"'])
        item.addChild(attr_item)

    # Text node
    text = (element.text or "").strip()
    if text:
        text_item = QTreeWidgetItem([f'Text: "{text}"'])
        item.addChild(text_item)

    # Recurse children
    for child in element:
        child_item = add_xml_element_to_tree(child, child, level + 1, expand_level)
        item.addChild(child_item)

    if level <= expand_level:
        item.setExpanded(True)
    return item

def populate_tree_from_xml(tree_widget, xml_text, expand_level=1):
    tree_widget.clear()
    if not xml_text:
        return
    try:
        txt = re.sub(r'\sxmlns="[^"]+"', '', xml_text, count=1)
        root = ET.fromstring(txt)
    except Exception:
        try:
            root = ET.fromstring(xml_text)
        except Exception:
            tree_widget.addTopLevelItem(QTreeWidgetItem(["<unparsable XML>"]))
            return

    top = add_xml_element_to_tree(None, root, 0, expand_level)
    tree_widget.addTopLevelItem(top)
    tree_widget.expandItem(top)
    for i in range(top.childCount()):
        top.child(i).setExpanded(True)
    tree_widget.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)

# helper to highlight matches in tree (case-insensitive or regex)
def highlight_tree_matches(tree_widget, term, use_regex=False):
    term_raw = term
    if not term:
        # clear backgrounds
        def clear(item):
            item.setBackground(0, QBrush())
            for i in range(item.childCount()):
                clear(item.child(i))
        for i in range(tree_widget.topLevelItemCount()):
            clear(tree_widget.topLevelItem(i))
        return

    try:
        pattern = re.compile(term, re.IGNORECASE) if use_regex else None
    except re.error:
        pattern = None

    def check_and_mark(item):
        text = item.text(0) or ""
        matched = False
        if use_regex and pattern:
            try:
                if pattern.search(text):
                    matched = True
            except re.error:
                matched = False
        else:
            if term.lower() in text.lower():
                matched = True
        # set background if matched
        if matched:
            item.setBackground(0, QBrush(QColor("#FFD44D")))  # soft yellow
            # ensure parents expanded to show it
            parent = item.parent()
            while parent is not None:
                parent.setExpanded(True)
                parent = parent.parent()
        else:
            item.setBackground(0, QBrush())
        for i in range(item.childCount()):
            check_and_mark(item.child(i))

    for i in range(tree_widget.topLevelItemCount()):
        check_and_mark(tree_widget.topLevelItem(i))

# ---------------------------
# Modal xml dialog
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
        try:
            from xml.dom import minidom
            txt = re.sub(r'\sxmlns="[^"]+"', '', pretty, count=1)
            dom = minidom.parseString(txt)
            pretty = dom.toprettyxml(indent="  ")
            pretty = "\n".join([line for line in pretty.splitlines() if line.strip() != ""])
        except Exception:
            pass
        self.text.setPlainText(pretty)

    def copy_xml(self):
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.text.toPlainText())

# ---------------------------
# parse XML to canonical dict
# ---------------------------
def parse_event_xml_to_dict(xml_text):
    if not xml_text:
        return {}
    try:
        xml2 = re.sub(r'\sxmlns="[^"]+"', '', xml_text, count=1)
        root = ET.fromstring(xml2)
    except Exception:
        try:
            root = ET.fromstring(xml_text)
        except Exception:
            return {}

    result = {}
    system = None
    for child in root:
        if child.tag.lower().endswith("system"):
            system = child
            break
    if system is None:
        for elem in root.iter():
            if elem.tag.lower().endswith("system"):
                system = elem
                break

    if system is not None:
        for elem in system:
            lname = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            if lname.lower() == "provider":
                name = elem.attrib.get("Name") or elem.text or ""
                if name:
                    result["Source"] = name
            elif lname.lower() == "eventid":
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

    # Message detection
    msg = ""
    for elem in root.iter():
        if elem.tag.split('}')[-1].lower() == "renderinginfo":
            for sub in elem.iter():
                if sub.tag.split('}')[-1].lower() == "message":
                    msg = (sub.text or "").strip()
                    break
            if msg:
                break
    if not msg:
        for elem in root.iter():
            if elem.tag.split('}')[-1].lower() == "message":
                msg = (elem.text or "").strip()
                break

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
    for k, v in eventdata.items():
        if k not in result:
            result[k] = v

    for k in ["Source", "EventID", "TimeCreated", "Level", "Message", "Computer"]:
        if k not in result:
            result[k] = ""
    return result

# ---------------------------
# Filtering engine helpers
# ---------------------------
class ColumnFilterDialog(QDialog):
    def __init__(self, parent=None, column_name="Column"):
        super().__init__(parent)
        self.setWindowTitle(f"Filter: {column_name}")
        self.resize(360, 120)
        layout = QVBoxLayout(self)
        # combo for type
        self.type_combo = QComboBox()
        self.type_combo.addItems(["Contains", "Equals", "Starts with", "Ends with", "Regex"])
        self.input = QLineEdit()
        self.input.setPlaceholderText("Type filter value (or regex)")
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(self.type_combo)
        layout.addWidget(self.input)
        layout.addWidget(btns)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)

    def result(self):
        return self.type_combo.currentText(), self.input.text()

# ---------------------------
# MainWindow
# ---------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Log Analyzer")
        self.resize(1200, 800)

        # Top bar
        top = QWidget()
        top_l = QHBoxLayout()
        top_l.setContentsMargins(0,0,0,0)
        top_l.setSpacing(6)
        top.setLayout(top_l)
        top.setFixedHeight(42)
        top.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        # Controls
        self.channel_combo = QComboBox()
        self.channel_combo.addItems(["Application", "System", "Security"])
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Global search (use prefix re: for regex)")
        self.search_scope = QComboBox()
        self.search_scope.addItems(["All", "Table only", "XML only"])
        self.filter_clear_btn = QPushButton("Clear All Filters")
        self.load_btn = QPushButton("Load Events")
        self.load_file_btn = QPushButton("Load From File")
        self.export_btn = QPushButton("Export CSV")
        self.status_label = QLabel("Ready")

        top_l.addWidget(self.channel_combo)
        top_l.addWidget(self.search_edit, 1)
        top_l.addWidget(self.search_scope)
        top_l.addWidget(self.filter_clear_btn)
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

        # enable context menu on header for column filters (Option 1)
        header = self.table.horizontalHeader()
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self.on_header_context_menu)

        # XML tree (right)
        self.xml_tree = QTreeWidget()
        self.xml_tree.setHeaderHidden(True)
        self.xml_tree.setColumnCount(1)
        self.xml_tree.setUniformRowHeights(True)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        left_w = QWidget()
        left_l = QVBoxLayout()
        left_l.setContentsMargins(0,0,0,0)
        left_l.addWidget(self.table)
        left_w.setLayout(left_l)
        splitter.addWidget(left_w)
        splitter.addWidget(self.xml_tree)
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
        self.search_edit.textChanged.connect(self.on_search_changed)
        self.filter_clear_btn.clicked.connect(self.clear_all_filters)
        self.table.cellClicked.connect(self.on_row_clicked)
        self.table.cellDoubleClicked.connect(self.on_row_double_clicked)

        # state
        self.records = []
        self.canonical_cols = ["Source", "EventID", "TimeCreated", "Level", "Message", "Computer"]
        self.header_keys = ["Source", "EventID", "TimeCreated", "Level", "Message"]

        # filters: {col_index: (type_str, value)}
        self.active_filters = {}

        # threading
        self.thread = None
        self.worker = None

        # suspicious event highlighting map (EventID -> color)
        self.suspicious_map = {
            "4624": QColor("#25b525"),  # successful logon (green)
            "4625": QColor("#6f6a2c"),  # failed logon (yellow)
            "4688": QColor("#4d6999"),  # new process (blue)
            "7045": QColor("#c30b0b"),  # service installed (red)
            "1102": QColor("#3b1a1a"),  # event log clear (dark red)
        }

    # ---------------------------
    # Header context menu
    # ---------------------------
    def on_header_context_menu(self, pos):
        header = self.table.horizontalHeader()
        logical_index = header.logicalIndexAt(pos)
        if logical_index < 0:
            return
        column_name = header.model().headerData(logical_index, Qt.Orientation.Horizontal)
        menu = QMenu(self)
        act_filter = QAction(f"Filter '{column_name}'...", self)
        act_clear = QAction(f"Clear filter '{column_name}'", self)
        menu.addAction(act_filter)
        menu.addAction(act_clear)
        action = menu.exec(header.mapToGlobal(pos))
        if action == act_filter:
            dlg = ColumnFilterDialog(self, column_name=str(column_name))
            if dlg.exec() == QDialog.DialogCode.Accepted:
                ftype, fval = dlg.result()
                if fval.strip() == "":
                    # empty -> treat as clear
                    if logical_index in self.active_filters:
                        del self.active_filters[logical_index]
                else:
                    self.active_filters[logical_index] = (ftype, fval)
                self.apply_filters_and_search()
        elif action == act_clear:
            if logical_index in self.active_filters:
                del self.active_filters[logical_index]
                self.apply_filters_and_search()

    # ---------------------------
    # Search & Filters integration
    # ---------------------------
    def on_search_changed(self, txt):
        # apply search (debounce not necessary for now)
        self.apply_filters_and_search()

    def clear_all_filters(self):
        self.active_filters = {}
        self.search_edit.clear()
        self.apply_filters_and_search()

    def apply_filters_and_search(self):
        """
        Central function: applies column filters (AND) and then global search (scope)
        """
        # precompute filter function
        def row_matches_filters(row_idx):
            # check active column filters
            for col_idx, (ftype, fval) in self.active_filters.items():
                try:
                    item = self.table.item(row_idx, col_idx)
                    cell_text = item.text() if item else ""
                except Exception:
                    cell_text = ""
                if not self._match_filter(cell_text, ftype, fval):
                    return False
            return True

        search_text = self.search_edit.text().strip()
        use_regex = False
        regex_text = ""
        if search_text.startswith("re:"):
            use_regex = True
            regex_text = search_text[3:]
        scope = self.search_scope.currentText()

        for r in range(self.table.rowCount()):
            visible = True
            # filters
            if not row_matches_filters(r):
                visible = False
            # global search
            if visible and search_text != "":
                table_ok = False
                xml_ok = False
                if scope in ("All", "Table only"):
                    # search across visible table columns
                    for c in range(self.table.columnCount()):
                        item = self.table.item(r, c)
                        if item:
                            txt = item.text()
                            if use_regex:
                                try:
                                    if re.search(regex_text, txt, re.IGNORECASE):
                                        table_ok = True
                                        break
                                except re.error:
                                    pass
                            else:
                                if search_text.lower() in txt.lower():
                                    table_ok = True
                                    break
                if scope in ("All", "XML only"):
                    raw = self.records[r].get("__raw_xml", "")
                    if use_regex:
                        try:
                            if re.search(regex_text, raw, re.IGNORECASE):
                                xml_ok = True
                        except re.error:
                            xml_ok = False
                    else:
                        if search_text.lower() in (raw or "").lower():
                            xml_ok = True
                if scope == "Table only":
                    visible = table_ok
                elif scope == "XML only":
                    visible = xml_ok
                else:
                    visible = (table_ok or xml_ok)
            # set row hidden state
            self.table.setRowHidden(r, not visible)

        # After filtering, apply suspicious highlighting for visible rows, and XML tree highlight if necessary
        self.apply_event_highlighting()
        # For XML highlighting: if scope includes XML and search_text present, highlight currently shown tree if its event matches
        # Get currently selected row and apply highlight_tree_matches for its xml
        cur = self.table.currentRow()
        if cur >= 0:
            raw = self.records[cur].get("__raw_xml", "")
            if search_text != "" and scope in ("All", "XML only"):
                # apply regex or plain
                if use_regex:
                    highlight_tree_matches(self.xml_tree, regex_text, use_regex=True)
                else:
                    highlight_tree_matches(self.xml_tree, search_text, use_regex=False)
            else:
                # clear highlights
                highlight_tree_matches(self.xml_tree, "", use_regex=False)

    def _match_filter(self, cell_text, ftype, fval):
        if cell_text is None:
            cell_text = ""
        if ftype == "Contains":
            return fval.lower() in cell_text.lower()
        elif ftype == "Equals":
            return cell_text.lower() == fval.lower()
        elif ftype == "Starts with":
            return cell_text.lower().startswith(fval.lower())
        elif ftype == "Ends with":
            return cell_text.lower().endswith(fval.lower())
        elif ftype == "Regex":
            try:
                return re.search(fval, cell_text, re.IGNORECASE) is not None
            except re.error:
                return False
        return False

    # ---------------------------
    # Loading (same as before)
    # ---------------------------
    def load_channel(self):
        channel = self.channel_combo.currentText()
        self._start_read(channel)

    def load_from_file(self):
        default_dir = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "winevt", "Logs")
        path, _ = QFileDialog.getOpenFileName(self, "Select EVTX", default_dir, "Event Log Files (*.evtx)")
        if not path:
            return
        self._start_read(path)

    def _start_read(self, path_or_channel):
        self.load_btn.setEnabled(False)
        self.load_file_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
        self._set_status("Reading...")
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

    # ---------------------------
    # On read finished -> parse and populate table
    # ---------------------------
    def _on_read_finished(self, records):
        self.records = records or []
        parsed_records = []
        for rec in self.records:
            raw = rec.get("__raw_xml", "")
            parsed = parse_event_xml_to_dict(raw)
            parsed["__raw_xml"] = raw
            parsed_records.append(parsed)
        self.records = parsed_records

        # Build headers
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
        self.xml_tree.clear()
        # Apply highlighting to all rows initially
        self.apply_event_highlighting()

    # ---------------------------
    # Row interactions
    # ---------------------------
    def on_row_clicked(self, row, col):
        if 0 <= row < len(self.records):
            raw = self.records[row].get("__raw_xml", "")
            populate_tree_from_xml(self.xml_tree, raw, expand_level=1)
            # If there's an active global search that targets XML, highlight matches
            search_text = self.search_edit.text().strip()
            if search_text.startswith("re:"):
                highlight_tree_matches(self.xml_tree, search_text[3:], use_regex=True)
            elif search_text != "" and self.search_scope.currentText() in ("All", "XML only"):
                highlight_tree_matches(self.xml_tree, search_text, use_regex=False)
            else:
                highlight_tree_matches(self.xml_tree, "", use_regex=False)

    def on_row_double_clicked(self, row, col):
        if 0 <= row < len(self.records):
            raw = self.records[row].get("__raw_xml", "")
            pretty = raw
            try:
                from xml.dom import minidom
                txt = re.sub(r'\sxmlns="[^"]+"', '', raw, count=1)
                dom = minidom.parseString(txt)
                pretty = dom.toprettyxml(indent="  ")
                pretty = "\n".join([line for line in pretty.splitlines() if line.strip() != ""])
            except Exception:
                pass
            dlg = XmlDialog(pretty, self)
            dlg.exec()

    # ---------------------------
    # Highlight suspicious events (C)
    # ---------------------------
    def apply_event_highlighting(self):
        # iterate rows; if row visible and EventID in suspicious_map -> color row
        for r in range(self.table.rowCount()):
            hidden = self.table.isRowHidden(r)
            eid = ""
            # try to obtain EventID from header_keys
            for idx, key in enumerate(self.header_keys):
                if key.lower() in ("eventid", "event id"):
                    try:
                        eid = self.table.item(r, idx).text()
                    except Exception:
                        eid = ""
                    break
            # If eid may contain non-digits, strip
            eid_str = eid.strip()
            color = None
            if eid_str in self.suspicious_map:
                color = self.suspicious_map[eid_str]
            # Apply color if row visible
            for c in range(self.table.columnCount()):
                it = self.table.item(r, c)
                if it is None:
                    continue
                if color and not hidden:
                    it.setBackground(QBrush(color))
                else:
                    it.setBackground(QBrush())

    # ---------------------------
    # Utilities
    # ---------------------------
    def _set_status(self, text):
        self.status_label.setText(text)

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
