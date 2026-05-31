from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from carbontracker.core.events import (
    DiagnosticEvent,
    FinishedSession,
    LogSeverity,
    ProcessExitedEvent,
    SpanProfileEvent,
    StartedSession,
    TrackerEvent,
)
from carbontracker.watch.jsonl import read_jsonl_events

RunStatus = Literal["running", "finished", "failed", "warning", "incomplete"]


@dataclass(frozen=True)
class RunRecord:
    project_name: str
    run_name: str
    started_at: datetime | None
    status: RunStatus
    command: tuple[str, ...] | None
    source_log_path: Path
    return_code: int | None
    duration_s: float | None
    completed_spans_count: int
    local_power_usage_kwh: float
    local_emissions_g: float
    external_power_usage_kwh: float
    external_emissions_g: float
    external_accounting_methods: tuple[str, ...]
    event_count: int
    diagnostics_count: int
    diagnostic_messages: tuple[str, ...]
    components: tuple[str, ...]
    intensity_method: str | None
    pue: float | None
    power_sampling_interval_s: float | None
    intensity_sampling_interval_s: float | None
    total_units: int | None
    unit_name: str | None
    total_duration_s: float | None
    predict_after_units: int | None
    predict_after_seconds: float | None
    predict_interval_s: float | None

    @property
    def power_usage_kwh(self) -> float:
        return self.local_power_usage_kwh + self.external_power_usage_kwh

    @property
    def emissions_g(self) -> float:
        return self.local_emissions_g + self.external_emissions_g

    @property
    def average_intensity_g_per_kwh(self) -> float | None:
        if self.power_usage_kwh <= 0:
            return None
        return self.emissions_g / self.power_usage_kwh

    @property
    def unit_emissions_g(self) -> float | None:
        if self.total_units is None or self.total_units <= 0:
            return None
        return self.emissions_g / self.total_units


def build_run_catalog(log_dir: str | Path) -> list[RunRecord]:
    directory = Path(log_dir)
    records = [
        build_run_record(path) for path in sorted(directory.glob("*_events.jsonl"))
    ]
    return sorted(records, key=_catalog_sort_key, reverse=True)


def build_run_record(path: str | Path) -> RunRecord:
    source_path = Path(path)
    try:
        events = read_jsonl_events(source_path)
    except OSError as exc:
        return _diagnostic_record(source_path, f"Could not read JSONL event log: {exc}")
    return run_record_from_events(events, source_log_path=source_path)


def run_record_from_events(
    events: list[TrackerEvent] | tuple[TrackerEvent, ...],
    *,
    source_log_path: str | Path,
) -> RunRecord:
    source_path = Path(source_log_path)
    started = _last_event(events, StartedSession)
    finished = _last_event(events, FinishedSession)
    exited = _last_event(events, ProcessExitedEvent)
    diagnostics = [event for event in events if isinstance(event, DiagnosticEvent)]
    config_summary = _config_summary(started, finished)

    local_power_usage_kwh = 0.0
    local_emissions_g = 0.0
    duration_s: float | None = None
    completed_spans_count = 0
    if finished is not None:
        local_power_usage_kwh = finished.stats.total_power_usage_kwh
        local_emissions_g = finished.stats.total_emissions_g
        duration_s = finished.stats.duration_s
        completed_spans_count = finished.stats.completed_spans_count

    external_power_usage_kwh = 0.0
    external_emissions_g = 0.0
    methods: list[str] = []
    for event in events:
        if not isinstance(event, SpanProfileEvent):
            continue
        accounting = event.external_accounting
        if accounting is None:
            continue
        external_power_usage_kwh += accounting.energy_kwh
        external_emissions_g += accounting.emissions_g
        methods.append(accounting.method)

    return RunRecord(
        project_name=_project_name(started, finished),
        run_name=_run_name(started, finished, source_path),
        started_at=_started_at(started, finished, source_path),
        status=_status(started, finished, exited, diagnostics),
        command=_command(started, finished),
        source_log_path=source_path,
        return_code=None if exited is None else exited.return_code,
        duration_s=duration_s,
        completed_spans_count=completed_spans_count,
        local_power_usage_kwh=local_power_usage_kwh,
        local_emissions_g=local_emissions_g,
        external_power_usage_kwh=external_power_usage_kwh,
        external_emissions_g=external_emissions_g,
        external_accounting_methods=tuple(dict.fromkeys(methods)),
        event_count=len(events),
        diagnostics_count=len(diagnostics),
        diagnostic_messages=tuple(event.message for event in diagnostics),
        components=_tuple_config(config_summary, "components"),
        intensity_method=_str_config(config_summary, "intensity_method"),
        pue=_float_config(config_summary, "pue"),
        power_sampling_interval_s=_float_config(
            config_summary, "power_sampling_interval"
        ),
        intensity_sampling_interval_s=_float_config(
            config_summary, "intensity_sampling_interval"
        ),
        total_units=_int_config(config_summary, "total_units"),
        unit_name=_str_config(config_summary, "unit_name"),
        total_duration_s=_float_config(config_summary, "total_duration_s"),
        predict_after_units=_int_config(config_summary, "predict_after_units"),
        predict_after_seconds=_float_config(config_summary, "predict_after_seconds"),
        predict_interval_s=_float_config(config_summary, "predict_interval_s"),
    )


