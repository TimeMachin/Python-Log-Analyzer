# ----------------------------------------------------------------------
# Defincion de librerias
# ----------------------------------------------------------------------
import win32evtlog
import win32evtlogutil
import win32con
import os

class EventRecord:
    def __init__(self, source, event_id, time_generated, message):
        self.source = source
        self.event_id = event_id
        self.time_generated = time_generated
        self.message = message


class EventLogReader:
    def read_channel(self, channel_or_path: str):
        """
        Si 'channel_or_path' es un nombre de canal (System, Application, etc.), 
        se abre directamente con OpenEventLog.
        Si es una ruta existente, se asume que es un archivo .evtx.
        """
        events = []
        total = 0

        try:
            if os.path.exists(channel_or_path):
                # Es un archivo .evtx
                handle = win32evtlog.OpenBackupEventLog(None, channel_or_path)
            else:
                # Es un canal del sistema
                handle = win32evtlog.OpenEventLog(None, channel_or_path)
        except Exception as e:
            print("Error al abrir el registro:", e)
            return events

        flags = win32evtlog.EVENTLOG_BACKWARDS_READ | win32evtlog.EVENTLOG_SEQUENTIAL_READ

        while True:
            records = win32evtlog.ReadEventLog(handle, flags, 0)
            if not records:
                break
            for event in records:
                msg = ""
                try:
                    msg = win32evtlogutil.SafeFormatMessage(event, channel_or_path)
                except Exception:
                    msg = "<No message>"

                events.append(EventRecord(
                    event.SourceName,
                    event.EventID,
                    event.TimeGenerated.Format(),
                    msg.strip()
                ))

                total += 1

        win32evtlog.CloseEventLog(handle)
        return events
