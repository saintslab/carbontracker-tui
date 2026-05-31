from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from carbontracker.core.event_codec import events_from_jsonl_lines
from carbontracker.core.events import DiagnosticEvent, LogSeverity, TrackerEvent


@dataclass
class JsonlEventSource:
    path: Path
    position: int = 0
    _reported_missing: bool = False

    def read_available(self) -> list[TrackerEvent]:
        if not self.path.exists():
            if self._reported_missing:
                return []
            self._reported_missing = True
            return [
                DiagnosticEvent(
                    severity=LogSeverity.ERROR,
                    logger_name="carbontracker.tui.sources",
                    message=f"JSONL event log not found: {self.path}",
                    timestamp=datetime.now(),
                )
            ]

        self._reported_missing = False
        with self.path.open() as handle:
            handle.seek(self.position)
            lines = handle.readlines()
            self.position = handle.tell()
        if not lines:
            return []
        return list(events_from_jsonl_lines(lines))


def read_jsonl_source(path: str | Path) -> list[TrackerEvent]:
    return JsonlEventSource(Path(path)).read_available()

