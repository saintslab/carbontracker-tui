from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Iterable

from carbontracker.core.spans import SpanRecord
from carbontracker.core.stats import SpanStats
from carbontracker.providers.carbon_intensity.intensity_provider import IntensityMeasurementData

JOULES_PER_KWH = 3_600_000.0


class PowerDomain(str, Enum):
    """Hardware domain measured by a power provider.

    SYSTEM means whole-machine power where the provider cannot split CPU/GPU/RAM.
    Use it sparingly because it cannot be joined to device-specific activity.
    """

    CPU = "cpu"
    GPU = "gpu"
    RAM = "ram"
    ANE = "ane"
    SYSTEM = "system"


class PowerScope(str, Enum):
    """Ownership scope of the measurement, not the hardware domain."""

    DEVICE_TOTAL = "device_total"
    PROCESS = "process"
    JOB = "job"
    CONTAINER = "container"


@dataclass(frozen=True)
class PowerSample:
    """One power or energy observation with explicit measurement semantics.

    observed_at is when the provider produced the observation. device_id is a
    stable join key such as gpu:0 or cpu:package-0, while label is only display
    text. source names the backend, such as nvml, rapl, or powermetrics. scope
    tells whether this measures a whole device or a true owner like a PID/job.
    PID utilization should not use this type unless it is true per-PID power or
    energy.
    """

    observed_at: datetime
    domain: PowerDomain
    device_id: str
    source: str
    scope: PowerScope = PowerScope.DEVICE_TOTAL
    watts: float | None = None
    cumulative_energy_j: float | None = None
    interval_energy_j: float | None = None
    interval_start: datetime | None = None
    interval_end: datetime | None = None
    pid: int | None = None
    owner_id: str | None = None
    label: str | None = None

    def __post_init__(self) -> None:
        if not self.device_id:
            raise ValueError("PowerSample.device_id must be non-empty")
        if not self.source:
            raise ValueError("PowerSample.source must be non-empty")
        if self.interval_energy_j is not None and (
            self.interval_start is None or self.interval_end is None
        ):
            raise ValueError(
                "PowerSample.interval_start and interval_end are required "
                "when interval_energy_j is set"
            )


@dataclass(frozen=True)
class DeviceEnergyInterval:
    """Normalized energy over a concrete time interval."""

    domain: PowerDomain
    device_id: str
    source: str
    scope: PowerScope
    start: datetime
    end: datetime
    energy_j: float
    pid: int | None = None
    owner_id: str | None = None

    @property
    def duration_s(self) -> float:
        return max((self.end - self.start).total_seconds(), 0.0)

    @property
    def average_watts(self) -> float:
        duration_s = self.duration_s
        if duration_s <= 0:
            return 0.0
        return self.energy_j / duration_s


@dataclass(frozen=True)
class IntensityInterval:
    """LOCF carbon intensity over a concrete time interval."""

    start: datetime
    end: datetime
    g_per_kwh: float

    @property
    def duration_s(self) -> float:
        return max((self.end - self.start).total_seconds(), 0.0)


@dataclass(frozen=True)
class DeviceSpanProfile:
    domain: PowerDomain
    device_id: str
    gross_energy_j: float
    gross_emissions_g: float
    avg_watt: float
    min_watt: float
    max_watt: float
    baseline_energy_j: float = 0.0
    baseline_emissions_g: float = 0.0

    @property
    def marginal_energy_j(self) -> float:
        return max(self.gross_energy_j - self.baseline_energy_j, 0.0)

    @property
    def marginal_emissions_g(self) -> float:
        return max(self.gross_emissions_g - self.baseline_emissions_g, 0.0)


