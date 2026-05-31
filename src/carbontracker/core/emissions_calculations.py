from datetime import datetime
from typing import List, Tuple

from carbontracker.core.profiling import (
    PowerDomain,
    PowerSample,
    PowerScope,
    SpanPowerProfiler,
    span_profile_to_stats,
)
from carbontracker.core.spans import SpanRecord
from carbontracker.core.stats import SpanStats
from carbontracker.providers.carbon_intensity.intensity_provider import IntensityMeasurementData
from carbontracker.providers.power.power_provider import PowerMeasurementData


def get_intensity_at(t: datetime, intensities: List[Tuple[datetime, float]]) -> float:
    """
    Finds the active carbon intensity at a specific moment in time.
    Uses Last-Observation-Carried-Forward, falling back to the first measurement.
    """
    if not intensities:
        return 0.0

    intensity = intensities[0][1]
    for i_time, i_val in intensities:
        if i_time <= t:
            intensity = i_val
        else:
            break
    return intensity


def calculate_device_energy_and_emissions(
    device_name: str,
    power_measurements: List[Tuple[datetime, float]],
    intensity_measurements: List[Tuple[datetime, float]],
    t_start: datetime,
    t_stop: datetime,
) -> Tuple[float, float, float, float, float]:
    """
    Compatibility wrapper for single-device watt tuples.
    New code should use SpanPowerProfiler directly.
    """
    power_samples = [
        PowerSample(
            observed_at=timestamp,
            domain=PowerDomain.SYSTEM,
            device_id=device_name,
            source="tuple_compat",
            scope=PowerScope.DEVICE_TOTAL,
            watts=watts,
            label=device_name,
        )
        for timestamp, watts in power_measurements
    ]
    intensity_samples = [
        IntensityMeasurementData(
            timestamp=timestamp,
            location=None,
            carbon_intensity=intensity,
            is_prediction=False,
        )
        for timestamp, intensity in intensity_measurements
    ]

    profile = SpanPowerProfiler().profile_window(
        start=t_start,
        end=t_stop,
        power_samples=power_samples,
        intensity_measurements=intensity_samples,
    )
    duration_s = (t_stop - t_start).total_seconds()
    avg_watt = profile.gross_energy_j / duration_s if duration_s > 0 else 0.0
    powers = [sample.watts or 0.0 for sample in power_samples]
    min_watt = min(powers) if powers else 0.0
    max_watt = max(powers) if powers else 0.0
    return (
        profile.gross_energy_j,
        avg_watt,
        min_watt,
        max_watt,
        profile.gross_emissions_g,
    )


def compute_epoch_stats(
    power_m: List[PowerMeasurementData],
    intensity_m: List[IntensityMeasurementData],
    start: datetime,
    end: datetime,
) -> SpanStats:
    """
    Compatibility wrapper around SpanPowerProfiler for legacy callers.
    """
    span = SpanRecord(
        span_id="compat",
        parent_span_id=None,
        started_at=start,
        ended_at=end,
    )
    power_samples = [
        sample for measurement in power_m for sample in measurement.samples
    ]
    profile = SpanPowerProfiler().profile_span(
        span=span,
        all_spans=[span],
        power_samples=power_samples,
        intensity_measurements=intensity_m,
    )
    return span_profile_to_stats(profile)
