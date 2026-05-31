import json
import urllib.request
import urllib.parse
from datetime import datetime
from carbontracker.providers.data_provider import DataProvider
from carbontracker.providers.carbon_intensity_forecast.forecast_provider import (
    IntensityForecastData, 
    ForecastPoint
)
from carbontracker.providers.carbon_intensity.intensity_provider import ResolvedLocation
from carbontracker.core.types import (
    CountryCode,
    ElectricityMapsDataCenter,
    ElectricityMapsGridZone,
    ElectricityMapsZone,
    GeoLocation,
)
from carbontracker.core.exceptions import ProviderConfigError, APIError


def _query_params_for_location(location: ResolvedLocation) -> dict[str, str]:
    if not location.location:
        return {}

    data = location.location
    if isinstance(data, (ElectricityMapsZone, ElectricityMapsGridZone)):
        return {"zone": data.zone_id}
    if isinstance(data, ElectricityMapsDataCenter):
        return {
            "dataCenterProvider": data.provider,
            "dataCenterRegion": data.region,
        }
    if isinstance(data, GeoLocation):
        return {"lat": str(data.latitude), "lon": str(data.longitude)}
    if isinstance(data, CountryCode):
        return {"zone": data.country_code}
    return {}


class ElectricityMapsForecastProvider(DataProvider[IntensityForecastData]):
    """
    Carbon intensity forecast provider using the Electricity Maps API.
    """
    BASE_URL = "https://api.electricitymap.org/v3/carbon-intensity/forecast"

    def __init__(self, location: ResolvedLocation, api_key: str):
        self.location = location
        self.api_key = api_key
        
        self.query_params = _query_params_for_location(location)
                
        if not self.query_params:
            raise ProviderConfigError(
                "Electricity Maps API requires a valid zone, data center, or lat/lon location."
            )

    @property
    def name(self) -> str:
        if 'zone' in self.query_params:
            return f"Electricity Maps API Forecast (zone: {self.query_params['zone']})"
        if "dataCenterProvider" in self.query_params:
            return (
                "Electricity Maps API Forecast "
                f"(data center: {self.query_params['dataCenterProvider']}:"
                f"{self.query_params['dataCenterRegion']})"
            )
        return "Electricity Maps API Forecast"

    def fetch(self) -> IntensityForecastData:
        url = self.BASE_URL
        if self.query_params:
            url += "?" + urllib.parse.urlencode(self.query_params)
            
        req = urllib.request.Request(url, headers={"auth-token": self.api_key})
        try:
            with urllib.request.urlopen(req, timeout=10.0) as response:
                if response.status == 200:
                    payload = json.loads(response.read().decode('utf-8'))
                    
                    forecasts = []
                    for point in payload.get('forecast', []):
                        # EM API returns datetime in ISO 8601 format (e.g. "2024-11-20T12:00:00.000Z")
                        dt_str = point.get('datetime')
                        if dt_str:
                            dt_str = dt_str.replace("Z", "+00:00")
                            try:
                                dt = datetime.fromisoformat(dt_str)
                            except ValueError:
                                # Fallback if parsing fails
                                continue
                                
                            forecasts.append(ForecastPoint(
                                timestamp=dt,
                                carbon_intensity=point.get('carbonIntensity')
                            ))
                            
                    return IntensityForecastData(
                        timestamp=datetime.now(),
                        location=self.location.location,
                        forecasts=forecasts
                    )
                else:
                    raise APIError(f"Electricity Maps API returned status {response.status}")
        except Exception as e:
            raise APIError(f"Failed to fetch forecast from Electricity Maps: {e}")

    def shutdown(self) -> None:
        pass
