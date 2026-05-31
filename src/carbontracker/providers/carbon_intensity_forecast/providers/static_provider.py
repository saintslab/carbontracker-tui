from datetime import datetime, timedelta
from carbontracker.providers.data_provider import DataProvider
from carbontracker.providers.carbon_intensity_forecast.forecast_provider import (
    IntensityForecastData, 
    ForecastPoint
)
from carbontracker.providers.carbon_intensity.intensity_provider import ResolvedLocation

class StaticForecastProvider(DataProvider[IntensityForecastData]):
    """
    A naive forecast provider that simply projects a constant intensity value
    into the future.
    """
    def __init__(
        self, 
        location: ResolvedLocation, 
        current_intensity: float,
        forecast_length_hours: int = 24,
        forecast_interval_hours: int = 1,
        name: str = "Static forecast provider"
    ):
        self.location = location
        self.current_intensity = current_intensity
        self.forecast_length_hours = forecast_length_hours
        self.forecast_interval_hours = forecast_interval_hours
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def fetch(self) -> IntensityForecastData:
        now = datetime.now()
        forecasts = []
        
        # Ensure we always return at least the current point
        if self.forecast_length_hours <= 0:
            forecasts.append(ForecastPoint(timestamp=now, carbon_intensity=self.current_intensity))
        else:
            current_time = now
            end_time = now + timedelta(hours=self.forecast_length_hours)
            interval = timedelta(hours=self.forecast_interval_hours)
            
            while current_time <= end_time:
                forecasts.append(
                    ForecastPoint(
                        timestamp=current_time,
                        carbon_intensity=self.current_intensity
                    )
                )
                current_time += interval

        return IntensityForecastData(
            timestamp=now,
            location=self.location.location,
            forecasts=forecasts
        )

    def shutdown(self) -> None:
        pass
