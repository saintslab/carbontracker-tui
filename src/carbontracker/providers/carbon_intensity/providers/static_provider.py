from datetime import datetime
from carbontracker.providers.data_provider import DataProvider
from carbontracker.providers.carbon_intensity.intensity_provider import IntensityMeasurementData, ResolvedLocation
from carbontracker.providers.carbon_intensity.country_defaults import GLOBAL_AVERAGE_INTENSITY, COUNTRY_INTENSITY_DEFAULTS

class StaticProvider(DataProvider[IntensityMeasurementData]):
    def __init__(self, location: ResolvedLocation, intensity_value: float, name: str = "Static carbon intensity"):
        self.location = location
        self.intensity_value = intensity_value
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def fetch(self) -> IntensityMeasurementData:
        return IntensityMeasurementData(
            timestamp=datetime.now(),
            location=self.location.location,
            carbon_intensity=self.intensity_value,
            is_prediction=False
        )

    def shutdown(self) -> None:
        pass


class StaticCountryProvider(StaticProvider):
    def __init__(self, location: ResolvedLocation, country_code: str):
        value = COUNTRY_INTENSITY_DEFAULTS.get(country_code, GLOBAL_AVERAGE_INTENSITY)
        name = f"Static country average ({country_code})"
        super().__init__(location, value, name)


class GlobalAverageProvider(StaticProvider):
    def __init__(self, location: ResolvedLocation):
        super().__init__(location, GLOBAL_AVERAGE_INTENSITY, "Global average")
