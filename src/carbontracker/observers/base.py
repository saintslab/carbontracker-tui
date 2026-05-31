import queue
from threading import Event, Thread
from typing import List

from carbontracker.core.events import TrackerEvent, SpanStart, SpanStop
from carbontracker.core.external import ExternalUsage
from carbontracker.core.markers import Marker

class ObserverThread(Thread):
    def __init__(
        self, 
        aggregation_queue: "queue.Queue[TrackerEvent]",
        event_sink: "List[queue.Queue[TrackerEvent]]",
        notify_events: List[Event],
        name: str
    ) -> None:
        super().__init__()
        self.aggregation_queue = aggregation_queue
        self.event_sink = event_sink
        self.notify_events = notify_events
        self._stop_event = Event()
        self.daemon = True
        self.name = name + "observer"
    
    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        raise NotImplementedError("Subclasses must implement run()")

    def _emit_start(self, marker: Marker) -> None:
        """Helper for subclasses to emit start events and trigger providers."""
        event = SpanStart(started_at=marker.timestamp, span_id=marker.span_id, parent_span_id=marker.parent_span_id, trace_id=marker.trace_id)
        self.aggregation_queue.put(event)
        for sink in self.event_sink:
            sink.put(event)
            
        # Wake up data providers for a snapshot at the boundary
        for ne in self.notify_events:
            ne.set()

    def _emit_stop(
        self, marker: Marker, external_usage: ExternalUsage | None = None
    ) -> None:
        """Helper for subclasses to emit stop events. DOES NOT trigger providers."""
        event = SpanStop(
            ended_at=marker.timestamp,
            span_id=marker.span_id,
            parent_span_id=marker.parent_span_id,
            trace_id=marker.trace_id,
            external_usage=external_usage,
        )
        self.aggregation_queue.put(event)
        for sink in self.event_sink:
            sink.put(event)
