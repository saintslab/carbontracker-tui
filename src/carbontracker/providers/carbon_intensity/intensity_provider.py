
from abc import ABC
from dataclasses import dataclass
from carbontracker.core.resolution import ResolutionStep
from carbontracker.core.types import Location
from carbontracker.providers.data_provider import DataProvider, MeasurementData


@dataclass(frozen=True)
class ResolvedLocation:
    """The canonical location resolved from config + environment."""
    location: Location | None
    source: str # "config", "geolocation", "unknown"
    raw_input: Location | None= None

@dataclass(frozen=True)
class IntensityMeasurementData(MeasurementData):
    location: Location | None 
    carbon_intensity: float                # usually Co2eq g / kwh
    is_prediction: bool



@dataclass(frozen=True)
class IntensityResolution:
    """Complete result of intensity provider factory resolution."""
    provider: DataProvider[IntensityMeasurementData]
    location: ResolvedLocation
    steps: list[ResolutionStep]
    provider_name: str
    static_intensity: float | None
