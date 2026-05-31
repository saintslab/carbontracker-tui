import queue
from datetime import datetime, timedelta

import pytest

from carbontracker.core.aggregator import AggregatorThread
from carbontracker.core.event_codec import event_from_json, event_to_dict
from carbontracker.core.events import PredictionEvent, SessionMetadata
from carbontracker.core.prediction import PredictionEngine, PredictionResult
from carbontracker.core.profiling import SpanPowerProfiler
from carbontracker.core.runtime import RuntimeOptions, build_subprocess_runtime
from carbontracker.reporters.file_logger import FileWriterThread


def test_runtime_options_validate_prediction_inputs():
    RuntimeOptions(total_units=10, predict_after_units=0, predict_interval_s=0)
    RuntimeOptions(total_duration_s=60, predict_after_seconds=0)

    invalid_cases = [
        {"total_units": 0},
        {"total_duration_s": 0},
        {"predict_after_units": -1, "total_units": 10},
        {"predict_after_seconds": -1, "total_duration_s": 60},
        {"unit_name": "   ", "total_units": 10},
        {"unit_name": "epoch"},
        {"predict_after_units": 1},
        {"total_units": 10, "total_duration_s": 60},
    ]

    for values in invalid_cases:
        with pytest.raises(ValueError):
            RuntimeOptions(**values)


def test_prediction_interval_zero_emits_at_most_once_after_readiness():
    engine = PredictionEngine(
        total_units=2,
        unit_name=None,
        total_duration_s=None,
        predict_after_units=1,
        predict_interval_s=0,
    )
    now = datetime(2026, 1, 1, 12)

    assert not engine.should_predict(
        now=now,
        run_duration_s=1,
        completed_span_names=[],
        completed_root_span_names=[],
    )
    assert engine.should_predict(
        now=now + timedelta(seconds=1),
        run_duration_s=2,
        completed_span_names=["epoch_1"],
        completed_root_span_names=["epoch_1"],
    )

    engine.predict(
        span_stats=[],
        run_duration_s=2,
        current_cumulative_energy_kwh=1.0,
        current_cumulative_emissions_g=2.0,
        forecast=None,
        completed_span_names=["epoch_1"],
        completed_root_span_names=["epoch_1"],
    )

    assert not engine.should_predict(
        now=now + timedelta(seconds=2),
        run_duration_s=3,
        completed_span_names=["epoch_1", "epoch_2"],
        completed_root_span_names=["epoch_1", "epoch_2"],
    )


def test_aggregator_prediction_event_reaches_all_sinks():
    first_sink = queue.Queue()
    second_sink = queue.Queue()
    aggregator = AggregatorThread(
        session_stats_interval_s=1,
        aggregation_queue=queue.Queue(),
        event_sink=[first_sink, second_sink],
        profiler=SpanPowerProfiler(),
        session_metadata=SessionMetadata(
            project_name="project",
            run_name="run",
            log_dir="logs",
            log_file_path="logs/run_events.jsonl",
        ),
        prediction_engine=PredictionEngine(
            total_units=2,
            unit_name=None,
            total_duration_s=None,
            predict_after_units=1,
            predict_interval_s=0,
        ),
    )
    aggregator._completed_span_names = ["epoch_1"]
    aggregator._completed_root_span_names = ["epoch_1"]
    aggregator._cumulative_power_kwh = 1.0
    aggregator._cumulative_emissions_g = 2.0

    aggregator._update_predictions()

    first_event = first_sink.get_nowait()
    second_event = second_sink.get_nowait()
    assert isinstance(first_event, PredictionEvent)
    assert isinstance(second_event, PredictionEvent)
    assert first_event.result.completed_units == 1
    assert event_to_dict(first_event) == event_to_dict(second_event)


def test_prediction_events_are_written_to_jsonl(tmp_path):
    event_queue = queue.Queue()
    writer = FileWriterThread(
        log_dir=str(tmp_path),
        run_name="run-a",
        event_queue=event_queue,
    )
    writer.start()
    event_queue.put(
        PredictionEvent(
            created_at=datetime(2026, 1, 1, 12),
            result=PredictionResult(
                completed_units=1,
                total_units=2,
                run_duration_s=10,
                estimated_duration_left_s=10,
                projected_total_energy_kwh=0.5,
                projected_total_emissions_g=20,
            ),
        )
    )
    writer.stop()
    writer.join()

    lines = writer.log_file_path.read_text().splitlines()
    assert len(lines) == 1
    decoded = event_from_json(lines[0])
    assert isinstance(decoded, PredictionEvent)
    assert decoded.result.completed_units == 1


def test_subprocess_runtime_can_add_tui_sink(monkeypatch):
    class FakeThread:
        def __init__(self, name):
            self.name = name
            self.daemon = True

    def fake_power_thread(**_kwargs):
        return FakeThread("power")

    def fake_intensity_thread(**_kwargs):
        class Resolution:
            provider_name = "static"
            location = None
            static_intensity = 100.0

        return FakeThread("intensity"), Resolution()

    def fake_forecast_thread(**_kwargs):
        return FakeThread("forecast")

    monkeypatch.setattr(
        "carbontracker.core.runtime.create_power_thread", fake_power_thread
    )
    monkeypatch.setattr(
        "carbontracker.core.runtime.create_intensity_thread", fake_intensity_thread
    )
    monkeypatch.setattr(
        "carbontracker.core.runtime.create_intensity_forecast_thread",
        fake_forecast_thread,
    )

    bundle = build_subprocess_runtime(
        ["python", "-c", "print('ok')"],
        RuntimeOptions(run_name="run-a", total_duration_s=10),
        enable_tui_sink=True,
    )

    assert bundle.tui_queue is not None
    assert bundle.tui_queue in bundle.event_sink
    assert bundle.aggregator_thread._prediction_engine is not None