@dataclass(frozen=True)
class SpanProfile:
    span_id: str
    parent_span_id: str | None
    started_at: datetime
    ended_at: datetime
    devices: dict[str, DeviceSpanProfile]
    avg_intensity: float
    min_intensity: float
    max_intensity: float
    power_measurements_count: int
    intensity_measurements_count: int
    quality: dict[str, str] = field(default_factory=dict)

    @property
    def duration_s(self) -> float:
        return max((self.ended_at - self.started_at).total_seconds(), 0.0)

    @property
    def gross_energy_j(self) -> float:
        return sum(device.gross_energy_j for device in self.devices.values())

    @property
    def gross_energy_kwh(self) -> float:
        return self.gross_energy_j / JOULES_PER_KWH

    @property
    def gross_emissions_g(self) -> float:
        return sum(device.gross_emissions_g for device in self.devices.values())

    @property
    def marginal_energy_kwh(self) -> float:
        return (
            sum(device.marginal_energy_j for device in self.devices.values())
            / JOULES_PER_KWH
        )

    @property
    def marginal_emissions_g(self) -> float:
        return sum(device.marginal_emissions_g for device in self.devices.values())

    @property
    def avg_watt(self) -> float:
        duration_s = self.duration_s
        if duration_s <= 0:
            return 0.0
        return self.gross_energy_j / duration_s

    @property
    def min_watt(self) -> float:
        return sum(device.min_watt for device in self.devices.values())

    @property
    def max_watt(self) -> float:
        return sum(device.max_watt for device in self.devices.values())

    @property
    def power_by_device_avg_watts(self) -> dict[str, float]:
        return {key: device.avg_watt for key, device in self.devices.items()}


@dataclass(frozen=True)
class WindowProfile:
    start: datetime
    end: datetime
    gross_energy_j: float
    gross_emissions_g: float
    current_wattage: float
    current_intensity: float
    current_power_by_device: dict[str, float]

    @property
    def gross_energy_kwh(self) -> float:
        return self.gross_energy_j / JOULES_PER_KWH


def _sample_group_key(
    sample: PowerSample,
) -> tuple[PowerDomain, str, str, PowerScope, int | None, str | None]:
    return (
        sample.domain,
        sample.device_id,
        sample.source,
        sample.scope,
        sample.pid,
        sample.owner_id,
    )


def _overlap_seconds(
    first_start: datetime,
    first_end: datetime,
    second_start: datetime,
    second_end: datetime,
) -> float:
    start = max(first_start, second_start)
    end = min(first_end, second_end)
    return max((end - start).total_seconds(), 0.0)


def _clip_interval(
    start: datetime, end: datetime, window_start: datetime, window_end: datetime
) -> tuple[datetime, datetime] | None:
    clipped_start = max(start, window_start)
    clipped_end = min(end, window_end)
    if clipped_end <= clipped_start:
        return None
    return clipped_start, clipped_end


