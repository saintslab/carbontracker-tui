import queue
import uuid
from datetime import datetime
from threading import Event
from typing import Optional, List

from carbontracker.core.markers import Marker
from carbontracker.core.events import TrackerEvent
from carbontracker.observers.base import ObserverThread


class ManualObserverThread(ObserverThread):
    def __init__(
        self,
        aggregation_queue: "queue.Queue[TrackerEvent]",
        event_sink: "List[queue.Queue[TrackerEvent]]",
        notify_events: List[Event],
        trace_id: str | None = None,
    ) -> None:
        super().__init__(
            aggregation_queue=aggregation_queue,
            event_sink=event_sink,
            notify_events=notify_events,
            name="python-api"
        )
        self._current_epoch = 0
        self._current_span_id: Optional[str] = None
        self._trace_id = trace_id if trace_id is not None else str(uuid.uuid4())

    def manual_start(self) -> None:
        self._current_epoch += 1
        self._current_span_id = f"epoch_{self._current_epoch}"
        marker = Marker(
            marker_id=str(uuid.uuid4()),
            trace_id=self._trace_id,
            parent_span_id=None,
            timestamp=datetime.now(),
            span_id=self._current_span_id,
            tags={"event": "start", "epoch": str(self._current_epoch)}
        )
        self._emit_start(marker)

    def manual_end(self) -> None:
        if not self._current_span_id:
            return

        marker = Marker(
            marker_id=str(uuid.uuid4()),
            trace_id=self._trace_id,
            parent_span_id=None,
            timestamp=datetime.now(),
            span_id=self._current_span_id,
            tags={"event": "end", "epoch": str(self._current_epoch)}
        )
        self._emit_stop(marker)
        self._current_span_id = None

    def run(self) -> None:
        self._stop_event.wait()
