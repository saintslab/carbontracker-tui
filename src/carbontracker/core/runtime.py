import logging
import queue
import uuid
from dataclasses import dataclass, field, fields
from datetime import datetime
from pathlib import Path
from threading import Event, Thread
from typing import Any, Sequence

from carbontracker.config.config import LogLevel
from carbontracker.core.aggregator import AggregatorThread
from carbontracker.core.events import SessionMetadata, StartedSession, TrackerEvent
from carbontracker.core.prediction import PredictionEngine
from carbontracker.core.profiling import SpanPowerProfiler
from carbontracker.core.types import Component, IntensityMethod, Location
from carbontracker.observers.base import ObserverThread
from carbontracker.observers.providers.manual import ManualObserverThread
from carbontracker.observers.providers.subprocess import SubprocessObserverThread
from carbontracker.providers.carbon_intensity.factory import create_intensity_thread
from carbontracker.providers.carbon_intensity_forecast.factory import (
    create_intensity_forecast_thread,
)
from carbontracker.providers.data_provider_thread import DataProviderThread
from carbontracker.providers.power.factory import create_power_thread
from carbontracker.reporters.file_logger import FileWriterThread
from carbontracker.reporters.logging_handler import EventQueueLogHandler
from carbontracker.reporters.terminal import TerminalOutputThread


def _normalize_provider_name(value: str) -> str:
    normalized = value.strip().replace("-", "_")
    if normalized.lower() in {"electricitymaps", "electricity_maps"}:
        return "electricity_maps"
    return normalized


def _coerce_log_level(value: LogLevel | str) -> LogLevel:
    if isinstance(value, LogLevel):
        return value
    try:
        return LogLevel(str(value).strip().lower())
    except ValueError as exc:
        raise ValueError(f"Invalid log level: {value}") from exc


def _coerce_intensity_method(value: IntensityMethod | str) -> IntensityMethod:
    if isinstance(value, IntensityMethod):
        return value
    normalized = str(value).strip().replace("-", "_").lower()
    if normalized == "electricitymaps":
        normalized = "electricity_maps"
    try:
        return IntensityMethod(normalized)
    except ValueError as exc:
        raise ValueError(f"Invalid intensity method: {value}") from exc


def _coerce_components(components: Sequence[Component | str] | None) -> list[Component]:
    if components is None:
        return [Component.CPU, Component.GPU, Component.RAM]
    if not components:
        raise ValueError("components must contain at least one component")

    resolved: list[Component] = []
    for component in components:
        if isinstance(component, Component):
            resolved.append(component)
            continue
        try:
            resolved.append(Component(str(component).strip().lower()))
        except ValueError as exc:
            raise ValueError(f"Invalid component: {component}") from exc
    return resolved


def _positive_number(name: str, value: float) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be greater than zero")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be greater than zero") from exc
    if numeric <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return numeric


