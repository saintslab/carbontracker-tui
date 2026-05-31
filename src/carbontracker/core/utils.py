import logging
from carbontracker.core.events import LogSeverity

# Map LogSeverity to standard logging levels
SEVERITY_MAP = {
    LogSeverity.DEBUG: logging.DEBUG,
    LogSeverity.INFO: logging.INFO,
    LogSeverity.WARNING: logging.WARNING,
    LogSeverity.ERROR: logging.ERROR,
    LogSeverity.CRITICAL: logging.CRITICAL,
}
