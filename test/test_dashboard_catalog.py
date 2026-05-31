from datetime import datetime, timedelta

import pytest

from carbontracker.dashboard.catalog import build_run_catalog, run_record_from_events
from carbontracker.core.event_codec import event_to_json
from carbontracker.core.events import (
    DiagnosticEvent,
    FinishedSession,
    LogSeverity,
    ProcessExitedEvent,
    SpanProfileEvent,
    StartedSession,
)
from carbontracker.core.external import ExternalAccounting
from carbontracker.core.stats import SessionFinalStats


def session_fields(run_name: str, *, timestamp: datetime) -> dict:
    return {
        "timestamp": timestamp,
        "project_name": "demo",
        "run_name": run_name,
        "log_dir": "logs",
        "log_file_path": f"logs/{run_name}_events.jsonl",
        "command": ("python", "train.py"),
        "trace_id": f"trace-{run_name}",
        "config_summary": {
            "components": ["cpu", "gpu"],
            "pue": 1.1,
            "power_sampling_interval": 1.0,
            "intensity_method": "static",
            "intensity_sampling_interval": 900.0,
            "total_units": 10,
            "unit_name": "request",
            "predict_after_units": 2,
        },
    }


def write_events(path, events) -> None:
    path.write_text("\n".join(event_to_json(event) for event in events) + "\n")


def test_catalog_derives_finished_run_with_external_accounting(tmp_path):
    t0 = datetime(2026, 1, 1, 12)
    path = tmp_path / "run-a_events.jsonl"
    write_events(
        path,
        [
            StartedSession(**session_fields("run-a", timestamp=t0)),
            SpanProfileEvent(
                created_at=t0 + timedelta(seconds=4),
                span_id="llm_call",
                parent_span_id=None,
                started_at=t0 + timedelta(seconds=1),
                ended_at=t0 + timedelta(seconds=3),
                profile={},
                external_accounting=ExternalAccounting(
                    energy_kwh=0.2,
                    emissions_g=10.0,
                    method="explicit_intensity",
                ),
            ),
            FinishedSession(
                **session_fields("run-a", timestamp=t0 + timedelta(seconds=30)),
                stats=SessionFinalStats(
                    total_power_usage_kwh=1.0,
                    total_emissions_g=20.0,
                    duration_s=30.0,
                    completed_spans_count=2,
                ),
            ),
        ],
    )

    record = build_run_catalog(tmp_path)[0]

    assert record.status == "finished"
    assert record.project_name == "demo"
    assert record.run_name == "run-a"
    assert record.local_power_usage_kwh == 1.0
    assert record.local_emissions_g == 20.0
    assert record.external_power_usage_kwh == 0.2
    assert record.external_emissions_g == 10.0
    assert record.power_usage_kwh == pytest.approx(1.2)
    assert record.emissions_g == pytest.approx(30.0)
    assert record.average_intensity_g_per_kwh == pytest.approx(25.0)
    assert record.external_accounting_methods == ("explicit_intensity",)
    assert record.components == ("cpu", "gpu")
    assert record.unit_emissions_g == pytest.approx(3.0)


def test_catalog_statuses_cover_warning_failed_running_and_incomplete(tmp_path):
    t0 = datetime(2026, 1, 1, 12)
    warning_path = tmp_path / "warning_events.jsonl"
    failed_path = tmp_path / "failed_events.jsonl"
    running_path = tmp_path / "running_events.jsonl"
    broken_path = tmp_path / "broken_events.jsonl"

    write_events(
        warning_path,
        [
            StartedSession(**session_fields("warning", timestamp=t0)),
            DiagnosticEvent(
                timestamp=t0 + timedelta(seconds=1),
                severity=LogSeverity.WARNING,
                logger_name="test",
                message="measurement gap",
            ),
            FinishedSession(
                **session_fields("warning", timestamp=t0 + timedelta(seconds=2)),
                stats=SessionFinalStats(
                    total_power_usage_kwh=0.1,
                    total_emissions_g=1.0,
                    duration_s=2.0,
                    completed_spans_count=1,
                ),
            ),
        ],
    )
    write_events(
        failed_path,
        [
            StartedSession(**session_fields("failed", timestamp=t0 + timedelta(minutes=1))),
            ProcessExitedEvent(
                timestamp=t0 + timedelta(minutes=1, seconds=2),
                return_code=1,
                interrupted=False,
                trace_id="trace-failed",
            ),
        ],
    )
    write_events(
        running_path,
        [StartedSession(**session_fields("running", timestamp=t0 + timedelta(minutes=2)))],
    )
    broken_path.write_text("not-json\n")

    records = {record.run_name: record for record in build_run_catalog(tmp_path)}

    assert records["warning"].status == "warning"
    assert records["warning"].diagnostics_count == 1
    assert records["failed"].status == "failed"
    assert records["failed"].return_code == 1
    assert records["running"].status == "running"
    assert records["broken"].status == "incomplete"
    assert records["broken"].diagnostics_count == 1


def test_catalog_sorts_newest_runs_first(tmp_path):
    t0 = datetime(2026, 1, 1, 12)
    older = tmp_path / "older_events.jsonl"
    newer = tmp_path / "newer_events.jsonl"
    write_events(older, [StartedSession(**session_fields("older", timestamp=t0))])
    write_events(
        newer,
        [StartedSession(**session_fields("newer", timestamp=t0 + timedelta(hours=1)))],
    )

    assert [record.run_name for record in build_run_catalog(tmp_path)] == [
        "newer",
        "older",
    ]


def test_run_record_from_events_handles_empty_event_list(tmp_path):
    record = run_record_from_events([], source_log_path=tmp_path / "empty_events.jsonl")

    assert record.run_name == "empty"
    assert record.status == "incomplete"
    assert record.event_count == 0
