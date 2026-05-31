import logging
from datetime import datetime
from queue import Queue
from typing import List
from carbontracker.core.events import DiagnosticEvent, LogSeverity

class EventQueueLogHandler(logging.Handler):
    """
    A custom logging handler that takes standard Python log records 
    and puts them into CarbonTracker's event queues as DiagnosticEvents.
    """
    def __init__(self, event_sinks: List["Queue[DiagnosticEvent]"]):
        super().__init__()
        self.event_sinks = event_sinks

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
        except Exception:
            self.handleError(record)
            return

        # Map Python's logging level names to our LogSeverity enum safely
        try:
            severity = LogSeverity(record.levelname)
        except ValueError:
            # Fallback if somehow a custom log level string is used
            severity = LogSeverity.INFO

        event = DiagnosticEvent(
            severity=severity,
            message=msg,
            logger_name=record.name,
            timestamp=datetime.fromtimestamp(record.created)
        )

        for sink in self.event_sinks:
            sink.put(event)
