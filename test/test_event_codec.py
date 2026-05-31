import json
import queue
from datetime import datetime

from carbontracker.core.event_codec import (
    event_from_json,
    event_to_dict,
    event_to_json,
    events_from_jsonl_lines,
)
from carbontracker.core.events import (
    DiagnosticEvent,
    FinishedSession,
    LogSeverity,
    MeasurementEvent,
    ProcessOutputEvent,
    ProcessStartedEvent,
    SessionMetadata,
    SpanProfileEvent,
    SpanStop,
    StartedSession,
)
from carbontracker.core.external import ExternalAccounting, ExternalUsage
from carbontracker.core.profiling import PowerDomain, PowerSample, SpanProfile
from carbontracker.core.stats import SessionFinalStats, SpanStats
from carbontracker.providers.power.power_provider import PowerMeasurementData
from carbontracker.reporters.file_logger import FileWriterThread


def metadata() -> SessionMetadata:
    return SessionMetadata(
        project_name="project-a",
        run_name="run-a",
        log_dir="logs",
        log_file_path="logs/run-a_events.jsonl",
        command=("python", "train.py"),
        trace_id="trace-a",
        config_summary={"components": ["cpu"], "pue": 1.1},
    )


def session_fields() -> dict:
    meta = metadata()
    return {
        "project_name": meta.project_name,
        "run_name": meta.run_name,
        "log_dir": meta.log_dir,
        "log_file_path": meta.log_file_path,
        "command": meta.command,
        "trace_id": meta.trace_id,
        "config_summary": meta.config_summary,
    }


def test_event_json_starts_with_type_and_identity_fields():
    event = StartedSession(timestamp=datetime(2026, 1, 1, 12), **session_fields())

    encoded = event_to_json(event)
    keys = list(json.loads(encoded).keys())

    assert keys[:4] == ["__type__", "timestamp", "project_name", "run_name"]


def test_round_trips_session_process_measurement_and_finished_events():
    timestamp = datetime(2026, 1, 1, 12)
    power_sample = PowerSample(
        observed_at=timestamp,
        domain=PowerDomain.CPU,
        device_id="cpu:0",
        source="test",
        watts=42.0,
    )
    events = [
        StartedSession(timestamp=timestamp, **session_fields()),
        ProcessStartedEvent(
            timestamp=timestamp,
            command=("python", "train.py"),
            pid=1234,
            trace_id="trace-a",
        ),
        MeasurementEvent(
            provider_name="power",
            timestamp=timestamp,
            data=PowerMeasurementData(timestamp=timestamp, samples=(power_sample,)),
        ),
        FinishedSession(
            timestamp=timestamp,
            **session_fields(),
            stats=SessionFinalStats(
                total_emissions_g=1.0,
                total_power_usage_kwh=2.0,
                duration_s=3.0,
                completed_spans_count=4,
            ),
        ),
    ]

    for event in events:
        decoded = event_from_json(event_to_json(event))
        assert decoded == event


def test_replay_fixture_decodes_supported_events():
    with open("test/fixtures/replay_session_events.jsonl") as handle:
        decoded = list(events_from_jsonl_lines(handle))

    assert [type(event).__name__ for event in decoded] == [
        "StartedSession",
        "ProcessStartedEvent",
        "ProcessExitedEvent",
    ]


def test_malformed_jsonl_lines_become_diagnostic_events():
    decoded = list(events_from_jsonl_lines(["not-json\n", '{"ok": true}\n']))

    assert all(isinstance(event, DiagnosticEvent) for event in decoded)
    assert decoded[0].severity == LogSeverity.WARNING
    assert "line 1" in decoded[0].message


def test_file_writer_skips_process_output_by_default(tmp_path):
    event_queue = queue.Queue()
    writer = FileWriterThread(
        log_dir=str(tmp_path),
        run_name="run-a",
        event_queue=event_queue,
    )
    writer.start()
    event_queue.put(
        ProcessOutputEvent(
            timestamp=datetime(2026, 1, 1, 12),
            stream="stdout",
            line="user output",
            trace_id="trace-a",
        )
    )
    event_queue.put(
        DiagnosticEvent(
            timestamp=datetime(2026, 1, 1, 12),
            severity=LogSeverity.WARNING,
            message="warning",
            logger_name="test",
        )
    )
    writer.stop()
    writer.join()

    lines = writer.log_file_path.read_text().splitlines()
    assert len(lines) == 1
    assert event_to_dict(event_from_json(lines[0]))["__type__"] == "DiagnosticEvent"


def test_file_writer_persists_process_output_when_enabled(tmp_path):
    event_queue = queue.Queue()
    writer = FileWriterThread(
        log_dir=str(tmp_path),
        run_name="run-a",
        event_queue=event_queue,
        persist_process_output=True,
    )
    writer.start()
    event_queue.put(
        ProcessOutputEvent(
            timestamp=datetime(2026, 1, 1, 12),
            stream="stdout",
            line="user output",
            trace_id="trace-a",
        )
    )
    writer.stop()
    writer.join()

    lines = writer.log_file_path.read_text().splitlines()
    assert len(lines) == 1
    assert event_to_dict(event_from_json(lines[0]))["__type__"] == "ProcessOutputEvent"


def test_external_usage_and_accounting_round_trip_through_json():
    timestamp = datetime(2026, 1, 1, 12)
    usage = ExternalUsage(
        energy_kwh=0.00012,
        carbon_intensity_g_per_kwh=65.0,
    )
    accounting = ExternalAccounting(
        energy_kwh=0.00012,
        emissions_g=0.0078,
        method="explicit_intensity",
    )
    events = [
        SpanStop(
            ended_at=timestamp,
            span_id="llm_call",
            parent_span_id="process",
            trace_id="trace-a",
            external_usage=usage,
        ),
        SpanProfileEvent(
            created_at=timestamp,
            span_id="llm_call",
            parent_span_id="process",
            started_at=timestamp,
            ended_at=timestamp,
            profile=SpanProfile(
                span_id="llm_call",
                parent_span_id="process",
                started_at=timestamp,
                ended_at=timestamp,
                devices={},
                avg_intensity=0.0,
                min_intensity=0.0,
                max_intensity=0.0,
                power_measurements_count=0,
                intensity_measurements_count=0,
            ),
            stats=SpanStats(
                avg_watt=0.0,
                min_watt=0.0,
                max_watt=0.0,
                avg_intensity=0.0,
                min_intensity=0.0,
                max_intensity=0.0,
                power_usage_pr_device={},
                emissions_g=0.0,
                power_usage_kwh=0.0,
                power_measurements_count=0,
                intensity_measurements_count=0,
            ),
            external_accounting=accounting,
        ),
    ]

    for event in events:
        assert event_from_json(event_to_json(event)) == event
