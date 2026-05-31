from datetime import datetime, timedelta

from carbontracker.core.event_codec import event_to_json
from carbontracker.core.events import (
    DiagnosticEvent,
    FinishedSession,
    LogSeverity,
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
)
from carbontracker.core.prediction import PredictionResult
from carbontracker.core.profiling import PowerDomain, PowerSample, SpanProfile
from carbontracker.core.stats import SessionFinalStats, SessionStatsData, SpanStats
from carbontracker.providers.carbon_intensity_forecast.forecast_provider import (
    ForecastPoint,
    IntensityForecastData,
)
from carbontracker.providers.power.power_provider import PowerMeasurementData
from carbontracker.watch.jsonl import read_jsonl_events
from carbontracker.watch.reducer import build_watch_state


def test_running_sparse_events_build_partial_watch_state():
    t0 = datetime(2026, 1, 1, 12)
    state = build_watch_state(
        [
            StartedSession(
                timestamp=t0,
                project_name="demo",
                run_name="run-a",
                log_dir="logs",
                log_file_path="logs/run-a_events.jsonl",
                command=("python", "train.py"),
                trace_id="trace-a",
            ),
            ProcessStartedEvent(
                timestamp=t0 + timedelta(seconds=1),
                command=("python", "train.py"),
                pid=123,
                trace_id="trace-a",
            ),
        ]
    )

    assert state.project_name == "demo"
    assert state.run_name == "run-a"
    assert state.status == "running"
    assert state.runtime_s == 1


def test_finished_events_build_final_watch_state():
    t0 = datetime(2026, 1, 1, 12)
    power_sample = PowerSample(
        observed_at=t0 + timedelta(seconds=2),
        domain=PowerDomain.CPU,
        device_id="cpu:0",
        source="test",
        label="CPU",
        watts=42.0,
        interval_energy_j=84.0,
        interval_start=t0 + timedelta(seconds=1),
        interval_end=t0 + timedelta(seconds=2),
    )
    stats = SpanStats(
        avg_watt=42.0,
        min_watt=40.0,
        max_watt=44.0,
        avg_intensity=100.0,
        min_intensity=100.0,
        max_intensity=100.0,
        power_usage_pr_device={"cpu:0": 42.0},
        emissions_g=0.1,
        power_usage_kwh=0.001,
        power_measurements_count=1,
        intensity_measurements_count=1,
    )
    events = [
        StartedSession(
            timestamp=t0,
            project_name="demo",
            run_name="run-a",
            log_dir="logs",
            log_file_path="logs/run-a_events.jsonl",
            command=("python", "train.py"),
            trace_id="trace-a",
        ),
        ProcessStartedEvent(
            timestamp=t0 + timedelta(seconds=1),
            command=("python", "train.py"),
            pid=123,
            trace_id="trace-a",
        ),
        MeasurementEvent(
            timestamp=t0 + timedelta(seconds=2),
            provider_name="power",
            data=PowerMeasurementData(
                timestamp=t0 + timedelta(seconds=2),
                samples=(power_sample,),
            ),
        ),
        MeasurementEvent(
            timestamp=t0 + timedelta(seconds=3),
            provider_name="forecast",
            data=IntensityForecastData(
                timestamp=t0 + timedelta(seconds=3),
                location=None,
                forecasts=[
                    ForecastPoint(
                        timestamp=t0 + timedelta(hours=1),
                        carbon_intensity=80.0,
                    )
                ],
            ),
        ),
        SessionCurrentStatsEvent(
            timestamp=t0 + timedelta(seconds=4),
            stats=SessionStatsData(
                current_wattage=42.0,
                current_intensity=100.0,
                total_emissions_g=0.1,
                total_power_usage_kwh=0.001,
                power_usage_pr_device={"cpu:0": 42.0},
            ),
        ),
        SpanStart(started_at=t0 + timedelta(seconds=5), span_id="train"),
        SpanStop(ended_at=t0 + timedelta(seconds=10), span_id="train"),
        SpanProfileEvent(
            created_at=t0 + timedelta(seconds=11),
            span_id="train",
            parent_span_id=None,
            started_at=t0 + timedelta(seconds=5),
            ended_at=t0 + timedelta(seconds=10),
            profile=SpanProfile(
                span_id="train",
                parent_span_id=None,
                started_at=t0 + timedelta(seconds=5),
                ended_at=t0 + timedelta(seconds=10),
                devices={},
                avg_intensity=100.0,
                min_intensity=100.0,
                max_intensity=100.0,
                power_measurements_count=1,
                intensity_measurements_count=1,
                quality={"reliable": True},
            ),
            stats=stats,
        ),
        PredictionEvent(
            created_at=t0 + timedelta(seconds=12),
            result=PredictionResult(
                completed_units=1,
                total_units=2,
                run_duration_s=12.0,
                estimated_duration_left_s=12.0,
                projected_total_energy_kwh=0.002,
                projected_total_emissions_g=0.2,
            ),
        ),
        ProcessOutputEvent(
            timestamp=t0 + timedelta(seconds=13),
            stream="stdout",
            line="done",
            trace_id="trace-a",
        ),
        DiagnosticEvent(
            timestamp=t0 + timedelta(seconds=14),
            severity=LogSeverity.INFO,
            logger_name="test",
            message="diagnostic",
        ),
        ProcessExitedEvent(
            timestamp=t0 + timedelta(seconds=15),
            return_code=0,
            interrupted=False,
            trace_id="trace-a",
        ),
        FinishedSession(
            timestamp=t0 + timedelta(seconds=16),
            project_name="demo",
            run_name="run-a",
            log_dir="logs",
            log_file_path="logs/run-a_events.jsonl",
            stats=SessionFinalStats(
                total_emissions_g=0.2,
                total_power_usage_kwh=0.002,
                duration_s=16.0,
                completed_spans_count=1,
            ),
            command=("python", "train.py"),
            trace_id="trace-a",
        ),
    ]

    state = build_watch_state(events)

    assert state.status == "finished"
    assert state.return_code == 0
    assert state.total_power_usage_kwh == 0.002
    assert state.total_emissions_g == 0.2
    assert state.devices["cpu:0"].total_energy_kwh == 84.0 / 3_600_000
    assert state.forecast_points == [(t0 + timedelta(hours=1), 80.0)]
    assert state.spans["train"].duration_s == 5.0
    assert state.spans["train"].power_usage_kwh == 0.001
    assert state.spans["train"].reliable is True
    assert state.projected_energy_kwh == 0.002
    assert len(state.diagnostics) == 1


def test_jsonl_decode_errors_become_watch_diagnostics(tmp_path):
    t0 = datetime(2026, 1, 1, 12)
    log_path = tmp_path / "events.jsonl"
    log_path.write_text(
        "not-json\n"
        + event_to_json(
            StartedSession(
                timestamp=t0,
                project_name="demo",
                run_name="run-a",
                log_dir="logs",
                log_file_path="logs/run-a_events.jsonl",
            )
        )
        + "\n"
    )

    events = read_jsonl_events(log_path)
    state = build_watch_state(events)

    assert len(state.diagnostics) == 1
    assert "line 1" in state.diagnostics[0].message
    assert state.project_name == "demo"
