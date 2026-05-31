from carbontracker.config.config_manager import (
    GlobalConfig,
    load_global_config,
    load_local_config,
    resolve_overrides,
    save_global_config,
)
from carbontracker.config.location_config import location_from_config, location_to_config
from carbontracker.config.project_init import init_project_config
from carbontracker.core.types import (
    CloudRegion,
    CountryCode,
    ElectricityMapsDataCenter,
    ElectricityMapsZone,
    GeoLocation,
)


def test_all_native_locations_round_trip_through_config_payloads():
    locations = [
        GeoLocation(55.67, 12.56),
        CloudRegion("aws", "eu-west-1"),
        ElectricityMapsZone("DK-DK1", zone_name="West Denmark", country_code="DK"),
        ElectricityMapsDataCenter("gcp", "europe-west1", zone_id="BE"),
        CountryCode("DK"),
    ]

    for location in locations:
        assert location_from_config(location_to_config(location)) == location


def test_legacy_string_locations_still_parse():
    assert location_from_config("55.67,12.56") == GeoLocation(55.67, 12.56)
    assert location_from_config("aws:eu-west-1") == CloudRegion("aws", "eu-west-1")
    assert location_from_config("DK-DK1") == ElectricityMapsZone("DK-DK1")
    assert location_from_config("DK") == CountryCode("DK")


def test_project_location_config_resolves_to_native_location(monkeypatch, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)

    init_project_config(location=ElectricityMapsDataCenter("gcp", "europe-west1"))

    loaded = load_local_config()
    resolved = resolve_overrides()

    assert loaded["location"] == ElectricityMapsDataCenter("gcp", "europe-west1")
    assert resolved["location"] == ElectricityMapsDataCenter("gcp", "europe-west1")


def test_global_location_config_resolves_to_native_location(monkeypatch, tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(project)

    save_global_config(
        GlobalConfig(default_location=ElectricityMapsZone("DK-DK1"), default_pue=1.2)
    )

    assert load_global_config().default_location == ElectricityMapsZone("DK-DK1")
    assert resolve_overrides()["location"] == ElectricityMapsZone("DK-DK1")
