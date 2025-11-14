"""
MAIN WINDOW FILE
Provides:
- Shapping of the main window
- Calls to program main functions
- Security copies of event files
- Loading and exporting
- Population of tables
- XML Tree view
- Filtering functions
"""

# ---------------------------
# Import libraries and modules
# ---------------------------
import os
import re
import tempfile
import shutil
from xml.etree import ElementTree as ET
from datetime import datetime
from PyQt6.QtCore import Qt, QObject, pyqtSignal, QThread
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QPushButton, QLineEdit, QComboBox, QLabel, QTableWidget,
    QTableWidgetItem, QFileDialog, QMessageBox, QTextEdit, QDialog,
    QDialogButtonBox, QHeaderView, QTreeWidget, QTreeWidgetItem,
    QSizePolicy, QMenu
)
from PyQt6.QtGui import QColor, QBrush, QAction, QIcon

# Import of the reader module to make it easier to use
try:
    import event_log_reader as elr_mod
except Exception:
    elr_mod = None

# python-evtx fallback for files running without it being installed
try:
    from Evtx.Evtx import Evtx
except Exception:
    Evtx = None

# ---------------------------
# Helpers
# ---------------------------
# Creates a temporary copy of a file to avoid issues with locked or in-use event log files
# Returns the full path to the temporary copy
def safe_copy_to_temp(path):
    dest_dir = tempfile.gettempdir()
    base = os.path.basename(path)
    dest = os.path.join(dest_dir, f"evtx_copy_{base}")
    shutil.copy2(path, dest)
    return dest

# ---------------------------
# Reader verification, either function or module
# ---------------------------
# Worker class that runs on a separate thread to read event log files or channels
# Emits signals when finished or encounters errors to update the main UI safely
class ReaderWorker(QObject):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, path_or_channel, max_events=5000):
        super().__init__()
        self.path_or_channel = path_or_channel
        self.max_events = max_events

    # Executes the event log reading operation on a separate thread
    # Detects if input is a file path or channel name and reads accordingly
    # Emits finished signal with event records or error signal if something goes wrong
    def run(self):
        try:
            p = self.path_or_channel
            # file path
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
                            if i + 1 >= self.max_events:
                                break
                    self.finished.emit(rows)
                    return
                self.error.emit("No available file reader. Install python-evtx or provide read_evtx_summary.")
                return
            else:
                # channel name -> map to System32\winevt\Logs\<channel>.evtx (3 main options)
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
                            if i + 1 >= self.max_events:
                                break
                    self.finished.emit(rows)
                    return
                self.error.emit("No available reader for channel files. Install python-evtx or provide read_evtx_summary.")
                return
        except Exception as e:
            import traceback
            self.error.emit(traceback.format_exc())

# ---------------------------
# XML tree population
# ---------------------------
# Recursively converts an XML element and its children into a tree structure for display
# Shows attributes, text content, and child elements with proper hierarchy
# Automatically expands items up to the specified expand_level
def add_xml_element_to_tree(tree_parent, element, level=0, expand_level=1):
    tag = element.tag.split("}")[-1] if "}" in element.tag else element.tag
    item = QTreeWidgetItem([f"<{tag}>"])
    # attributes
    for k, v in element.attrib.items():
        attr_item = QTreeWidgetItem([f'Attribute: {k} = "{v}"'])
        item.addChild(attr_item)
    # text
    text = (element.text or "").strip()
    if text:
        text_item = QTreeWidgetItem([f'Text: "{text}"'])
        item.addChild(text_item)
    # children
    for child in element:
        child_item = add_xml_element_to_tree(child, child, level + 1, expand_level)
        item.addChild(child_item)
    if level <= expand_level:
        item.setExpanded(True)
    return item

# Parses XML text and displays it as a tree in the tree widget
# Handles XML parsing errors and removes xmlns attributes for cleaner display
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

