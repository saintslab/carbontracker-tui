import pytest
from carbontracker.core.runtime import RuntimeOptions
from carbontracker.providers.carbon_intensity.location import resolve_location, location_to_country
from carbontracker.core.types import (
    CountryCode, ElectricityMapsZone, CloudRegion, GeoLocation, Location
)
from carbontracker.providers.carbon_intensity.factory import resolve_intensity_provider
from carbontracker.providers.carbon_intensity.providers.electricity_maps import ElectricityMapsProvider
from carbontracker.providers.carbon_intensity.providers.static_provider import (
    StaticCountryProvider, GlobalAverageProvider, StaticProvider
)


def _runtime_options(**overrides):
    values = {
        "run_name": "test",
        "auto_detect_location": False,
    }
    values.update(overrides)
    return RuntimeOptions(**values)


def test_resolve_location_parsing():
    # Country Code
    res = resolve_location("DK", auto_detect=False)
    assert res.source == "config"
    assert isinstance(res.location, CountryCode)
    assert res.location.country_code == "DK"
    
    # Grid Zone
    res = resolve_location("DK-DK1", auto_detect=False)
    assert isinstance(res.location, ElectricityMapsZone)
    assert res.location.zone_id == "DK-DK1"
    
    # Cloud Region
    res = resolve_location("aws:eu-west-1", auto_detect=False)
    assert isinstance(res.location, CloudRegion)
    assert res.location.provider == "aws"
    assert res.location.region == "eu-west-1"
    
    # Lat/Lon
    res = resolve_location("55.67, 12.56", auto_detect=False)
    assert isinstance(res.location, GeoLocation)
    assert res.location.latitude == 55.67
    assert res.location.longitude == 12.56

def test_location_to_country():
    # Cloud region fallback
    res = resolve_location("aws:eu-west-1", auto_detect=False)
    assert location_to_country(res.location) == "IE"
    
    # Grid zone fallback
    res = resolve_location("DK-DK1", auto_detect=False)
    assert location_to_country(res.location) == "DK"

def test_factory_electricity_maps():
    config = _runtime_options(
        intensity_method="electricityMaps",
        location=CountryCode(country_code="DK"),
        api_keys={"electricityMaps": "test-key"},
    )
    resolution = resolve_intensity_provider(config)
    assert isinstance(resolution.provider, ElectricityMapsProvider)
    assert resolution.provider.api_key == "test-key"

def test_factory_static_override():
    config = _runtime_options(
        intensity_method="static",
        static_carbon_intensity_g_per_kwh=123.4,
    )
    resolution = resolve_intensity_provider(config)
    assert isinstance(resolution.provider, StaticProvider)
    assert not isinstance(resolution.provider, StaticCountryProvider)
    assert resolution.provider.intensity_value == 123.4

def test_factory_auto_fallback_to_country():
    # No API key, but location provided (auto method)
    config = _runtime_options(
        intensity_method="auto",
        location=CountryCode(country_code="DK"),
        api_keys=None,
    )
    resolution = resolve_intensity_provider(config)
    assert isinstance(resolution.provider, StaticCountryProvider)
    assert resolution.provider.intensity_value == 166.0 # DK default

def test_factory_auto_fallback_to_global():
    # No API key, no location, auto_detect false
    config = _runtime_options(
        intensity_method="auto",
        location=None,
    )
    resolution = resolve_intensity_provider(config)
    assert isinstance(resolution.provider, GlobalAverageProvider)
    assert resolution.provider.intensity_value == 475.0
