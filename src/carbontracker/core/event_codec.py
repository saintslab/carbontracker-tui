from __future__ import annotations

import dataclasses
import json
from datetime import datetime
from enum import Enum
from typing import Any, Callable

from pydantic import BaseModel

from carbontracker.config.location_config import location_from_config, location_to_config
from carbontracker.core.events import (
    DiagnosticEvent,
    FinishedSession,
    GuardEvent,
    LogSeverity,
    MeasurementEvent,
    ProcessExitedEvent,
    ProcessOutputEvent,
    ProcessStartedEvent,
    SessionCurrentStatsEvent,
    SessionMetadata,
    SpanProfileEvent,
    SpanStart,
    SpanStop,
    StartedSession,
    TrackerEvent,
    PredictionEvent,
)
from carbontracker.core.execution_guard import GuardVerdict
from carbontracker.core.external import ExternalAccounting, ExternalUsage
from carbontracker.core.prediction import PredictionResult
from carbontracker.core.profiling import (
    DeviceSpanProfile,
    PowerDomain,
    PowerSample,
    PowerScope,
    SpanProfile,
)
from carbontracker.core.stats import SessionFinalStats, SessionStatsData, SpanStats
from carbontracker.core.types import (
    BreachAction,
    CloudRegion,
    CountryCode,
    ElectricityMapsDataCenter,
    ElectricityMapsGridZone,
    ElectricityMapsZone,
    GeoLocation,
    Location,
)
from carbontracker.providers.carbon_intensity.intensity_provider import (
    IntensityMeasurementData,
)
from carbontracker.providers.carbon_intensity_forecast.forecast_provider import (
    ForecastPoint,
    IntensityForecastData,
)
from carbontracker.providers.power.power_provider import PowerMeasurementData


class EventDecodeError(ValueError):
    pass


