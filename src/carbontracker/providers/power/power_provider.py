from pydantic.dataclasses import dataclass
from carbontracker.providers.data_provider import MeasurementData
from carbontracker.core.profiling import PowerSample


@dataclass(frozen=True)
class PowerMeasurementData(MeasurementData):
    """Batch of power samples emitted by one provider fetch."""

    samples: tuple[PowerSample, ...]