def _positive_int(name: str, value: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be greater than zero")
    try:
        numeric = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be greater than zero") from exc
    if numeric <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return numeric


def _nonnegative_int(name: str, value: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be greater than or equal to zero")
    try:
        numeric = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be greater than or equal to zero") from exc
    if numeric < 0:
        raise ValueError(f"{name} must be greater than or equal to zero")
    return numeric


def _nonnegative_number(name: str, value: float) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be greater than or equal to zero")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be greater than or equal to zero") from exc
    if numeric < 0:
        raise ValueError(f"{name} must be greater than or equal to zero")
    return numeric


def generate_default_run_name(now: datetime | None = None) -> str:
    timestamp = now if now is not None else datetime.now()
    return timestamp.strftime("run_%Y%m%d_%H%M%S")


@dataclass(frozen=True)
class RuntimeOptions:
    project_name: str = "carbontracker"
    run_name: str = field(default_factory=generate_default_run_name)
    log_dir: str = "carbontracker_logs/"
    ignore_errors: bool = True
    log_level: LogLevel | str = LogLevel.WARNING
    session_stat_interval_s: float = 1.0
    components: Sequence[Component | str] | None = None
    pue: float = 1.1
    power_sampling_interval: float = 15.0
    devices_by_pids: list[str] = field(default_factory=list)
    intensity_method: IntensityMethod | str = IntensityMethod.AUTO
    intensity_sampling_interval: float = 900.0
    location: Location | str | None = None
    static_carbon_intensity_g_per_kwh: float | None = None
    api_keys: dict[str, str] | None = None
    forecast_provider_name: str | None = None
    auto_detect_location: bool = True
    total_units: int | None = None
    unit_name: str | None = None
    total_duration_s: float | None = None
    predict_after_units: int | None = None
    predict_after_seconds: float | None = None
    predict_interval_s: float | None = None

    def __post_init__(self) -> None:
        project_name = str(self.project_name).strip()
        if not project_name:
            raise ValueError("project_name must be a non-empty string")
        object.__setattr__(self, "project_name", project_name)

        run_name = str(self.run_name).strip()
        if not run_name:
            raise ValueError("run_name must be a non-empty string")
        object.__setattr__(self, "run_name", run_name)

        log_dir = str(self.log_dir).strip()
        if not log_dir:
            raise ValueError("log_dir must be a non-empty string")
        object.__setattr__(self, "log_dir", log_dir)

        object.__setattr__(self, "log_level", _coerce_log_level(self.log_level))
        object.__setattr__(self, "components", _coerce_components(self.components))
        object.__setattr__(
            self,
            "session_stat_interval_s",
            _positive_number("session_stat_interval_s", self.session_stat_interval_s),
        )
        object.__setattr__(self, "pue", _positive_number("pue", self.pue))
        object.__setattr__(
            self,
            "power_sampling_interval",
            _positive_number("power_sampling_interval", self.power_sampling_interval),
        )
        object.__setattr__(
            self,
            "intensity_sampling_interval",
            _positive_number(
                "intensity_sampling_interval", self.intensity_sampling_interval
            ),
        )
        object.__setattr__(
            self, "intensity_method", _coerce_intensity_method(self.intensity_method)
        )

        if self.static_carbon_intensity_g_per_kwh is not None:
            object.__setattr__(
                self,
                "static_carbon_intensity_g_per_kwh",
                _positive_number(
                    "static_carbon_intensity_g_per_kwh",
                    self.static_carbon_intensity_g_per_kwh,
                ),
            )

        if self.api_keys is None:
            api_keys: dict[str, str] = {}
        elif isinstance(self.api_keys, dict):
            api_keys = {
                _normalize_provider_name(str(key)): str(value)
                for key, value in self.api_keys.items()
            }
        else:
            raise ValueError("api_keys must be a dict when provided")
        object.__setattr__(self, "api_keys", api_keys)

        if self.forecast_provider_name is not None:
            object.__setattr__(
                self,
                "forecast_provider_name",
                _normalize_provider_name(self.forecast_provider_name),
            )

        if self.total_units is not None:
            object.__setattr__(
                self,
                "total_units",
                _positive_int("total_units", self.total_units),
            )
        if self.total_duration_s is not None:
            object.__setattr__(
                self,
                "total_duration_s",
                _positive_number("total_duration_s", self.total_duration_s),
            )
        if self.predict_after_units is not None:
            object.__setattr__(
                self,
                "predict_after_units",
                _nonnegative_int("predict_after_units", self.predict_after_units),
            )
        if self.predict_after_seconds is not None:
            object.__setattr__(
                self,
                "predict_after_seconds",
                _nonnegative_number(
                    "predict_after_seconds", self.predict_after_seconds
                ),
            )
        if self.predict_interval_s is not None:
            if isinstance(self.predict_interval_s, bool):
                raise ValueError("predict_interval_s must be a number")
            try:
                object.__setattr__(
                    self, "predict_interval_s", float(self.predict_interval_s)
                )
            except (TypeError, ValueError) as exc:
                raise ValueError("predict_interval_s must be a number") from exc
        if self.unit_name is not None:
            unit_name = str(self.unit_name).strip()
            if not unit_name:
                raise ValueError("unit_name must be a non-empty string")
            object.__setattr__(self, "unit_name", unit_name)

        if self.total_units is not None and self.total_duration_s is not None:
            raise ValueError("total_units and total_duration_s are mutually exclusive")
        if self.unit_name is not None and self.total_units is None:
            raise ValueError("unit_name requires total_units")
        if self.predict_after_units is not None and self.total_units is None:
            raise ValueError("predict_after_units requires total_units")

    @classmethod
    def from_mapping(cls, values: dict[str, Any]) -> "RuntimeOptions":
        values = dict(values)
        aliases = {
            "total_duration": "total_duration_s",
            "predict_after_n_units": "predict_after_units",
            "predict_after_n_secounds": "predict_after_seconds",
            "predict_interval": "predict_interval_s",
        }
        for old_key, new_key in aliases.items():
            if old_key in values and new_key not in values:
                values[new_key] = values[old_key]
        option_fields = {field_.name for field_ in fields(cls)}
        return cls(
            **{key: value for key, value in values.items() if key in option_fields}
        )


class ManualRuntimeControls:
    def __init__(self, observer: ManualObserverThread) -> None:
        self._observer = observer
        self._active = False
        self._finished = False

    def epoch_start(self) -> None:
        if self._finished:
            raise RuntimeError("Cannot start an epoch after finish()")
        if self._active:
            raise RuntimeError("Cannot start a new epoch while another epoch is active")
        self._observer.manual_start()
        self._active = True

    def epoch_end(self) -> None:
        if self._finished:
            raise RuntimeError("Cannot end an epoch after finish()")
        if not self._active:
            raise RuntimeError("epoch_end() called before epoch_start()")
        self._observer.manual_end()
        self._active = False

    def mark_finished(self) -> None:
        self._finished = True


@dataclass
class RuntimeBundle:
    options: RuntimeOptions
    metadata: SessionMetadata
    log_file_path: Path
    observer_thread: ObserverThread
    provider_threads: list[DataProviderThread[Any]]
    aggregator_thread: AggregatorThread
    reporter_threads: list[Thread]
    aggregation_queue: queue.Queue[TrackerEvent]
    terminal_queue: queue.Queue[TrackerEvent]
    logger_queue: queue.Queue[TrackerEvent]
    event_sink: list[queue.Queue[TrackerEvent]]
    manual_controls: ManualRuntimeControls | None = None
    tui_queue: queue.Queue[TrackerEvent] | None = None

    @property
    def threads(self) -> list[Thread]:
        return [
            self.observer_thread,
            *self.provider_threads,
            self.aggregator_thread,
            *self.reporter_threads,
        ]


def _setup_logging(
    options: RuntimeOptions, event_sink: list[queue.Queue[TrackerEvent]]
) -> None:
    logger = logging.getLogger("carbontracker")
    logger.setLevel(options.log_level.value.upper())
    logger.propagate = False
    logger.handlers.clear()

    queue_handler = EventQueueLogHandler(event_sink)
    queue_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(queue_handler)


def _config_summary(options: RuntimeOptions) -> dict[str, Any]:
    return {
        "components": [component.value for component in options.components],
        "pue": options.pue,
        "power_sampling_interval": options.power_sampling_interval,
        "intensity_method": options.intensity_method.value,
        "intensity_sampling_interval": options.intensity_sampling_interval,
        "forecast_provider_name": options.forecast_provider_name,
        "auto_detect_location": options.auto_detect_location,
        "total_units": options.total_units,
        "unit_name": options.unit_name,
        "total_duration_s": options.total_duration_s,
        "predict_after_units": options.predict_after_units,
        "predict_after_seconds": options.predict_after_seconds,
        "predict_interval_s": options.predict_interval_s,
    }


def _build_prediction_engine(options: RuntimeOptions) -> PredictionEngine | None:
    if options.total_units is None and options.total_duration_s is None:
        return None
    return PredictionEngine(
        total_units=options.total_units,
        unit_name=options.unit_name,
        total_duration_s=options.total_duration_s,
        predict_after_seconds=options.predict_after_seconds,
        predict_after_units=options.predict_after_units,
        predict_interval_s=options.predict_interval_s,
    )


def _build_shared_runtime(
    options: RuntimeOptions,
    observer_thread: ObserverThread,
    provider_threads: list[DataProviderThread[Any]],
    aggregation_queue: queue.Queue[TrackerEvent],
    terminal_queue: queue.Queue[TrackerEvent],
    logger_queue: queue.Queue[TrackerEvent],
    event_sink: list[queue.Queue[TrackerEvent]],
    command: Sequence[str] | None = None,
    trace_id: str | None = None,
    manual_controls: ManualRuntimeControls | None = None,
    persist_process_output: bool = False,
    jsonl_path: str | Path | None = None,
) -> RuntimeBundle:
    file_writer = FileWriterThread(
        log_dir=options.log_dir,
        run_name=options.run_name,
        event_queue=logger_queue,
        persist_process_output=persist_process_output,
        log_file_path=jsonl_path,
    )
    metadata = SessionMetadata(
        project_name=options.project_name,
        run_name=options.run_name,
        log_dir=options.log_dir,
        log_file_path=str(file_writer.log_file_path),
        command=tuple(command) if command is not None else None,
        trace_id=trace_id,
        config_summary=_config_summary(options),
    )
    profiler = SpanPowerProfiler()
    aggregator_thread = AggregatorThread(
        session_stats_interval_s=options.session_stat_interval_s,
        aggregation_queue=aggregation_queue,
        event_sink=event_sink,
        profiler=profiler,
        session_metadata=metadata,
        prediction_engine=_build_prediction_engine(options),
    )
    reporter_threads: list[Thread] = [
        TerminalOutputThread(log_level=options.log_level, event_queue=terminal_queue),
        file_writer,
    ]
    started_event = StartedSession(
        timestamp=datetime.now(),
        project_name=metadata.project_name,
        run_name=metadata.run_name,
        log_dir=metadata.log_dir,
        log_file_path=metadata.log_file_path,
        command=metadata.command,
        trace_id=metadata.trace_id,
        config_summary=metadata.config_summary,
    )
    for sink in event_sink:
        sink.put(started_event)

    return RuntimeBundle(
        options=options,
        metadata=metadata,
        log_file_path=file_writer.log_file_path,
        observer_thread=observer_thread,
        provider_threads=provider_threads,
        aggregator_thread=aggregator_thread,
        reporter_threads=reporter_threads,
        aggregation_queue=aggregation_queue,
        terminal_queue=terminal_queue,
        logger_queue=logger_queue,
        event_sink=event_sink,
        manual_controls=manual_controls,
        tui_queue=next(
            (
                sink
                for sink in event_sink
                if sink not in (terminal_queue, logger_queue)
            ),
            None,
        ),
    )


def _build_providers(
    options: RuntimeOptions,
    aggregation_queue: queue.Queue[TrackerEvent],
) -> tuple[list[DataProviderThread[Any]], list[Event]]:
    provider_threads: list[DataProviderThread[Any]] = []
    provider_trigger_events: list[Event] = []

    power_trigger = Event()
    provider_trigger_events.append(power_trigger)
    provider_threads.append(
        create_power_thread(
            config=options,
            aggregation_queue=aggregation_queue,
            notify_event=power_trigger,
        )
    )

    intensity_trigger = Event()
    provider_trigger_events.append(intensity_trigger)
    intensity_thread, intensity_resolution = create_intensity_thread(
        config=options,
        aggregation_queue=aggregation_queue,
        notify_event=intensity_trigger,
    )
    provider_threads.append(intensity_thread)

    forecast_provider_name = options.forecast_provider_name
    if forecast_provider_name is None:
        forecast_provider_name = (
            "electricity_maps"
            if intensity_resolution.provider_name == "electricity_maps"
            else "static"
        )

    forecast_api_key = (
        options.api_keys.get(forecast_provider_name) if forecast_provider_name else None
    )
    provider_threads.append(
        create_intensity_forecast_thread(
            location=intensity_resolution.location,
            aggregation_queue=aggregation_queue,
            current_intensity=intensity_resolution.static_intensity,
            provider_name=forecast_provider_name,
            api_key=forecast_api_key,
            forecast_length_hours=24,
            forecast_interval_hours=1,
            sample_interval=3600,
        )
    )

    return provider_threads, provider_trigger_events


def _runtime_parts(
    options: RuntimeOptions,
    enable_tui_sink: bool = False,
) -> tuple[
    queue.Queue[TrackerEvent],
    queue.Queue[TrackerEvent],
    queue.Queue[TrackerEvent],
    list[queue.Queue[TrackerEvent]],
    list[DataProviderThread[Any]],
    list[Event],
]:
    aggregation_queue: queue.Queue[TrackerEvent] = queue.Queue()
    terminal_queue: queue.Queue[TrackerEvent] = queue.Queue()
    logger_queue: queue.Queue[TrackerEvent] = queue.Queue()
    event_sink = [terminal_queue, logger_queue]
    if enable_tui_sink:
        event_sink.append(queue.Queue())

    _setup_logging(options, event_sink)
    provider_threads, provider_trigger_events = _build_providers(
        options, aggregation_queue
    )

    return (
        aggregation_queue,
        terminal_queue,
        logger_queue,
        event_sink,
        provider_threads,
        provider_trigger_events,
    )


def build_manual_runtime(
    options: RuntimeOptions,
    extra_event_sinks: list[queue.Queue[TrackerEvent]] | None = None,
) -> RuntimeBundle:
    (
        aggregation_queue,
        terminal_queue,
        logger_queue,
        event_sink,
        provider_threads,
        provider_trigger_events,
    ) = _runtime_parts(options)
    if extra_event_sinks:
        event_sink.extend(extra_event_sinks)

    trace_id = str(uuid.uuid4())
    observer_thread = ManualObserverThread(
        aggregation_queue=aggregation_queue,
        event_sink=event_sink,
        notify_events=provider_trigger_events,
        trace_id=trace_id,
    )
    manual_controls = ManualRuntimeControls(observer_thread)

    return _build_shared_runtime(
        options=options,
        observer_thread=observer_thread,
        provider_threads=provider_threads,
        aggregation_queue=aggregation_queue,
        terminal_queue=terminal_queue,
        logger_queue=logger_queue,
        event_sink=event_sink,
        trace_id=trace_id,
        manual_controls=manual_controls,
    )


def build_subprocess_runtime(
    command: Sequence[str],
    options: RuntimeOptions,
    capture_output_events: bool = False,
    enable_tui_sink: bool = False,
    persist_process_output: bool = False,
    jsonl_path: str | Path | None = None,
    extra_event_sinks: list[queue.Queue[TrackerEvent]] | None = None,
) -> RuntimeBundle:
    resolved_command = [str(part) for part in command]
    if not resolved_command or not any(part.strip() for part in resolved_command):
        raise ValueError("CLI command must be non-empty")

    (
        aggregation_queue,
        terminal_queue,
        logger_queue,
        event_sink,
        provider_threads,
        provider_trigger_events,
    ) = _runtime_parts(options, enable_tui_sink=enable_tui_sink)
    if extra_event_sinks:
        event_sink.extend(extra_event_sinks)

    trace_id = str(uuid.uuid4())
    observer_thread = SubprocessObserverThread(
        command=resolved_command,
        aggregation_queue=aggregation_queue,
        event_sink=event_sink,
        notify_events=provider_trigger_events,
        trace_id=trace_id,
        capture_output_events=capture_output_events,
    )

    return _build_shared_runtime(
        options=options,
        observer_thread=observer_thread,
        provider_threads=provider_threads,
        aggregation_queue=aggregation_queue,
        terminal_queue=terminal_queue,
        logger_queue=logger_queue,
        event_sink=event_sink,
        command=resolved_command,
        trace_id=trace_id,
        persist_process_output=persist_process_output,
        jsonl_path=jsonl_path,
    )
