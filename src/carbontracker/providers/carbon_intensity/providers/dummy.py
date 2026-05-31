import math
from datetime import datetime, timedelta
from typing import List

# 1. Removed IntensityMeasurement from imports (the provider shouldn't know about the wrapper)
from carbontracker.providers.data_provider import DataProvider
from carbontracker.core.types import Location
from carbontracker.providers.carbon_intensity.intensity_provider import IntensityMeasurementData


class DummyForecaster(DataProvider[IntensityMeasurementData]):
    """
    A simulated carbon intensity provider.
    Satisfies DataProvider.location via a simple instance attribute.
    """
    
    def __init__(self, location: Location, base_intensity: float = 400.0):
        self.location = location
        self.base_intensity = base_intensity

    @property
    def name(self) -> str:
        return "Dummy Simulated Forecaster"

    # 2. Updated return type to the raw Data payload
    def fetch(self) -> IntensityMeasurementData:
        """Returns the current simulated intensity."""
        return self._generate(datetime.now(), is_prediction=False)

    # 3. Updated return type to a List of raw Data payloads
    def get_forecast(self, hours: int) -> List[IntensityMeasurementData]:
        """Generates a list of future measurements for the next N hours."""
        return [
            self._generate(datetime.now() + timedelta(hours=h), is_prediction=True)
            for h in range(1, hours + 1)
        ]

    def shutdown(self) -> None:
        """No hardware or API connections to close for the dummy."""
        pass

    def _generate(self, time: datetime, is_prediction: bool) -> IntensityMeasurementData:
        """
        Dips at 12:00 (high renewables/solar), peaks at 00:00.
        """
        
        cycle = math.cos(2 * math.pi * (time.hour - 12) / 24)
        variation = (self.base_intensity * 0.25) * cycle
        current_intensity = self.base_intensity + variation

        return IntensityMeasurementData(
            timestamp=time,
            location=self.location,
            carbon_intensity=round(current_intensity, 2) + random.uniform(-10.0, 10.0),
            is_prediction=is_prediction
        )