# Searches for matching text in the XML tree and highlights found items with yellow background
# Expands parent items of matches for easy visibility
# Supports both plain text and regex pattern matching (better not to use, as I wasnt able to optimize it well)
def highlight_tree_matches(tree_widget, term, use_regex=False):
    if not term:
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
        if matched:
            item.setBackground(0, QBrush(QColor("#FFD44D")))
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
# Modal FilterDialog for advanced filters
# ---------------------------
# Modal dialog that allows users to create complex filtering rules
# Each rule consists of a field, operator, and one or two values for range-based operators
# Supports operators like =, !=, >, <, contains, regex, between, etc. (Better use the normal ones, same problem with regex)
class FilterDialog(QDialog):
    def __init__(self, parent=None, get_fields_callable=None):
        # Modal configuration
        super().__init__(parent)
        self.setWindowTitle("Advanced filters")
        self.setModal(True)
        self.resize(640, 360)
        self.get_fields_callable = get_fields_callable
        self.setWindowIcon(QIcon("filters.ico"))

        # Headers section for filter (layout)
        layout = QVBoxLayout(self)
        self.rules_table = QTableWidget()
        self.rules_table.setColumnCount(4)
        self.rules_table.setHorizontalHeaderLabels(["Field", "Operator", "Value", "Value2 (if between)"])
        self.rules_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.rules_table)
        
        # Configuration of layout controls
        controls = QWidget()
        c_layout = QHBoxLayout()
        c_layout.setContentsMargins(0,0,0,0)
        controls.setLayout(c_layout)

        # Setting functionality buttons
        self.add_btn = QPushButton("+ Add Rule")
        self.apply_btn = QPushButton("Apply")
        self.clear_btn = QPushButton("Clear")
        self.cancel_btn = QPushButton("Cancel")

        # styling properties used by stylesheet in main.py
        self.apply_btn.setProperty('primary', True)
        self.clear_btn.setProperty('secondary', True)

        # Positioning of buttopns in modal view
        c_layout.addWidget(self.add_btn)
        c_layout.addStretch(1)
        c_layout.addWidget(self.apply_btn)
        c_layout.addWidget(self.clear_btn)
        c_layout.addWidget(self.cancel_btn)
        layout.addWidget(controls)

        # Connection between rules functionality and visual elements
        self.add_btn.clicked.connect(self.add_empty_rule)
        self.apply_btn.clicked.connect(self.on_apply)
        self.clear_btn.clicked.connect(self.on_clear)
        self.cancel_btn.clicked.connect(self.reject)
        self.rules = []     # rules counter list

    # Returns the list of available fields for filtering
    # Can use a custom callable or fall back to default field list
    def refresh_fields(self):
        if callable(self.get_fields_callable):
            return self.get_fields_callable()
        return ["Source", "EventID", "TimeCreated", "Level", "Message", "Computer"]

    # Adds a new empty filter rule row to the table with dropdowns and text inputs
    def add_empty_rule(self):
        row = self.rules_table.rowCount()
        self.rules_table.insertRow(row)
        # Field combobox
        field_combo = QComboBox()
        field_combo.addItems(self.refresh_fields())
        self.rules_table.setCellWidget(row, 0, field_combo)
        # Operator
        op_combo = QComboBox()
        op_combo.addItems(["=", "!=", ">", "<", ">=", "<=", "contains", "startswith", "endswith", "regex", "between"])
        self.rules_table.setCellWidget(row, 1, op_combo)
        # Value inputs
        val_edit = QLineEdit()
        val_edit.setProperty('dialoginput', True)
        self.rules_table.setCellWidget(row, 2, val_edit)
        val2_edit = QLineEdit()
        val2_edit.setProperty('dialoginput', True)
        self.rules_table.setCellWidget(row, 3, val2_edit)

    # Extracts all filter rules from the dialog table and returns them as a list of dictionaries
    # Skips empty rows and returns only complete rules with values
    def get_rules(self):
        rules = []
        for r in range(self.rules_table.rowCount()):
            fw = self.rules_table.cellWidget(r, 0)
            ow = self.rules_table.cellWidget(r, 1)
            vw = self.rules_table.cellWidget(r, 2)
            v2w = self.rules_table.cellWidget(r, 3)
            if not fw or not ow:
                continue
            field = fw.currentText()
            op = ow.currentText()
            val = vw.text().strip() if vw else ""
            val2 = v2w.text().strip() if v2w else ""
            # require at least a value for most ops
            if val == "" and op not in ("is empty", "is not empty"):
                continue
            rules.append({"field": field, "op": op, "value": val, "value2": val2})
        return rules

    # Collects all rules and closes the dialog with acceptance status
    def on_apply(self):
        self.rules = self.get_rules()
        self.accept()

    # Clears all filter rules from the table
    def on_clear(self):
        self.rules_table.setRowCount(0)
        self.rules = []

