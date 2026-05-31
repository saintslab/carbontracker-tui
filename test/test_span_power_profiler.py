import queue
from datetime import datetime, timedelta

import pytest

from carbontracker.core.aggregator import AggregatorThread
from carbontracker.core.events import (
    MeasurementEvent,
    SessionCurrentStatsEvent,
    SpanProfileEvent,
    SpanStart,
    SpanStop,
)
from carbontracker.core.profiling import PowerDomain, PowerSample, SpanPowerProfiler
from carbontracker.providers.carbon_intensity.intensity_provider import IntensityMeasurementData
from carbontracker.providers.power.power_provider import PowerMeasurementData


def intensity(timestamp: datetime, value: float) -> IntensityMeasurementData:
    return IntensityMeasurementData(
        timestamp=timestamp,
        location=None,
        carbon_intensity=value,
        is_prediction=False,
    )


def power(timestamp: datetime, watts: float, device_id: str = "cpu:0") -> PowerSample:
    return PowerSample(
        observed_at=timestamp,
        domain=PowerDomain.CPU,
        device_id=device_id,
        source="test",
        watts=watts,
    )


def test_profile_window_uses_power_locf_seed_and_splits_intensity():
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    profiler = SpanPowerProfiler()

    profile = profiler.profile_window(
        start=t0 + timedelta(seconds=5),
        end=t0 + timedelta(seconds=15),
        power_samples=[
            power(t0, 100.0),
            power(t0 + timedelta(seconds=10), 200.0),
        ],
        intensity_measurements=[
            intensity(t0, 100.0),
            intensity(t0 + timedelta(seconds=12), 200.0),
        ],
    )

    assert profile.gross_energy_j == pytest.approx(1500.0)
    assert profile.gross_emissions_g == pytest.approx(
        (900.0 / 3_600_000.0) * 100.0 + (600.0 / 3_600_000.0) * 200.0
    )


def test_aggregator_profiles_span_stop_and_keeps_measurements():
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    sink = queue.Queue()
    aggregator = AggregatorThread(
        session_stats_interval_s=1.0,
        aggregation_queue=queue.Queue(),
        event_sink=[sink],
        profiler=SpanPowerProfiler(),
    )

    aggregator._handle_measurement(
        MeasurementEvent(
            provider_name="test",
            timestamp=t0,
            data=PowerMeasurementData(
                timestamp=t0,
                samples=(power(t0, 100.0), power(t0 + timedelta(seconds=10), 200.0)),
            ),
        )
    )
    aggregator._handle_measurement(
        MeasurementEvent(
            provider_name="test",
            timestamp=t0,
            data=intensity(t0, 100.0),
        )
    )

    aggregator._handle_span_start(
        SpanStart(
            started_at=t0 + timedelta(seconds=5),
            span_id="batch_1",
            parent_span_id="epoch_1",
        )
    )
    aggregator._handle_span_stop(
        SpanStop(
            ended_at=t0 + timedelta(seconds=15),
            span_id="batch_1",
            parent_span_id="epoch_1",
        )
    )

    emitted = []
    while not sink.empty():
        emitted.append(sink.get())

    profile_events = [
        event for event in emitted if isinstance(event, SpanProfileEvent)
    ]
    assert len(profile_events) == 1
    assert profile_events[0].parent_span_id == "epoch_1"
    assert profile_events[0].profile.gross_energy_j == pytest.approx(1500.0)
    assert len(aggregator._power_samples) == 2


def test_aggregator_emit_session_stats_uses_profiler_window():
    t0 = datetime.now() - timedelta(seconds=10)
    sink = queue.Queue()
    aggregator = AggregatorThread(
        session_stats_interval_s=1.0,
        aggregation_queue=queue.Queue(),
        event_sink=[sink],
        profiler=SpanPowerProfiler(),
    )
    aggregator._session_start_time = t0

    aggregator._handle_measurement(
        MeasurementEvent(
            provider_name="test",
            timestamp=t0,
            data=PowerMeasurementData(
                timestamp=t0,
                samples=(power(t0, 100.0),),
            ),
        )
    )
    aggregator._handle_measurement(
        MeasurementEvent(
            provider_name="test",
            timestamp=t0,
            data=intensity(t0, 100.0),
        )
    )

    aggregator._emit_session_stats()

    emitted = []
    while not sink.empty():
        emitted.append(sink.get())

    session_events = [
        event for event in emitted if isinstance(event, SessionCurrentStatsEvent)
    ]
    assert len(session_events) == 1
    assert session_events[0].stats.total_power_usage_kwh > 0.0
    assert session_events[0].stats.current_wattage == pytest.approx(100.0)
