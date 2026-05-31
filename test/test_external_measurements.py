import queue
from datetime import datetime, timedelta

import pytest

from carbontracker.core.aggregator import AggregatorThread
from carbontracker.core.events import (
    MeasurementEvent,
    SpanProfileEvent,
    SpanStart,
    SpanStop,
)
from carbontracker.core.external import ExternalUsage, compute_external_accounting
from carbontracker.core.profiling import PowerDomain, PowerSample, SpanPowerProfiler
from carbontracker.core.spans import SpanRecord
from carbontracker.providers.carbon_intensity.intensity_provider import (
    IntensityMeasurementData,
)
from carbontracker.providers.power.power_provider import PowerMeasurementData


def drain(event_queue):
    events = []
    while not event_queue.empty():
        events.append(event_queue.get_nowait())
    return events


def intensity(timestamp: datetime, value: float) -> IntensityMeasurementData:
    return IntensityMeasurementData(
        timestamp=timestamp,
        location=None,
        carbon_intensity=value,
        is_prediction=False,
    )


def power(timestamp: datetime, watts: float) -> PowerSample:
    return PowerSample(
        observed_at=timestamp,
        domain=PowerDomain.CPU,
        device_id="cpu:0",
        source="test",
        watts=watts,
    )


def test_compute_external_accounting_explicit_intensity():
    accounting = compute_external_accounting(
        ExternalUsage(
            energy_kwh=0.00012,
            carbon_intensity_g_per_kwh=65.0,
        )
    )

    assert accounting is not None
    assert accounting.energy_kwh == 0.00012
    assert accounting.emissions_g == pytest.approx(0.0078)
    assert accounting.method == "explicit_intensity"


def test_compute_external_accounting_prefers_direct_emissions():
    accounting = compute_external_accounting(
        ExternalUsage(
            energy_kwh=0.00012,
            emissions_g=0.004,
            carbon_intensity_g_per_kwh=65.0,
        )
    )

    assert accounting is not None
    assert accounting.energy_kwh == 0.00012
    assert accounting.emissions_g == 0.004
    assert accounting.method == "direct_emissions_and_energy"


@pytest.mark.parametrize(
    "usage",
    [
        ExternalUsage(energy_kwh=0.00012),
        ExternalUsage(carbon_intensity_g_per_kwh=65.0),
        ExternalUsage(energy_kwh=-0.00012, emissions_g=0.004),
        ExternalUsage(emissions_g=-0.004),
        ExternalUsage(energy_kwh=0.00012, carbon_intensity_g_per_kwh=-65.0),
    ],
)
def test_invalid_external_accounting_produces_no_sidecar(usage):
    assert compute_external_accounting(usage) is None


def test_direct_emissions_without_energy_records_zero_energy():
    accounting = compute_external_accounting(ExternalUsage(emissions_g=0.004))

    assert accounting is not None
    assert accounting.energy_kwh == 0.0
    assert accounting.emissions_g == 0.004
    assert accounting.method == "direct_emissions"


def test_span_record_close_copies_external_usage():
    t0 = datetime(2026, 1, 1, 12)
    span = SpanRecord.from_start(
        SpanStart(started_at=t0, span_id="api_call", parent_span_id="process")
    )
    usage = ExternalUsage(emissions_g=0.004)

    span.close(
        SpanStop(
            ended_at=t0 + timedelta(seconds=1),
            span_id="api_call",
            external_usage=usage,
        )
    )

    assert span.external_usage == usage


def test_aggregator_emits_external_accounting_sidecar_not_measured_stats():
    t0 = datetime(2026, 1, 1, 12)
    sink = queue.Queue()
    aggregator = AggregatorThread(
        session_stats_interval_s=1.0,
        aggregation_queue=queue.Queue(),
        event_sink=[sink],
        profiler=SpanPowerProfiler(),
    )

    aggregator._handle_span_start(
        SpanStart(started_at=t0, span_id="llm_call", parent_span_id="process")
    )
    aggregator._handle_span_stop(
        SpanStop(
            ended_at=t0 + timedelta(seconds=1),
            span_id="llm_call",
            parent_span_id="process",
            external_usage=ExternalUsage(emissions_g=5.0),
        )
    )

    profile_event = next(
        event for event in drain(sink) if isinstance(event, SpanProfileEvent)
    )

    assert profile_event.external_accounting is not None
    assert profile_event.external_accounting.emissions_g == 5.0
    assert profile_event.profile.devices == {}
    assert profile_event.stats is not None
    assert profile_event.stats.emissions_g == 0.0
    assert profile_event.stats.power_usage_kwh == 0.0


def test_invalid_external_usage_logs_and_emits_no_sidecar(caplog):
    caplog.set_level("ERROR", logger="carbontracker.aggregator")
    t0 = datetime(2026, 1, 1, 12)
    sink = queue.Queue()
    aggregator = AggregatorThread(
        session_stats_interval_s=1.0,
        aggregation_queue=queue.Queue(),
        event_sink=[sink],
        profiler=SpanPowerProfiler(),
    )

    aggregator._handle_span_start(SpanStart(started_at=t0, span_id="api_call"))
    aggregator._handle_span_stop(
        SpanStop(
            ended_at=t0 + timedelta(seconds=1),
            span_id="api_call",
            external_usage=ExternalUsage(energy_kwh=0.00012),
        )
    )

    profile_event = next(
        event for event in drain(sink) if isinstance(event, SpanProfileEvent)
    )

    assert profile_event.external_accounting is None
    assert "Invalid external usage for span_id api_call" in caplog.text


def test_external_usage_does_not_change_session_totals():
    t0 = datetime(2026, 1, 1, 12)
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
            data=PowerMeasurementData(timestamp=t0, samples=(power(t0, 100.0),)),
        )
    )
    aggregator._handle_measurement(
        MeasurementEvent(
            provider_name="test",
            timestamp=t0,
            data=intensity(t0, 100.0),
        )
    )

    aggregator._handle_span_start(SpanStart(started_at=t0, span_id="api_call"))
    aggregator._handle_span_stop(
        SpanStop(
            ended_at=t0 + timedelta(seconds=1),
            span_id="api_call",
            external_usage=ExternalUsage(
                energy_kwh=10.0,
                emissions_g=1000.0,
            ),
        )
    )
    profile = aggregator._refresh_cumulative_stats(t0 + timedelta(seconds=10))

    assert profile.gross_energy_kwh == pytest.approx(1000.0 / 3_600_000.0)
    assert aggregator._cumulative_power_kwh == pytest.approx(1000.0 / 3_600_000.0)
    assert aggregator._cumulative_emissions_g == pytest.approx(
        (1000.0 / 3_600_000.0) * 100.0
    )
