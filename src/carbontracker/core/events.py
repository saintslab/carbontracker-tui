from enum import Enum
from datetime import datetime
from typing import Any, Generic, Literal

from pydantic import ConfigDict
from pydantic.dataclasses import dataclass

from carbontracker.core.external import ExternalAccounting, ExternalUsage
from carbontracker.core.stats import SpanStats, SessionStatsData, SessionFinalStats
from carbontracker.providers.data_provider import TData

class LogSeverity(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

@dataclass(frozen=True)
class TrackerEvent():
    ...

@dataclass(frozen=True)
class SessionMetadata:
    project_name: str
    run_name: str
    log_dir: str
    log_file_path: str
    command: tuple[str, ...] | None = None
    trace_id: str | None = None
    config_summary: dict[str, Any] | None = None

@dataclass(frozen=True, config=ConfigDict(arbitrary_types_allowed=True))
class MeasurementEvent(TrackerEvent, Generic[TData]):
    provider_name: str 
    timestamp: datetime
    data: TData 
    
@dataclass(frozen=True)
class SpanStop(TrackerEvent):    
    ended_at: datetime
    span_id: str
    parent_span_id: str | None = None
    trace_id: str | None = None
    external_usage: ExternalUsage | None = None
    
@dataclass(frozen=True)
class SpanStart(TrackerEvent):    
    started_at: datetime 
    span_id: str
    parent_span_id: str | None = None
    trace_id: str | None = None

@dataclass(frozen=True)
class SpanProfileEvent(TrackerEvent):
    created_at: datetime
    span_id: str
    parent_span_id: str | None
    started_at: datetime
    ended_at: datetime
    profile: Any
    stats: SpanStats | None = None 
    external_accounting: ExternalAccounting | None = None
    
@dataclass(frozen=True)
class SessionCurrentStatsEvent(TrackerEvent):
    timestamp: datetime
    stats: SessionStatsData

@dataclass(frozen=True)
class PredictionEvent(TrackerEvent):    
    created_at: datetime 
    result: Any # Using Any to avoid circular import with prediction.py, or we can import it. Wait, let's just use Any for now or TYPE_CHECKING.
@dataclass(frozen=True)
class GuardEvent(TrackerEvent):
    created_at: datetime
    verdict: Any
    prediction: Any

@dataclass(frozen=True)
class DiagnosticEvent(TrackerEvent):
    severity: LogSeverity
    message: str
    logger_name: str
    timestamp: datetime

            
@dataclass(frozen=True)
class FinishedSession(TrackerEvent):
    timestamp: datetime
    project_name: str
    run_name: str
    log_dir: str
    log_file_path: str
    stats: SessionFinalStats
    command: tuple[str, ...] | None = None
    trace_id: str | None = None
    config_summary: dict[str, Any] | None = None

    @property
    def metadata(self) -> SessionMetadata:
        return SessionMetadata(
            project_name=self.project_name,
            run_name=self.run_name,
            log_dir=self.log_dir,
            log_file_path=self.log_file_path,
            command=self.command,
            trace_id=self.trace_id,
            config_summary=self.config_summary,
        )
    
@dataclass(frozen=True)
class StartedSession(TrackerEvent):
    timestamp: datetime
    project_name: str
    run_name: str
    log_dir: str
    log_file_path: str
    command: tuple[str, ...] | None = None
    trace_id: str | None = None
    config_summary: dict[str, Any] | None = None

    @property
    def metadata(self) -> SessionMetadata:
        return SessionMetadata(
            project_name=self.project_name,
            run_name=self.run_name,
            log_dir=self.log_dir,
            log_file_path=self.log_file_path,
            command=self.command,
            trace_id=self.trace_id,
            config_summary=self.config_summary,
        )

@dataclass(frozen=True)
class ProcessStartedEvent(TrackerEvent):
    timestamp: datetime
    command: tuple[str, ...]
    pid: int
    trace_id: str

@dataclass(frozen=True)
class ProcessExitedEvent(TrackerEvent):
    timestamp: datetime
    return_code: int | None
    interrupted: bool
    trace_id: str

@dataclass(frozen=True)
class ProcessOutputEvent(TrackerEvent):
    timestamp: datetime
    stream: Literal["stdout", "stderr"]
    line: str
    trace_id: str
