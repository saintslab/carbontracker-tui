from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from carbontracker.config.project_init import default_project_config, init_project_config
from carbontracker.core.runtime import RuntimeOptions
from carbontracker.core.types import Component, IntensityMethod, Location


@dataclass(frozen=True)
class InitDiagnostic:
    severity: str
    message: str
    field: str | None = None


@dataclass(frozen=True)
class InitDraft:
    project_name: str
    log_dir: str
    components: tuple[Component, ...]
    power_sampling_interval: float
    intensity_sampling_interval: float
    intensity_method: IntensityMethod
    location: Location | None = None
    forecast_provider_name: str | None = None
    static_carbon_intensity_g_per_kwh: float | None = None
    total_units: int | None = None
    unit_name: str | None = None
    total_duration_s: float | None = None
    predict_after_units: int | None = None
    predict_after_seconds: float | None = None
    predict_interval_s: float | None = None


def default_init_draft(project_dir: Path | None = None) -> InitDraft:
    defaults = default_project_config(project_dir=project_dir)
    return InitDraft(
        project_name=str(defaults["project_name"]),
        log_dir=str(defaults["log_dir"]),
        components=tuple(Component(value) for value in defaults["components"]),
        power_sampling_interval=float(defaults["power_sampling_interval"]),
        intensity_sampling_interval=float(defaults["intensity_sampling_interval"]),
        intensity_method=IntensityMethod(defaults["intensity_method"]),
    )


def draft_to_runtime_mapping(draft: InitDraft) -> dict[str, object]:
    values: dict[str, Any] = {
        "project_name": draft.project_name,
        "log_dir": draft.log_dir,
        "components": [component.value for component in draft.components],
        "power_sampling_interval": draft.power_sampling_interval,
        "intensity_sampling_interval": draft.intensity_sampling_interval,
        "intensity_method": draft.intensity_method.value,
        "location": draft.location,
        "forecast_provider_name": draft.forecast_provider_name,
        "static_carbon_intensity_g_per_kwh": draft.static_carbon_intensity_g_per_kwh,
        "total_units": draft.total_units,
        "unit_name": draft.unit_name,
        "total_duration_s": draft.total_duration_s,
        "predict_after_units": draft.predict_after_units,
        "predict_after_seconds": draft.predict_after_seconds,
        "predict_interval_s": draft.predict_interval_s,
    }
    return {key: value for key, value in values.items() if value is not None}


def validate_init_draft(draft: InitDraft) -> list[InitDiagnostic]:
    diagnostics: list[InitDiagnostic] = []

    if not draft.components:
        diagnostics.append(
            InitDiagnostic(
                severity="error",
                field="components",
                message="At least one component must be selected.",
            )
        )

    if (
        draft.intensity_method == IntensityMethod.ELECTRICITY_MAPS
        and draft.location is None
    ):
        diagnostics.append(
            InitDiagnostic(
                severity="error",
                field="location",
                message="Electricity Maps requires a zone, data center, country, or lat/lon location.",
            )
        )

    try:
        RuntimeOptions.from_mapping(draft_to_runtime_mapping(draft))
    except Exception as exc:
        diagnostics.append(
            InitDiagnostic(
                severity="error",
                field=None,
                message=str(exc),
            )
        )

    return diagnostics


def write_project_config_from_draft(draft: InitDraft) -> Path:
    diagnostics = validate_init_draft(draft)
    errors = [item.message for item in diagnostics if item.severity == "error"]
    if errors:
        raise ValueError("; ".join(errors))

    return init_project_config(
        project_name=draft.project_name,
        log_dir=draft.log_dir,
        components=[component.value for component in draft.components],
        power_sampling_interval=draft.power_sampling_interval,
        intensity_sampling_interval=draft.intensity_sampling_interval,
        intensity_method=draft.intensity_method.value,
        location=draft.location,
        forecast_provider_name=draft.forecast_provider_name,
        static_carbon_intensity_g_per_kwh=draft.static_carbon_intensity_g_per_kwh,
        total_units=draft.total_units,
        unit_name=draft.unit_name,
        total_duration_s=draft.total_duration_s,
        predict_after_units=draft.predict_after_units,
        predict_after_seconds=draft.predict_after_seconds,
        predict_interval_s=draft.predict_interval_s,
    )
