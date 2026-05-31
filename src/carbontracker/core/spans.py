from datetime import datetime
from dataclasses import dataclass

from carbontracker.core.events import SpanStart, SpanStop
from carbontracker.core.external import ExternalAccounting, ExternalUsage


@dataclass
class SpanRecord:
    """Aggregator-owned interval state derived from span marker events."""

    span_id: str
    parent_span_id: str | None
    started_at: datetime
    ended_at: datetime | None = None
    trace_id: str | None = None
    external_usage: ExternalUsage | None = None
    external_accounting: ExternalAccounting | None = None

    @classmethod
    def from_start(cls, event: SpanStart) -> "SpanRecord":
        return cls(
            span_id=event.span_id,
            parent_span_id=event.parent_span_id,
            started_at=event.started_at,
            trace_id=event.trace_id,
        )

    def close(self, event: SpanStop) -> None:
        self.ended_at = event.ended_at
        if event.parent_span_id is not None:
            self.parent_span_id = event.parent_span_id
        self.external_usage = event.external_usage
