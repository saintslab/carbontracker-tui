from dataclasses import replace

from carbontracker.config.config_manager import resolve_overrides
from carbontracker.config.init_draft import (
    default_init_draft,
    draft_to_runtime_mapping,
    validate_init_draft,
    write_project_config_from_draft,
)
from carbontracker.core.runtime import RuntimeOptions
from carbontracker.core.types import (
    Component,
    ElectricityMapsDataCenter,
    ElectricityMapsZone,
    IntensityMethod,
)


def test_default_init_draft_validates_and_maps_to_runtime_options(tmp_path):
    draft = default_init_draft(tmp_path / "project-a")

    assert validate_init_draft(draft) == []
    options = RuntimeOptions.from_mapping(draft_to_runtime_mapping(draft))
    assert options.project_name == "project-a"
    assert options.components == [Component.CPU, Component.GPU, Component.RAM]


def test_static_init_draft_validates():
    draft = replace(
        default_init_draft(),
        intensity_method=IntensityMethod.STATIC,
        static_carbon_intensity_g_per_kwh=120.0,
        forecast_provider_name="static",
    )

    assert validate_init_draft(draft) == []


def test_electricity_maps_zone_and_data_center_drafts_validate():
    zone_draft = replace(
        default_init_draft(),
        intensity_method=IntensityMethod.ELECTRICITY_MAPS,
        location=ElectricityMapsZone("DK-DK1"),
        forecast_provider_name="electricity_maps",
    )
    data_center_draft = replace(
        default_init_draft(),
        intensity_method=IntensityMethod.ELECTRICITY_MAPS,
        location=ElectricityMapsDataCenter("gcp", "europe-west1"),
        forecast_provider_name="electricity_maps",
    )

    assert validate_init_draft(zone_draft) == []
    assert validate_init_draft(data_center_draft) == []


def test_write_project_config_from_draft_round_trips_location(monkeypatch, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    draft = replace(
        default_init_draft(project),
        location=ElectricityMapsDataCenter("gcp", "europe-west1", zone_id="BE"),
    )

    path = write_project_config_from_draft(draft)
    resolved = resolve_overrides()

    assert path == project / ".carbontracker" / "config.toml"
    assert resolved["location"] == ElectricityMapsDataCenter(
        "gcp",
        "europe-west1",
        zone_id="BE",
    )