def _datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def _plain(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(
        value,
        (
            GeoLocation,
            CloudRegion,
            ElectricityMapsZone,
            ElectricityMapsDataCenter,
            ElectricityMapsGridZone,
            CountryCode,
        ),
    ):
        return location_to_config(value)
    if isinstance(value, BaseModel):
        return _plain(value.model_dump())
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {field.name: _plain(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    return value


def _ordered_payload(event_type: str, fields: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {"__type__": event_type}
    for key, value in fields:
        payload[key] = _plain(value)
    return payload


def _metadata_fields(metadata: SessionMetadata) -> list[tuple[str, Any]]:
    return [
        ("project_name", metadata.project_name),
        ("run_name", metadata.run_name),
        ("log_dir", metadata.log_dir),
        ("log_file_path", metadata.log_file_path),
        ("command", metadata.command),
        ("trace_id", metadata.trace_id),
        ("config_summary", metadata.config_summary),
    ]


def event_to_dict(event: TrackerEvent) -> dict[str, Any]:
    if isinstance(event, StartedSession):
        return _ordered_payload(
            "StartedSession",
            [("timestamp", event.timestamp), *_metadata_fields(event.metadata)],
        )
    if isinstance(event, FinishedSession):
        return _ordered_payload(
            "FinishedSession",
            [
                ("timestamp", event.timestamp),
                *_metadata_fields(event.metadata),
                ("stats", event.stats),
            ],
        )
    if isinstance(event, ProcessStartedEvent):
        return _ordered_payload(
            "ProcessStartedEvent",
            [
                ("timestamp", event.timestamp),
                ("trace_id", event.trace_id),
                ("command", event.command),
                ("pid", event.pid),
            ],
        )
    if isinstance(event, ProcessExitedEvent):
        return _ordered_payload(
            "ProcessExitedEvent",
            [
                ("timestamp", event.timestamp),
                ("trace_id", event.trace_id),
                ("return_code", event.return_code),
                ("interrupted", event.interrupted),
            ],
        )
    if isinstance(event, ProcessOutputEvent):
        return _ordered_payload(
            "ProcessOutputEvent",
            [
                ("timestamp", event.timestamp),
                ("trace_id", event.trace_id),
                ("stream", event.stream),
                ("line", event.line),
            ],
        )
    if isinstance(event, SpanStart):
        return _ordered_payload(
            "SpanStart",
            [
                ("started_at", event.started_at),
                ("trace_id", event.trace_id),
                ("span_id", event.span_id),
                ("parent_span_id", event.parent_span_id),
            ],
        )
    if isinstance(event, SpanStop):
        return _ordered_payload(
            "SpanStop",
            [
                ("ended_at", event.ended_at),
                ("trace_id", event.trace_id),
                ("span_id", event.span_id),
                ("parent_span_id", event.parent_span_id),
                ("external_usage", event.external_usage),
            ],
        )
    if isinstance(event, SpanProfileEvent):
        return _ordered_payload(
            "SpanProfileEvent",
            [
                ("created_at", event.created_at),
                ("span_id", event.span_id),
                ("parent_span_id", event.parent_span_id),
                ("started_at", event.started_at),
                ("ended_at", event.ended_at),
                ("stats", event.stats),
                ("external_accounting", event.external_accounting),
                ("profile", event.profile),
            ],
        )
    if isinstance(event, SessionCurrentStatsEvent):
        return _ordered_payload(
            "SessionCurrentStatsEvent",
            [("timestamp", event.timestamp), ("stats", event.stats)],
        )
    if isinstance(event, PredictionEvent):
        return _ordered_payload(
            "PredictionEvent",
            [("created_at", event.created_at), ("result", event.result)],
        )
    if isinstance(event, GuardEvent):
        return _ordered_payload(
            "GuardEvent",
            [
                ("created_at", event.created_at),
                ("verdict", event.verdict),
                ("prediction", event.prediction),
            ],
        )
    if isinstance(event, DiagnosticEvent):
        return _ordered_payload(
            "DiagnosticEvent",
            [
                ("timestamp", event.timestamp),
                ("logger_name", event.logger_name),
                ("severity", event.severity),
                ("message", event.message),
            ],
        )
    if isinstance(event, MeasurementEvent):
        return _ordered_payload(
            "MeasurementEvent",
            [
                ("timestamp", event.timestamp),
                ("provider_name", event.provider_name),
                ("data", event.data),
            ],
        )
    raise TypeError(f"Unsupported event type: {type(event).__name__}")


def event_to_json(event: TrackerEvent) -> str:
    return json.dumps(event_to_dict(event), separators=(",", ":"))


def _optional_location(payload: dict[str, Any] | None) -> Any:
    if payload is None:
        return None
    location = location_from_config(payload)
    return location if location is not None else payload


def _power_sample(payload: dict[str, Any]) -> PowerSample:
    return PowerSample(
        observed_at=_datetime(payload["observed_at"]),
        domain=PowerDomain(payload["domain"]),
        device_id=payload["device_id"],
        source=payload["source"],
        scope=PowerScope(payload.get("scope", PowerScope.DEVICE_TOTAL)),
        watts=payload.get("watts"),
        cumulative_energy_j=payload.get("cumulative_energy_j"),
        interval_energy_j=payload.get("interval_energy_j"),
        interval_start=_datetime(payload["interval_start"]) if payload.get("interval_start") else None,
        interval_end=_datetime(payload["interval_end"]) if payload.get("interval_end") else None,
        pid=payload.get("pid"),
        owner_id=payload.get("owner_id"),
        label=payload.get("label"),
    )


def _measurement_data(payload: dict[str, Any]) -> Any:
    if "samples" in payload:
        return PowerMeasurementData(
            timestamp=_datetime(payload["timestamp"]),
            samples=tuple(_power_sample(item) for item in payload["samples"]),
        )
    if "forecasts" in payload:
        return IntensityForecastData(
            timestamp=_datetime(payload["timestamp"]),
            location=_optional_location(payload.get("location")),
            forecasts=[
                ForecastPoint(
                    timestamp=_datetime(item["timestamp"]),
                    carbon_intensity=item["carbon_intensity"],
                )
                for item in payload["forecasts"]
            ],
        )
    if "carbon_intensity" in payload:
        return IntensityMeasurementData(
            timestamp=_datetime(payload["timestamp"]),
            location=_optional_location(payload.get("location")),
            carbon_intensity=payload["carbon_intensity"],
            is_prediction=payload["is_prediction"],
        )
    return payload


def _span_stats(payload: dict[str, Any] | None) -> SpanStats | None:
    return SpanStats(**payload) if payload is not None else None


def _external_usage(payload: dict[str, Any] | None) -> ExternalUsage | None:
    return ExternalUsage(**payload) if payload is not None else None


def _external_accounting(
    payload: dict[str, Any] | None,
) -> ExternalAccounting | None:
    return ExternalAccounting(**payload) if payload is not None else None


def _session_stats(payload: dict[str, Any]) -> SessionStatsData:
    return SessionStatsData(**payload)


def _final_stats(payload: dict[str, Any]) -> SessionFinalStats:
    return SessionFinalStats(**payload)


def _prediction_result(payload: dict[str, Any] | None) -> PredictionResult | None:
    return PredictionResult(**payload) if payload is not None else None


def _guard_verdict(payload: dict[str, Any]) -> GuardVerdict:
    data = dict(payload)
    data["action"] = BreachAction(data["action"])
    return GuardVerdict(**data)


def _span_profile(payload: dict[str, Any] | None) -> Any:
    if payload is None:
        return None
    if not {"span_id", "started_at", "ended_at", "devices"}.issubset(payload):
        return payload
    devices = {
        key: DeviceSpanProfile(
            domain=PowerDomain(value["domain"]),
            device_id=value["device_id"],
            gross_energy_j=value["gross_energy_j"],
            gross_emissions_g=value["gross_emissions_g"],
            avg_watt=value["avg_watt"],
            min_watt=value["min_watt"],
            max_watt=value["max_watt"],
            baseline_energy_j=value.get("baseline_energy_j", 0.0),
            baseline_emissions_g=value.get("baseline_emissions_g", 0.0),
        )
        for key, value in payload["devices"].items()
    }
    return SpanProfile(
        span_id=payload["span_id"],
        parent_span_id=payload.get("parent_span_id"),
        started_at=_datetime(payload["started_at"]),
        ended_at=_datetime(payload["ended_at"]),
        devices=devices,
        avg_intensity=payload["avg_intensity"],
        min_intensity=payload["min_intensity"],
        max_intensity=payload["max_intensity"],
        power_measurements_count=payload["power_measurements_count"],
        intensity_measurements_count=payload["intensity_measurements_count"],
        quality=payload.get("quality", {}),
    )


def _metadata(payload: dict[str, Any]) -> SessionMetadata:
    if isinstance(payload.get("metadata"), dict):
        payload = {**payload["metadata"], **{k: v for k, v in payload.items() if k != "metadata"}}
    return SessionMetadata(
        project_name=payload.get("project_name", "carbontracker"),
        run_name=payload.get("run_name", "carbontracker"),
        log_dir=payload.get("log_dir", "carbontracker_logs/"),
        log_file_path=payload.get("log_file_path", "carbontracker_logs/carbontracker_events.jsonl"),
        command=tuple(payload["command"]) if payload.get("command") is not None else None,
        trace_id=payload.get("trace_id"),
        config_summary=payload.get("config_summary"),
    )


def _required(payload: dict[str, Any], key: str) -> Any:
    try:
        return payload[key]
    except KeyError as exc:
        raise EventDecodeError(f"Missing required field: {key}") from exc


def event_from_dict(payload: dict[str, Any]) -> TrackerEvent:
    event_type = payload.get("__type__")
    if not event_type:
        raise EventDecodeError("Missing __type__")

    decoders: dict[str, Callable[[dict[str, Any]], TrackerEvent]] = {
        "StartedSession": lambda p: StartedSession(
            timestamp=_datetime(_required(p, "timestamp")),
            **dataclasses.asdict(_metadata(p)),
        ),
        "FinishedSession": lambda p: FinishedSession(
            timestamp=_datetime(_required(p, "timestamp")),
            **dataclasses.asdict(_metadata(p)),
            stats=_final_stats(_required(p, "stats")),
        ),
        "ProcessStartedEvent": lambda p: ProcessStartedEvent(
            timestamp=_datetime(_required(p, "timestamp")),
            command=tuple(_required(p, "command")),
            pid=_required(p, "pid"),
            trace_id=_required(p, "trace_id"),
        ),
        "ProcessExitedEvent": lambda p: ProcessExitedEvent(
            timestamp=_datetime(_required(p, "timestamp")),
            return_code=p.get("return_code"),
            interrupted=bool(_required(p, "interrupted")),
            trace_id=_required(p, "trace_id"),
        ),
        "ProcessOutputEvent": lambda p: ProcessOutputEvent(
            timestamp=_datetime(_required(p, "timestamp")),
            stream=_required(p, "stream"),
            line=_required(p, "line"),
            trace_id=_required(p, "trace_id"),
        ),
        "SpanStart": lambda p: SpanStart(
            started_at=_datetime(_required(p, "started_at")),
            span_id=_required(p, "span_id"),
            parent_span_id=p.get("parent_span_id"),
            trace_id=p.get("trace_id"),
        ),
        "SpanStop": lambda p: SpanStop(
            ended_at=_datetime(_required(p, "ended_at")),
            span_id=_required(p, "span_id"),
            parent_span_id=p.get("parent_span_id"),
            trace_id=p.get("trace_id"),
            external_usage=_external_usage(p.get("external_usage")),
        ),
        "SpanProfileEvent": lambda p: SpanProfileEvent(
            created_at=_datetime(_required(p, "created_at")),
            span_id=_required(p, "span_id"),
            parent_span_id=p.get("parent_span_id"),
            started_at=_datetime(_required(p, "started_at")),
            ended_at=_datetime(_required(p, "ended_at")),
            stats=_span_stats(p.get("stats")),
            external_accounting=_external_accounting(
                p.get("external_accounting")
            ),
            profile=_span_profile(p.get("profile")),
        ),
        "SessionCurrentStatsEvent": lambda p: SessionCurrentStatsEvent(
            timestamp=_datetime(_required(p, "timestamp")),
            stats=_session_stats(_required(p, "stats")),
        ),
        "PredictionEvent": lambda p: PredictionEvent(
            created_at=_datetime(_required(p, "created_at")),
            result=_prediction_result(p.get("result")),
        ),
        "GuardEvent": lambda p: GuardEvent(
            created_at=_datetime(_required(p, "created_at")),
            verdict=_guard_verdict(_required(p, "verdict")),
            prediction=_prediction_result(p.get("prediction")),
        ),
        "DiagnosticEvent": lambda p: DiagnosticEvent(
            timestamp=_datetime(_required(p, "timestamp")),
            logger_name=_required(p, "logger_name"),
            severity=LogSeverity(_required(p, "severity")),
            message=_required(p, "message"),
        ),
        "MeasurementEvent": lambda p: MeasurementEvent(
            timestamp=_datetime(_required(p, "timestamp")),
            provider_name=_required(p, "provider_name"),
            data=_measurement_data(_required(p, "data")),
        ),
    }
    try:
        decoder = decoders[event_type]
    except KeyError as exc:
        raise EventDecodeError(f"Unsupported event type: {event_type}") from exc
    return decoder(payload)


def event_from_json(line: str) -> TrackerEvent:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError as exc:
        raise EventDecodeError(f"Malformed JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise EventDecodeError("Event JSON must decode to an object")
    return event_from_dict(payload)


def diagnostic_from_decode_error(line_number: int, error: Exception) -> DiagnosticEvent:
    return DiagnosticEvent(
        timestamp=datetime.now(),
        severity=LogSeverity.WARNING,
        logger_name="carbontracker.event_codec",
        message=f"Could not decode JSONL event at line {line_number}: {error}",
    )


def events_from_jsonl_lines(lines: Any) -> Any:
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            yield event_from_json(stripped)
        except EventDecodeError as exc:
            yield diagnostic_from_decode_error(line_number, exc)