def _catalog_sort_key(record: RunRecord) -> tuple[datetime, str]:
    return (record.started_at or _file_mtime(record.source_log_path), record.run_name)


def _diagnostic_record(path: Path, message: str) -> RunRecord:
    return RunRecord(
        project_name="carbontracker",
        run_name=_run_name_from_path(path),
        started_at=_file_mtime(path),
        status="incomplete",
        command=None,
        source_log_path=path,
        return_code=None,
        duration_s=None,
        completed_spans_count=0,
        local_power_usage_kwh=0.0,
        local_emissions_g=0.0,
        external_power_usage_kwh=0.0,
        external_emissions_g=0.0,
        external_accounting_methods=(),
        event_count=0,
        diagnostics_count=1,
        diagnostic_messages=(message,),
        components=(),
        intensity_method=None,
        pue=None,
        power_sampling_interval_s=None,
        intensity_sampling_interval_s=None,
        total_units=None,
        unit_name=None,
        total_duration_s=None,
        predict_after_units=None,
        predict_after_seconds=None,
        predict_interval_s=None,
    )


def _last_event(
    events: list[TrackerEvent] | tuple[TrackerEvent, ...],
    event_type: type[StartedSession] | type[FinishedSession] | type[ProcessExitedEvent],
):
    for event in reversed(events):
        if isinstance(event, event_type):
            return event
    return None


def _config_summary(
    started: StartedSession | None,
    finished: FinishedSession | None,
) -> dict:
    if started is not None and isinstance(started.config_summary, dict):
        return started.config_summary
    if finished is not None and isinstance(finished.config_summary, dict):
        return finished.config_summary
    return {}


def _project_name(
    started: StartedSession | None,
    finished: FinishedSession | None,
) -> str:
    if started is not None:
        return started.project_name
    if finished is not None:
        return finished.project_name
    return "carbontracker"


def _run_name(
    started: StartedSession | None,
    finished: FinishedSession | None,
    path: Path,
) -> str:
    if started is not None:
        return started.run_name
    if finished is not None:
        return finished.run_name
    return _run_name_from_path(path)


def _run_name_from_path(path: Path) -> str:
    name = path.name
    if name.endswith("_events.jsonl"):
        return name[: -len("_events.jsonl")]
    return path.stem


def _started_at(
    started: StartedSession | None,
    finished: FinishedSession | None,
    path: Path,
) -> datetime | None:
    if started is not None:
        return started.timestamp
    if finished is not None:
        return finished.timestamp
    return _file_mtime(path)


def _command(
    started: StartedSession | None,
    finished: FinishedSession | None,
) -> tuple[str, ...] | None:
    if started is not None and started.command is not None:
        return started.command
    if finished is not None:
        return finished.command
    return None


def _status(
    started: StartedSession | None,
    finished: FinishedSession | None,
    exited: ProcessExitedEvent | None,
    diagnostics: list[DiagnosticEvent],
) -> RunStatus:
    if exited is not None and (exited.interrupted or exited.return_code not in (None, 0)):
        return "failed"
    if finished is not None:
        return "warning" if diagnostics else "finished"
    if started is not None and not diagnostics:
        return "running"
    return "incomplete"


def _file_mtime(path: Path) -> datetime:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return datetime.fromtimestamp(0)


def _tuple_config(config: dict, key: str) -> tuple[str, ...]:
    value = config.get(key)
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    return (str(value),)


def _str_config(config: dict, key: str) -> str | None:
    value = config.get(key)
    if value is None:
        return None
    return str(value)


def _float_config(config: dict, key: str) -> float | None:
    value = config.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_config(config: dict, key: str) -> int | None:
    value = config.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
