import json

import pytest

from carbontracker.core.exceptions import ProviderConfigError
from carbontracker.core.types import (
    CountryCode,
    ElectricityMapsDataCenter,
    ElectricityMapsZone,
    GeoLocation,
)
from carbontracker.providers.carbon_intensity.intensity_provider import ResolvedLocation
from carbontracker.providers.carbon_intensity.providers.electricity_maps import (
    ElectricityMapsProvider,
)
from carbontracker.providers.carbon_intensity_forecast.providers.electricity_maps import (
    ElectricityMapsForecastProvider,
)
from carbontracker.providers.electricity_maps.catalog import (
    decode_data_centers,
    decode_zones,
)


def test_native_electricity_maps_locations_validate_required_fields():
    zone = ElectricityMapsZone(zone_id="DK-DK1", zone_name="West Denmark")
    data_center = ElectricityMapsDataCenter(
        provider="gcp",
        region="europe-west1",
        zone_id="BE",
    )

    assert zone.zone_id == "DK-DK1"
    assert data_center.provider == "gcp"

    with pytest.raises(ValueError):
        ElectricityMapsZone(zone_id="")
    with pytest.raises(ValueError):
        ElectricityMapsDataCenter(provider="", region="europe-west1")
    with pytest.raises(ValueError):
        ElectricityMapsDataCenter(provider="gcp", region="")


def test_catalog_decodes_zones_fixture():
    payload = json.loads(open("test/fixtures/electricity_maps_zones.json").read())

    zones = decode_zones(payload)

    assert zones[0].zone_id == "DE"
    assert zones[1].zone_id == "DK-DK1"
    assert zones[1].zone_name == "West Denmark"
    assert zones[1].country_code == "DK"


def test_catalog_decodes_data_centers_fixture():
    payload = json.loads(
        open("test/fixtures/electricity_maps_data_centers.json").read()
    )

    data_centers = decode_data_centers(payload)

    assert data_centers[0] == ElectricityMapsDataCenter(
        provider="aws",
        region="eu-west-1",
        zone_id="IE",
        display_name="Ireland",
        status="operational",
    )
    assert data_centers[1].provider == "gcp"


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        (ElectricityMapsZone("DK-DK1"), {"zone": "DK-DK1"}),
        (
            ElectricityMapsDataCenter("gcp", "europe-west1"),
            {
                "dataCenterProvider": "gcp",
                "dataCenterRegion": "europe-west1",
            },
        ),
        (CountryCode("DK"), {"zone": "DK"}),
        (GeoLocation(55.67, 12.56), {"lat": "55.67", "lon": "12.56"}),
    ],
)
def test_electricity_maps_latest_provider_location_query_params(location, expected):
    provider = ElectricityMapsProvider(
        ResolvedLocation(location=location, source="config"),
        api_key="token",
    )

    assert provider.query_params == expected


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        (ElectricityMapsZone("DK-DK1"), {"zone": "DK-DK1"}),
        (
            ElectricityMapsDataCenter("gcp", "europe-west1"),
            {
                "dataCenterProvider": "gcp",
                "dataCenterRegion": "europe-west1",
            },
        ),
        (CountryCode("DK"), {"zone": "DK"}),
        (GeoLocation(55.67, 12.56), {"lat": "55.67", "lon": "12.56"}),
    ],
)
def test_electricity_maps_forecast_provider_location_query_params(location, expected):
    provider = ElectricityMapsForecastProvider(
        ResolvedLocation(location=location, source="config"),
        api_key="token",
    )

    assert provider.query_params == expected


def test_electricity_maps_provider_rejects_unknown_location():
    with pytest.raises(ProviderConfigError):
        ElectricityMapsProvider(
            ResolvedLocation(location=None, source="unknown"),
            api_key="token",
        )