class SpanPowerProfiler:
    def profile_span(
        self,
        span: SpanRecord,
        all_spans: list[SpanRecord],
        power_samples: list[PowerSample],
        intensity_measurements: list[IntensityMeasurementData],
    ) -> SpanProfile:
        if span.ended_at is None:
            raise ValueError(f"Cannot profile active span: {span.span_id}")

        energy_intervals = self.build_energy_intervals(
            samples=power_samples,
            start=span.started_at,
            end=span.ended_at,
        )
        intensity_intervals = self.build_intensity_intervals(
            measurements=intensity_measurements,
            start=span.started_at,
            end=span.ended_at,
        )
        devices = self._profile_devices(
            start=span.started_at,
            end=span.ended_at,
            energy_intervals=energy_intervals,
            intensity_intervals=intensity_intervals,
        )
        avg_i, min_i, max_i = self._intensity_stats(
            intensity_intervals, span.started_at, span.ended_at
        )

        return SpanProfile(
            span_id=span.span_id,
            parent_span_id=span.parent_span_id,
            started_at=span.started_at,
            ended_at=span.ended_at,
            devices=devices,
            avg_intensity=avg_i,
            min_intensity=min_i,
            max_intensity=max_i,
            power_measurements_count=sum(
                1
                for sample in power_samples
                if span.started_at <= sample.observed_at <= span.ended_at
            ),
            intensity_measurements_count=sum(
                1
                for measurement in intensity_measurements
                if span.started_at <= measurement.timestamp <= span.ended_at
            ),
        )

    def profile_window(
        self,
        start: datetime,
        end: datetime,
        power_samples: list[PowerSample],
        intensity_measurements: list[IntensityMeasurementData],
    ) -> WindowProfile:
        if end <= start:
            return WindowProfile(
                start=start,
                end=end,
                gross_energy_j=0.0,
                gross_emissions_g=0.0,
                current_wattage=0.0,
                current_intensity=0.0,
                current_power_by_device={},
            )

        energy_intervals = self.build_energy_intervals(
            samples=power_samples,
            start=start,
            end=end,
        )
        intensity_intervals = self.build_intensity_intervals(
            measurements=intensity_measurements,
            start=start,
            end=end,
        )

        gross_energy_j = sum(interval.energy_j for interval in energy_intervals)
        gross_emissions_g = sum(
            self._emissions_for_energy_interval(interval, intensity_intervals)
            for interval in energy_intervals
        )
        current_power_by_device = self.current_power_by_device(power_samples, at=end)

        return WindowProfile(
            start=start,
            end=end,
            gross_energy_j=gross_energy_j,
            gross_emissions_g=gross_emissions_g,
            current_wattage=sum(current_power_by_device.values()),
            current_intensity=self.current_intensity_at(intensity_measurements, at=end),
            current_power_by_device=current_power_by_device,
        )

    def build_energy_intervals(
        self,
        samples: list[PowerSample],
        start: datetime,
        end: datetime,
    ) -> list[DeviceEnergyInterval]:
        if end <= start or not samples:
            return []

        grouped: dict[
            tuple[PowerDomain, str, str, PowerScope, int | None, str | None],
            list[PowerSample],
        ] = defaultdict(list)
        for sample in samples:
            if sample.observed_at <= end:
                grouped[_sample_group_key(sample)].append(sample)

        intervals: list[DeviceEnergyInterval] = []
        for group_samples in grouped.values():
            intervals.extend(
                self._intervals_from_interval_energy(group_samples, start, end)
            )
            intervals.extend(
                self._intervals_from_cumulative_energy(group_samples, start, end)
            )
            intervals.extend(self._intervals_from_watts(group_samples, start, end))

        intervals.sort(key=lambda item: (item.start, item.end, item.device_id))
        return intervals

    def build_intensity_intervals(
        self,
        measurements: list[IntensityMeasurementData],
        start: datetime,
        end: datetime,
    ) -> list[IntensityInterval]:
        if end <= start:
            return []
        if not measurements:
            return [IntensityInterval(start=start, end=end, g_per_kwh=0.0)]

        ordered = sorted(measurements, key=lambda measurement: measurement.timestamp)
        seed = ordered[0]
        for measurement in ordered:
            if measurement.timestamp <= start:
                seed = measurement
            else:
                break

        intervals: list[IntensityInterval] = []
        current_value = seed.carbon_intensity
        cursor = start
        for measurement in ordered:
            if measurement.timestamp <= start:
                continue
            if measurement.timestamp >= end:
                break
            if measurement.timestamp > cursor:
                intervals.append(
                    IntensityInterval(
                        start=cursor,
                        end=measurement.timestamp,
                        g_per_kwh=current_value,
                    )
                )
            current_value = measurement.carbon_intensity
            cursor = measurement.timestamp

        if cursor < end:
            intervals.append(
                IntensityInterval(start=cursor, end=end, g_per_kwh=current_value)
            )
        return intervals

    def current_power_by_device(
        self, power_samples: list[PowerSample], at: datetime
    ) -> dict[str, float]:
        latest_by_device: dict[str, PowerSample] = {}
        for sample in power_samples:
            if sample.watts is None or sample.observed_at > at:
                continue
            current = latest_by_device.get(sample.device_id)
            if current is None or sample.observed_at >= current.observed_at:
                latest_by_device[sample.device_id] = sample
        return {
            device_id: max(sample.watts or 0.0, 0.0)
            for device_id, sample in latest_by_device.items()
        }

    def current_intensity_at(
        self, intensity_measurements: list[IntensityMeasurementData], at: datetime
    ) -> float:
        if not intensity_measurements:
            return 0.0
        ordered = sorted(
            intensity_measurements, key=lambda measurement: measurement.timestamp
        )
        current_value = ordered[0].carbon_intensity
        for measurement in ordered:
            if measurement.timestamp <= at:
                current_value = measurement.carbon_intensity
            else:
                break
        return current_value

    def _profile_devices(
        self,
        start: datetime,
        end: datetime,
        energy_intervals: list[DeviceEnergyInterval],
        intensity_intervals: list[IntensityInterval],
    ) -> dict[str, DeviceSpanProfile]:
        aggregates: dict[str, dict[str, object]] = {}
        duration_s = max((end - start).total_seconds(), 0.0)

        for interval in energy_intervals:
            key = interval.device_id
            if key not in aggregates:
                aggregates[key] = {
                    "domain": interval.domain,
                    "energy_j": 0.0,
                    "emissions_g": 0.0,
                    "powers": [],
                }
            aggregates[key]["energy_j"] = (
                float(aggregates[key]["energy_j"]) + interval.energy_j
            )
            aggregates[key]["emissions_g"] = (
                float(aggregates[key]["emissions_g"])
                + self._emissions_for_energy_interval(interval, intensity_intervals)
            )
            powers = aggregates[key]["powers"]
            assert isinstance(powers, list)
            powers.append(interval.average_watts)

        profiles: dict[str, DeviceSpanProfile] = {}
        for device_id, values in aggregates.items():
            energy_j = float(values["energy_j"])
            powers = values["powers"]
            assert isinstance(powers, list)
            profiles[device_id] = DeviceSpanProfile(
                domain=values["domain"],  # type: ignore[arg-type]
                device_id=device_id,
                gross_energy_j=energy_j,
                gross_emissions_g=float(values["emissions_g"]),
                avg_watt=energy_j / duration_s if duration_s > 0 else 0.0,
                min_watt=min(powers) if powers else 0.0,
                max_watt=max(powers) if powers else 0.0,
            )
        return profiles

    def _intervals_from_interval_energy(
        self,
        samples: list[PowerSample],
        start: datetime,
        end: datetime,
    ) -> list[DeviceEnergyInterval]:
        intervals: list[DeviceEnergyInterval] = []
        for sample in samples:
            if sample.interval_energy_j is None:
                continue
            assert sample.interval_start is not None
            assert sample.interval_end is not None
            clipped = _clip_interval(
                sample.interval_start, sample.interval_end, start, end
            )
            if clipped is None:
                continue
            clipped_start, clipped_end = clipped
            interval_duration_s = (
                sample.interval_end - sample.interval_start
            ).total_seconds()
            if interval_duration_s <= 0:
                continue
            overlap_s = (clipped_end - clipped_start).total_seconds()
            intervals.append(
                DeviceEnergyInterval(
                    domain=sample.domain,
                    device_id=sample.device_id,
                    source=sample.source,
                    scope=sample.scope,
                    start=clipped_start,
                    end=clipped_end,
                    energy_j=max(sample.interval_energy_j, 0.0)
                    * (overlap_s / interval_duration_s),
                    pid=sample.pid,
                    owner_id=sample.owner_id,
                )
            )
        return intervals

    def _intervals_from_cumulative_energy(
        self,
        samples: list[PowerSample],
        start: datetime,
        end: datetime,
    ) -> list[DeviceEnergyInterval]:
        cumulative_samples = sorted(
            [
                sample
                for sample in samples
                if sample.interval_energy_j is None
                and sample.cumulative_energy_j is not None
            ],
            key=lambda sample: sample.observed_at,
        )
        intervals: list[DeviceEnergyInterval] = []
        for previous, current in zip(cumulative_samples, cumulative_samples[1:]):
            clipped = _clip_interval(
                previous.observed_at, current.observed_at, start, end
            )
            if clipped is None:
                continue
            total_duration_s = (
                current.observed_at - previous.observed_at
            ).total_seconds()
            if total_duration_s <= 0:
                continue
            delta_j = (current.cumulative_energy_j or 0.0) - (
                previous.cumulative_energy_j or 0.0
            )
            if delta_j < 0:
                continue
            clipped_start, clipped_end = clipped
            overlap_s = (clipped_end - clipped_start).total_seconds()
            intervals.append(
                DeviceEnergyInterval(
                    domain=current.domain,
                    device_id=current.device_id,
                    source=current.source,
                    scope=current.scope,
                    start=clipped_start,
                    end=clipped_end,
                    energy_j=delta_j * (overlap_s / total_duration_s),
                    pid=current.pid,
                    owner_id=current.owner_id,
                )
            )
        return intervals

    def _intervals_from_watts(
        self,
        samples: list[PowerSample],
        start: datetime,
        end: datetime,
    ) -> list[DeviceEnergyInterval]:
        watt_samples = sorted(
            [
                sample
                for sample in samples
                if sample.interval_energy_j is None
                and sample.cumulative_energy_j is None
                and sample.watts is not None
            ],
            key=lambda sample: sample.observed_at,
        )
        if not watt_samples:
            return []

        intervals: list[DeviceEnergyInterval] = []
        for index, sample in enumerate(watt_samples):
            next_start = (
                watt_samples[index + 1].observed_at
                if index + 1 < len(watt_samples)
                else end
            )
            if next_start <= start or sample.observed_at >= end:
                continue

            interval_start = max(sample.observed_at, start)
            interval_end = min(next_start, end)
            if interval_end <= interval_start:
                continue

            watts = max(sample.watts or 0.0, 0.0)
            intervals.append(
                DeviceEnergyInterval(
                    domain=sample.domain,
                    device_id=sample.device_id,
                    source=sample.source,
                    scope=sample.scope,
                    start=interval_start,
                    end=interval_end,
                    energy_j=watts * (interval_end - interval_start).total_seconds(),
                    pid=sample.pid,
                    owner_id=sample.owner_id,
                )
            )
        return intervals

    def _emissions_for_energy_interval(
        self,
        interval: DeviceEnergyInterval,
        intensity_intervals: Iterable[IntensityInterval],
    ) -> float:
        if interval.duration_s <= 0:
            return 0.0

        emissions_g = 0.0
        for intensity in intensity_intervals:
            overlap_s = _overlap_seconds(
                interval.start, interval.end, intensity.start, intensity.end
            )
            if overlap_s <= 0:
                continue
            energy_j = interval.energy_j * (overlap_s / interval.duration_s)
            emissions_g += (energy_j / JOULES_PER_KWH) * intensity.g_per_kwh
        return emissions_g

    def _intensity_stats(
        self,
        intervals: list[IntensityInterval],
        start: datetime,
        end: datetime,
    ) -> tuple[float, float, float]:
        if not intervals or end <= start:
            return 0.0, 0.0, 0.0
        total_s = (end - start).total_seconds()
        weighted = sum(
            interval.g_per_kwh * interval.duration_s for interval in intervals
        )
        values = [interval.g_per_kwh for interval in intervals]
        return weighted / total_s, min(values), max(values)


def span_profile_to_stats(profile: SpanProfile) -> SpanStats:
    return SpanStats(
        avg_watt=profile.avg_watt,
        min_watt=profile.min_watt,
        max_watt=profile.max_watt,
        avg_intensity=profile.avg_intensity,
        min_intensity=profile.min_intensity,
        max_intensity=profile.max_intensity,
        power_usage_pr_device=profile.power_by_device_avg_watts,
        emissions_g=profile.gross_emissions_g,
        power_usage_kwh=profile.gross_energy_kwh,
        power_measurements_count=profile.power_measurements_count,
        intensity_measurements_count=profile.intensity_measurements_count,
    )
