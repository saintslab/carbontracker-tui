from pathlib import Path

from carbontracker import (
    CarbonTracker,
    CloudRegion,
    Component,
    CountryCode,
    ElectricityMapsDataCenter,
    ElectricityMapsZone,
    IntensityMethod,
    LogLevel,
)
from carbontracker.entrypoints.programmatic.manual import (
    CarbonTracker as CompatCarbonTracker,
)


def test_user_facing_api_is_exported_at_package_top_level():
    assert CarbonTracker is CompatCarbonTracker
    assert Component.CPU.value == "cpu"
    assert IntensityMethod.AUTO.value == "auto"
    assert LogLevel.WARNING.value == "warning"
    assert CountryCode("DK").country_code == "DK"
    assert CloudRegion("aws", "eu-west-1").region == "eu-west-1"
    assert ElectricityMapsZone("DK-DK1").zone_id == "DK-DK1"
    assert ElectricityMapsDataCenter("gcp", "europe-west1").region == "europe-west1"


def test_readme_uses_public_imports_for_examples():
    readme = Path("README.md").read_text()

    assert "carbontracker.entrypoints.programmatic.manual" not in readme
    assert "carbontracker.core.types" not in readme
