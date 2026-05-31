from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from carbontracker.core.event_codec import event_to_dict
from carbontracker.core.events import (
    DiagnosticEvent,
    FinishedSession,
    GuardEvent,
    MeasurementEvent,
    PredictionEvent,
    ProcessExitedEvent,
    ProcessOutputEvent,
    ProcessStartedEvent,
    SessionCurrentStatsEvent,
    SpanProfileEvent,
    SpanStart,
    SpanStop,
    StartedSession,
    TrackerEvent,
)
from carbontracker.core.profiling import PowerSample
from carbontracker.providers.carbon_intensity.intensity_provider import (
    IntensityMeasurementData,
)
from carbontracker.providers.carbon_intensity_forecast.forecast_provider import (
    IntensityForecastData,
)
from carbontracker.providers.power.power_provider import PowerMeasurementData


@dataclass(frozen=True)
class EventRow:
    kind: str
    timestamp: datetime
    payload: dict[str, Any]
    event: TrackerEvent


@dataclass
class DeviceState:
    device_id: str
    source: str = "unknown"
    label: str | None = None
    watts: float = 0.0
    domain: str | None = None
    samples_count: int = 0
    watts_total: float = 0.0
    watts_min: float | None = None
    watts_max: float | None = None
    watt_samples: list[tuple[datetime, float]] = field(default_factory=list)
    interval_energy_kwh: float = 0.0
    cumulative_energy_samples_kwh: list[float] = field(default_factory=list)

    @property
    def watts_avg(self) -> float | None:
        if self.samples_count == 0:
            return None
        return self.watts_total / self.samples_count

    @property
    def total_energy_kwh(self) -> float:
        if self.interval_energy_kwh > 0:
            return self.interval_energy_kwh
        if len(self.cumulative_energy_samples_kwh) >= 2:
            return max(
                self.cumulative_energy_samples_kwh[-1]
                - self.cumulative_energy_samples_kwh[0],
                0.0,
            )
        samples = sorted(self.watt_samples, key=lambda item: item[0])
        if len(samples) < 2:
            return 0.0
        energy_wh = 0.0
        for (start, watts), (end, _) in zip(samples, samples[1:]):
            duration_h = max((end - start).total_seconds(), 0.0) / 3600
            energy_wh += watts * duration_h
        return energy_wh / 1000

    def add_power_sample(self, sample: PowerSample) -> None:
        self.source = sample.source or self.source
        self.label = sample.label or self.label
        self.domain = sample.domain.value
        if sample.watts is not None:
            self.watts = sample.watts
            self.samples_count += 1
            self.watts_total += sample.watts
            self.watts_min = (
                sample.watts
                if self.watts_min is None
                else min(self.watts_min, sample.watts)
            )
            self.watts_max = (
                sample.watts
                if self.watts_max is None
                else max(self.watts_max, sample.watts)
            )
            self.watt_samples.append((sample.observed_at, sample.watts))
        if sample.interval_energy_j is not None:
            self.interval_energy_kwh += sample.interval_energy_j / 3_600_000
        if sample.cumulative_energy_j is not None:
            self.cumulative_energy_samples_kwh.append(
                sample.cumulative_energy_j / 3_600_000
            )


@dataclass
class SpanState:
    span_id: str
    parent_span_id: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_s: float | None = None
    power_usage_kwh: float | None = None
    emissions_g: float | None = None
    reliable: bool | None = None
    status: str = "running"


@dataclass
class WatchState:
    project_name: str = "carbontracker"
    run_name: str = "unknown"
    command: tuple[str, ...] = ()
    log_dir: str | None = None
    log_file_path: str | None = None
    trace_id: str | None = None
    status: str = "starting"
    return_code: int | None = None
    started_at: datetime | None = None
    latest_at: datetime | None = None
    current_wattage: float | None = None
    current_intensity: float | None = None
    total_power_usage_kwh: float = 0.0
    total_emissions_g: float = 0.0
    final_duration_s: float | None = None
    projected_duration_s: float | None = None
    prediction_run_duration_s: float | None = None
    prediction_completed_units: int | None = None
    prediction_total_units: int | None = None
    projected_energy_kwh: float | None = None
    projected_emissions_g: float | None = None
    last_prediction_at: datetime | None = None
    last_forecast_at: datetime | None = None
    forecast_points: list[tuple[datetime, float]] = field(default_factory=list)
    forecast_location: Any | None = None
    devices: dict[str, DeviceState] = field(default_factory=dict)
    spans: dict[str, SpanState] = field(default_factory=dict)
    events: list[EventRow] = field(default_factory=list)
    diagnostics: list[DiagnosticEvent] = field(default_factory=list)

    @property
    def runtime_s(self) -> float:
        if self.final_duration_s is not None:
            return self.final_duration_s
        if self.started_at is None or self.latest_at is None:
            return 0.0
        return max((self.latest_at - self.started_at).total_seconds(), 0.0)


