from pydantic.dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Marker:
    marker_id: str
    trace_id: str
    span_id: str  # The ID of THIS specific block (epoch, function, etc.)
    parent_span_id: str | None  # The ID of the block that wraps this one (None if root)
    timestamp: datetime
    tags: dict[str, str] | None = None  # Standardized metadata
