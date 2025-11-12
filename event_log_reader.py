"""
EVENT LOG READER FILE
Provides:
- Security copies of event files
- Parsing of events
# event_log_reader.py
"""

# ---------------------------
# Import libraries and modules
# ---------------------------
import os
import tempfile
import shutil

# Try pywin32
try:
    import win32evtlog
    import win32evtlogutil
    import win32con
except Exception:
    win32evtlog = None

# Try python-evtx
try:
    from Evtx.Evtx import Evtx
except Exception:
    Evtx = None

def safe_copy_evtx(path):
    """Copy file to temp to avoid locked-file issues."""
    dest_dir = tempfile.gettempdir()
    base = os.path.basename(path)
    dest = os.path.join(dest_dir, f"evtx_copy_{base}")
    shutil.copy2(path, dest)
    return dest

def read_evtx_summary(path, maxEvents=5000):
    """
    Read an .evtx file and return a list of dicts with key '__raw_xml' (xml string).
    Requires python-evtx (pip install python-evtx).
    """
    rows = []
    if not os.path.exists(path):
        raise FileNotFoundError(f"{path} not found")
    if Evtx is None:
        raise RuntimeError("python-evtx is not installed. Install with: pip install python-evtx")
    tmp = safe_copy_evtx(path)
    with Evtx(tmp) as log:
        for i, rec in enumerate(log.records()):
            xml = rec.xml()
            rows.append({"__raw_xml": xml})
            if i + 1 >= maxEvents:
                break
    return rows

class EventLogReader:
    """
    Wrapper around win32evtlog to read channels (if pywin32 is installed).
    Returns list of dicts with keys: Source, EventID, TimeCreated, Level, Message, Computer
    """
    def __init__(self):
        pass

    def readChannel(self, channel, maxEvents=5000):
        if win32evtlog is None:
            raise RuntimeError("pywin32 (win32evtlog) is required to read channels. Install pywin32.")
        server = None  # local
        try:
            hand = win32evtlog.OpenEventLog(server, channel)
        except Exception:
            raise
        flags = win32evtlog.EVENTLOG_BACKWARDS_READ | win32evtlog.EVENTLOG_SEQUENTIAL_READ
        records = []
        total = 0
        while True:
            events = win32evtlog.ReadEventLog(hand, flags, 0)
            if not events:
                break
            for ev in events:
                try:
                    src = str(ev.SourceName) if hasattr(ev, 'SourceName') else ""
                    eid = int(ev.EventID & 0xFFFF) if hasattr(ev, 'EventID') else ""
                    time = ev.TimeGenerated.Format() if hasattr(ev, 'TimeGenerated') else ""
                    level = getattr(ev, 'EventType', "")
                    msg = ""
                    try:
                        msg = win32evtlogutil.SafeFormatMessage(ev, channel)
                    except Exception:
                        msg = str(getattr(ev, 'StringInserts', "") or "")
                    rec = {
                        "Source": src,
                        "EventID": str(eid),
                        "TimeCreated": time,
                        "Level": str(level),
                        "Message": msg,
                        "Computer": getattr(ev, 'ComputerName', "")
                    }
                except Exception:
                    rec = {"Source": "", "EventID": "", "TimeCreated": "", "Level": "", "Message": "", "Computer": ""}
                records.append(rec)
                total += 1
                if total >= maxEvents:
                    break
            if total >= maxEvents:
                break
        try:
            win32evtlog.CloseEventLog(hand)
        except Exception:
            pass
        return records