# ---------------------------
# Parse event XML to canonical dict (Source, EventID, TimeCreated, Level, Message, other EventData fields)
# ---------------------------
# Extracts event information from Windows Event Log XML format
# Parses System section for provider, event ID, time, level, and computer
# Also extracts Message and EventData fields for additional details
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
# Main window
# ---------------------------
# Main application window that displays event logs in a table with XML tree view
# Provides filtering, searching, export functionality, and event highlighting
class MainWindow(QMainWindow):
    # Initializes the main window UI with table, tree view, buttons, and all controls
    # Sets up signal/slot connections and state variables for data management
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Windows Event Log Analyzer")
        self.resize(1300, 850)

        # Top bar
        top = QWidget()
        top_l = QHBoxLayout()
        top_l.setContentsMargins(0,0,0,0)
        top_l.setSpacing(6)
        top.setLayout(top_l)
        top.setFixedHeight(42)
        top.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        # Controls (no quick filters; single Filters button)
        self.channel_combo = QComboBox()
        self.channel_combo.addItems(["Application", "System", "Security"])
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Global search")
        self.search_scope = QComboBox()
        self.search_scope.addItems(["All", "Table only", "XML only"])
        self.filters_btn = QPushButton("Filters")
        self.load_btn = QPushButton("Load Events")
        self.load_file_btn = QPushButton("Load From File")
        self.export_btn = QPushButton("Export CSV")
        self.status_label = QLabel("Ready")

        top_l.addWidget(self.channel_combo)
        top_l.addWidget(self.search_edit, 1)
        top_l.addWidget(self.search_scope)
        top_l.addWidget(self.filters_btn)
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

        # header context menu for column filters (simple)
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
        self.filters_btn.clicked.connect(self.open_filters_dialog)
        self.table.cellClicked.connect(self.on_row_clicked)
        self.table.cellDoubleClicked.connect(self.on_row_double_clicked)

        # state
        self.records = []
        self.canonical_cols = ["Source", "EventID", "TimeCreated", "Level", "Message", "Computer"]
        self.header_keys = ["Source", "EventID", "TimeCreated", "Level", "Message"]

        # filters
        self.active_filters = {}           # column filters {col_index: (type_str, value)}
        self.advanced_filters = []         # structured advanced filters (list of dicts)

        # threading
        self.thread = None
        self.worker = None

        # suspicious event highlighting map (EventID -> color)
        self.suspicious_map = {
            "4624": QColor("#1a3b1a"),
            "4625": QColor("#3b391a"),
            "4688": QColor("#1a263b"),
            "7045": QColor("#3b1a1a"),
            "1102": QColor("#3b1a1a"),
        }

    # ---------------------------
    # Header context menu
    # ---------------------------
    # Shows a context menu when right-clicking on table column headers
    # Allows filtering by selected cell value or clearing column filters
    def on_header_context_menu(self, pos):
        header = self.table.horizontalHeader()
        logical_index = header.logicalIndexAt(pos)
        if logical_index < 0:
            return
        column_name = header.model().headerData(logical_index, Qt.Orientation.Horizontal)
        menu = QMenu(self)
        act_filter_by_value = QAction(f"Filter by value from selection...", self)
        act_clear = QAction(f"Clear filter '{column_name}'", self)
        menu.addAction(act_filter_by_value)
        menu.addAction(act_clear)
        action = menu.exec(header.mapToGlobal(pos))
        if action == act_filter_by_value:
            sel = self.table.selectedRanges()
            if sel:
                rng = sel[0]
                r = rng.topRow()
                c = logical_index
                it = self.table.item(r, c)
                if it:
                    value = it.text()
                    self.active_filters[logical_index] = ("Contains", value)
                    self.apply_filters_and_search()
        elif action == act_clear:
            if logical_index in self.active_filters:
                del self.active_filters[logical_index]
                self.apply_filters_and_search()

    # ---------------------------
    # Open advanced Filters dialog (modal)
    # ---------------------------
    # Opens the advanced filter dialog and applies selected rules to filter the event table
    # Changes filter button color when filters are active
    def open_filters_dialog(self):
        dlg = FilterDialog(self, get_fields_callable=self.get_available_fields)
        dlg.refresh_fields()
        # pre-populate
        for rule in self.advanced_filters:
            dlg.add_empty_rule()
            r = dlg.rules_table.rowCount() - 1
            fw = dlg.rules_table.cellWidget(r, 0)
            ow = dlg.rules_table.cellWidget(r, 1)
            vw = dlg.rules_table.cellWidget(r, 2)
            v2w = dlg.rules_table.cellWidget(r, 3)
            try:
                if fw:
                    idx = fw.findText(rule.get('field'))
                    if idx >= 0:
                        fw.setCurrentIndex(idx)
            except Exception:
                pass
            try:
                if ow:
                    idx2 = ow.findText(rule.get('op'))
                    if idx2 >= 0:
                        ow.setCurrentIndex(idx2)
            except Exception:
                pass
            if vw:
                vw.setText(rule.get('value', ''))
            if v2w:
                v2w.setText(rule.get('value2', ''))
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.advanced_filters = dlg.rules or []
            if self.advanced_filters:
                self.filters_btn.setStyleSheet('background-color: #154e7a; color: white;')
            else:
                self.filters_btn.setStyleSheet('')
            self.apply_filters_and_search()

    # Returns a list of all available fields from loaded records for use in filter rules
    # Prioritizes canonical columns and removes duplicates
    def get_available_fields(self):
        fields = list(self.header_keys)
        for c in self.canonical_cols:
            if c not in fields:
                fields.insert(0, c)
        seen = set()
        res = []
        for f in fields:
            if f not in seen:
                seen.add(f)
                res.append(f)
        return res

    # ---------------------------
    # Search & filters orchestration
    # ---------------------------
    # Triggered when search text changes; applies all filters and search terms
    def on_search_changed(self, txt):
        self.apply_filters_and_search()

    # Main filtering and search orchestration method
    # Applies advanced filters, column filters, and global search to show/hide table rows
    # Supports regex patterns with 're:' prefix and different search scopes (All, Table only, XML only)
    def apply_filters_and_search(self):
        def check_advanced(rec):
            for rule in self.advanced_filters:
                field = rule.get('field')
                op = rule.get('op')
                val = rule.get('value')
                val2 = rule.get('value2', '')
                field_val = rec.get(field, '')
                if not self.evaluate_rule(field_val, op, val, val2, field):
                    return False
            return True

        def check_column_filters(row_idx):
            for col_idx, (ftype, fval) in self.active_filters.items():
                try:
                    item = self.table.item(row_idx, col_idx)
                    cell_text = item.text() if item else ''
                except Exception:
                    cell_text = ''
                if not self._match_filter(cell_text, ftype, fval):
                    return False
            return True

        search_text = self.search_edit.text().strip()
        use_regex = False
        regex_text = ''
        if search_text.startswith('re:'):
            use_regex = True
            regex_text = search_text[3:]
        scope = self.search_scope.currentText()

        for r in range(self.table.rowCount()):
            visible = True
            rec = self.records[r] if r < len(self.records) else {}
            # advanced
            if self.advanced_filters:
                if not check_advanced(rec):
                    visible = False
            # column filters
            if visible and self.active_filters:
                if not check_column_filters(r):
                    visible = False
            # global search
            if visible and search_text != '':
                table_ok = False
                xml_ok = False
                if scope in ('All', 'Table only'):
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
                if scope in ('All', 'XML only'):
                    raw = self.records[r].get('__raw_xml', '')
                    if use_regex:
                        try:
                            if re.search(regex_text, raw, re.IGNORECASE):
                                xml_ok = True
                        except re.error:
                            xml_ok = False
                    else:
                        if search_text.lower() in (raw or '').lower():
                            xml_ok = True
                if scope == 'Table only':
                    visible = table_ok
                elif scope == 'XML only':
                    visible = xml_ok
                else:
                    visible = (table_ok or xml_ok)
            self.table.setRowHidden(r, not visible)

        self.apply_event_highlighting()

        # highlight tree for current selection if search targets XML
        cur = self.table.currentRow()
        if cur >= 0:
            raw = self.records[cur].get('__raw_xml', '')
            if search_text != '' and scope in ('All', 'XML only'):
                if use_regex:
                    highlight_tree_matches(self.xml_tree, regex_text, use_regex=True)
                else:
                    highlight_tree_matches(self.xml_tree, search_text, use_regex=False)
            else:
                highlight_tree_matches(self.xml_tree, '', use_regex=False)

    # Evaluates a single filter rule against a field value
    # Handles different operators (=, !=, >, <, contains, regex, between, etc.)
    # Supports special comparison types for numeric EventIDs and datetime fields
    def evaluate_rule(self, field_val, op, val, val2, field_name):
        fv = field_val or ''
        # numeric EventID comparisons
        if field_name.lower() in ('eventid', 'event id'):
            try:
                fv_n = int(re.sub(r'\D', '', fv)) if fv else 0
            except Exception:
                fv_n = 0
            try:
                v_n = int(val)
            except Exception:
                return False
            try:
                v2_n = int(val2) if val2 else None
            except Exception:
                v2_n = None
            if op == '=':
                return fv_n == v_n
            if op == '!=':
                return fv_n != v_n
            if op == '>':
                return fv_n > v_n
            if op == '<':
                return fv_n < v_n
            if op == '>=':
                return fv_n >= v_n
            if op == '<=':
                return fv_n <= v_n
            if op == 'between':
                if v2_n is None:
                    return False
                return v_n <= fv_n <= v2_n
            if op == 'regex':
                try:
                    return re.search(val, fv, re.IGNORECASE) is not None
                except re.error:
                    return False
            if op == 'contains':
                return val.lower() in fv.lower()
            if op == 'startswith':
                return fv.lower().startswith(val.lower())
            if op == 'endswith':
                return fv.lower().endswith(val.lower())
        # date/time comparisons
        elif field_name.lower() in ('timecreated', 'time', 'timestamp', 'date'):
            try:
                if fv:
                    fv_dt = None
                    try:
                        fv_dt = datetime.fromisoformat(fv.replace('Z', '+00:00'))
                    except Exception:
                        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
                            try:
                                fv_dt = datetime.strptime(fv, fmt)
                                break
                            except Exception:
                                pass
                    if fv_dt is None:
                        return False
                else:
                    return False
                # parse target(s)
                if op in ('>', '<', '>=', '<=', '=', '!='):
                    try:
                        v_dt = datetime.fromisoformat(val.replace('Z', '+00:00'))
                    except Exception:
                        try:
                            v_dt = datetime.fromisoformat(val)
                        except Exception:
                            return False
                    if op == '>':
                        return fv_dt > v_dt
                    if op == '<':
                        return fv_dt < v_dt
                    if op == '>=':
                        return fv_dt >= v_dt
                    if op == '<=':
                        return fv_dt <= v_dt
                    if op == '=':
                        return fv_dt == v_dt
                    if op == '!=':
                        return fv_dt != v_dt
                if op == 'between':
                    try:
                        v1 = datetime.fromisoformat(val.replace('Z', '+00:00'))
                        v2 = datetime.fromisoformat(val2.replace('Z', '+00:00'))
                        return v1 <= fv_dt <= v2
                    except Exception:
                        return False
                if op == 'regex':
                    try:
                        return re.search(val, fv, re.IGNORECASE) is not None
                    except re.error:
                        return False
                if op == 'contains':
                    return val.lower() in fv.lower()
                return False
            except Exception:
                return False
        else:
            # string comparisons
            if op == '=':
                return fv.lower() == val.lower()
            if op == '!=':
                return fv.lower() != val.lower()
            if op == 'contains':
                return val.lower() in fv.lower()
            if op == 'startswith':
                return fv.lower().startswith(val.lower())
            if op == 'endswith':
                return fv.lower().endswith(val.lower())
            if op == 'regex':
                try:
                    return re.search(val, fv, re.IGNORECASE) is not None
                except re.error:
                    return False
            # fallback numeric compare
            try:
                fv_n = float(fv)
                v_n = float(val)
                if op == '>':
                    return fv_n > v_n
                if op == '<':
                    return fv_n < v_n
                if op == '>=':
                    return fv_n >= v_n
                if op == '<=':
                    return fv_n <= v_n
            except Exception:
                pass
        return False

    # Tests if a cell value matches a column filter of a given type (Contains, Equals, Starts with, etc.)
    def _match_filter(self, cell_text, ftype, fval):
        if cell_text is None:
            cell_text = ''
        if ftype == 'Contains':
            return fval.lower() in cell_text.lower()
        elif ftype == 'Equals':
            return cell_text.lower() == fval.lower()
        elif ftype == 'Starts with':
            return cell_text.lower().startswith(fval.lower())
        elif ftype == 'Ends with':
            return cell_text.lower().endswith(fval.lower())
        elif ftype == 'Regex':
            try:
                return re.search(fval, cell_text, re.IGNORECASE) is not None
            except re.error:
                return False
        return False

    # ---------------------------
    # Loading events (channel or file)
    # ---------------------------
    # Reads events from the selected Windows event log channel (Application, System, Security)
    def load_channel(self):
        channel = self.channel_combo.currentText()
        self._start_read(channel)

    # Opens a file dialog to select an .evtx file and loads events from it
    def load_from_file(self):
        default_dir = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "winevt", "Logs")
        path, _ = QFileDialog.getOpenFileName(self, "Select EVTX", default_dir, "Event Log Files (*.evtx)")
        if not path:
            return
        self._start_read(path)

    # Starts the event reading operation in a separate thread to avoid UI freezing
    # Disables UI controls during reading and shows status
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

    # Handles errors during event log reading and displays error message to user
    def _on_read_error(self, msg):
        self._set_status("Error")
        QMessageBox.critical(self, "Read error", str(msg))
        self.load_btn.setEnabled(True)
        self.load_file_btn.setEnabled(True)
        self.export_btn.setEnabled(True)

    # ---------------------------
    # Read finished: parse XML and populate table
    # ---------------------------
    # Processes loaded event records, parses XML, and populates the table with event data
    # Dynamically determines columns based on union of all record fields
    def _on_read_finished(self, records):
        self.records = records or []
        parsed_records = []
        for rec in self.records:
            raw = rec.get("__raw_xml", "")
            parsed = parse_event_xml_to_dict(raw)
            parsed["__raw_xml"] = raw
            parsed_records.append(parsed)
        self.records = parsed_records

        # Build columns based on union of keys
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
        self.apply_event_highlighting()

    # ---------------------------
    # Row click / double click
    # ---------------------------
    def on_row_clicked(self, row, col):
        if 0 <= row < len(self.records):
            raw = self.records[row].get("__raw_xml", "")
            populate_tree_from_xml(self.xml_tree, raw, expand_level=1)
            search_text = self.search_edit.text().strip()
            if search_text.startswith("re:"):
                highlight_tree_matches(self.xml_tree, search_text[3:], use_regex=True)
            elif search_text != "" and self.search_scope.currentText() in ("All", "XML only"):
                highlight_tree_matches(self.xml_tree, search_text, use_regex=False)
            else:
                highlight_tree_matches(self.xml_tree, "", use_regex=False)

    # Opens a modal dialog showing the full formatted XML of the double-clicked event for detailed inspection
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
            dlg = QDialog(self)
            dlg.setWindowTitle("Event XML (detail)")
            dlg.setModal(True)
            v = QVBoxLayout(dlg)
            te = QTextEdit()
            te.setReadOnly(True)
            te.setPlainText(pretty)
            v.addWidget(te)
            btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            v.addWidget(btns)
            btns.rejected.connect(dlg.reject)
            dlg.resize(900, 600)
            dlg.exec()

    # ---------------------------
    # Highlight suspicious events
    # ---------------------------
    # Applies background color highlighting to rows with suspicious/high-risk event IDs
    # Uses a predefined map of event ID to color for visual identification
    def apply_event_highlighting(self):
        for r in range(self.table.rowCount()):
            hidden = self.table.isRowHidden(r)
            eid = ''
            for idx, key in enumerate(self.header_keys):
                if key.lower() in ('eventid', 'event id'):
                    try:
                        eid = self.table.item(r, idx).text()
                    except Exception:
                        eid = ''
                    break
            eid_str = eid.strip()
            color = None
            if eid_str in self.suspicious_map:
                color = self.suspicious_map[eid_str]
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
    # Updates the status label text in the main window
    def _set_status(self, text):
        self.status_label.setText(text)

    # Exports currently loaded and visible event records to a CSV file
    # Handles special characters and newlines in field values for proper CSV formatting (Just the simple one, the other was too weird)
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