def event_timestamp(event: TrackerEvent) -> datetime:
    if isinstance(event, (StartedSession, FinishedSession)):
        return event.timestamp
    if isinstance(event, (ProcessStartedEvent, ProcessExitedEvent, ProcessOutputEvent)):
        return event.timestamp
    if isinstance(event, SpanStart):
        return event.started_at
    if isinstance(event, SpanStop):
        return event.ended_at
    if isinstance(event, SpanProfileEvent):
        return event.created_at
    if isinstance(event, SessionCurrentStatsEvent):
        return event.timestamp
    if isinstance(event, PredictionEvent):
        return event.created_at
    if isinstance(event, GuardEvent):
        return event.created_at
    if isinstance(event, DiagnosticEvent):
        return event.timestamp
    if isinstance(event, MeasurementEvent):
        return event.timestamp
    return datetime.now()


def build_watch_state(events: list[TrackerEvent] | tuple[TrackerEvent, ...]) -> WatchState:
    state = WatchState()
    for event in events:
        apply_event(state, event)
    return state


def apply_event(state: WatchState, event: TrackerEvent) -> None:
    timestamp = event_timestamp(event)
    state.latest_at = timestamp
    state.events.append(
        EventRow(
            kind=type(event).__name__,
            timestamp=timestamp,
            payload=event_to_dict(event),
            event=event,
        )
    )

    if isinstance(event, DiagnosticEvent):
        state.diagnostics.append(event)
    elif isinstance(event, StartedSession):
        state.started_at = event.timestamp
        state.project_name = event.project_name
        state.run_name = event.run_name
        state.command = event.command or ()
        state.log_dir = event.log_dir
        state.log_file_path = event.log_file_path
        state.trace_id = event.trace_id
        state.status = "starting"
    elif isinstance(event, ProcessStartedEvent):
        state.status = "running"
        if not state.command:
            state.command = event.command
        state.trace_id = event.trace_id
    elif isinstance(event, MeasurementEvent):
        _apply_measurement(state, event)
    elif isinstance(event, SessionCurrentStatsEvent):
        stats = event.stats
        state.current_wattage = stats.current_wattage
        state.current_intensity = stats.current_intensity
        state.total_power_usage_kwh = stats.total_power_usage_kwh
        state.total_emissions_g = stats.total_emissions_g
        for device_id, watts in stats.power_usage_pr_device.items():
            device = state.devices.get(device_id, DeviceState(device_id=device_id))
            device.watts = watts
            state.devices[device_id] = device
    elif isinstance(event, SpanStart):
        span = state.spans.get(event.span_id, SpanState(span_id=event.span_id))
        span.parent_span_id = event.parent_span_id
        span.started_at = event.started_at
        span.status = "running"
        state.spans[event.span_id] = span
    elif isinstance(event, SpanStop):
        span = state.spans.get(event.span_id, SpanState(span_id=event.span_id))
        span.parent_span_id = event.parent_span_id
        span.ended_at = event.ended_at
        span.status = "profiling"
        state.spans[event.span_id] = span
    elif isinstance(event, SpanProfileEvent):
        span = state.spans.get(event.span_id, SpanState(span_id=event.span_id))
        span.parent_span_id = event.parent_span_id
        span.started_at = event.started_at
        span.ended_at = event.ended_at
        span.duration_s = (event.ended_at - event.started_at).total_seconds()
        if event.stats is not None:
            span.power_usage_kwh = event.stats.power_usage_kwh
            span.emissions_g = event.stats.emissions_g
        quality = getattr(event.profile, "quality", None)
        if isinstance(quality, dict) and isinstance(quality.get("reliable"), bool):
            span.reliable = quality["reliable"]
        span.status = "finished"
        state.spans[event.span_id] = span
    elif isinstance(event, PredictionEvent) and event.result is not None:
        result = event.result
        state.last_prediction_at = event.created_at
        state.projected_duration_s = result.estimated_duration_left_s
        state.prediction_run_duration_s = result.run_duration_s
        state.prediction_completed_units = result.completed_units
        state.prediction_total_units = result.total_units
        state.projected_energy_kwh = result.projected_total_energy_kwh
        state.projected_emissions_g = result.projected_total_emissions_g
    elif isinstance(event, ProcessExitedEvent):
        state.return_code = event.return_code
        state.status = "finishing"
    elif isinstance(event, FinishedSession):
        state.status = "finished"
        state.project_name = event.project_name
        state.run_name = event.run_name
        state.total_power_usage_kwh = event.stats.total_power_usage_kwh
        state.total_emissions_g = event.stats.total_emissions_g
        state.final_duration_s = event.stats.duration_s
        state.current_wattage = 0.0
        for device in state.devices.values():
            device.watts = 0.0


def _apply_measurement(state: WatchState, event: MeasurementEvent[Any]) -> None:
    data = event.data
    if isinstance(data, PowerMeasurementData):
        for sample in data.samples:
            device = state.devices.get(
                sample.device_id,
                DeviceState(device_id=sample.device_id),
            )
            device.add_power_sample(sample)
            state.devices[sample.device_id] = device
    elif isinstance(data, IntensityMeasurementData):
        state.current_intensity = data.carbon_intensity
    elif isinstance(data, IntensityForecastData):
        state.last_forecast_at = event.timestamp
        state.forecast_location = data.location
        state.forecast_points = [
            (point.timestamp, point.carbon_intensity) for point in data.forecasts
        ]
