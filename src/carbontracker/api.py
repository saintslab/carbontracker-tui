from typing import Callable

from carbontracker.config.config import LogLevel
from carbontracker.core.engine import CarbonTrackerEngine
from carbontracker.core.execution_guard import GuardVerdict
from carbontracker.core.runtime import (
    RuntimeOptions,
    build_manual_runtime,
    generate_default_run_name,
)
from carbontracker.core.stats import SessionFinalStats
from carbontracker.core.types import BreachAction, Component, IntensityMethod, Location


def _reject_unsupported_runtime_features(
    *,
    max_energy_kwh: float | None,
    max_emissions_g: float | None,
    use_predicted_values: bool,
    action_on_breach: BreachAction,
    on_breach_callback: Callable[[GuardVerdict], None] | None,
) -> None:
    unsupported: list[str] = []
    if max_energy_kwh is not None:
        unsupported.append("max_energy_kwh")
    if max_emissions_g is not None:
        unsupported.append("max_emissions_g")
    if use_predicted_values:
        unsupported.append("use_predicted_values")
    if action_on_breach not in (BreachAction.LOG, "log"):
        unsupported.append("action_on_breach")
    if on_breach_callback is not None:
        unsupported.append("on_breach_callback")

    if unsupported:
        joined = ", ".join(unsupported)
        raise NotImplementedError(
            f"Prediction and budget options are not supported yet: {joined}"
        )


class CarbonTracker:
    """
    Programmatic epoch-based carbon tracking API.
    """

    def __init__(
        self,
        epochs: int,
        *,
        project_name: str | None = None,
        run_name: str | None = None,
        log_dir: str = "carbontracker_logs/",
        ignore_errors: bool = True,
        log_level: LogLevel = LogLevel.WARNING,
        session_stat_interval_s: float = 1.0,
        components: list[Component] | None = None,
        pue: float = 1.1,
        power_sampling_interval: float = 15.0,
        intensity_method: IntensityMethod = IntensityMethod.AUTO,
        intensity_sampling_interval: float = 900.0,
        location: Location | None = None,
        static_carbon_intensity_g_per_kwh: float | None = None,
        api_keys: dict[str, str] | None = None,
        total_units: int | None = None,
        total_duration_s: float | None = None,
        predict_after_units: int | None = None,
        predict_after_seconds: float | None = None,
        predict_after_n_units: int | None = None,
        predict_interval_s: float | None = None,
        unit_name: str | None = None,
        max_energy_kwh: float | None = None,
        max_emissions_g: float | None = None,
        use_predicted_values: bool = False,
        action_on_breach: BreachAction = BreachAction.LOG,
        on_breach_callback: Callable[[GuardVerdict], None] | None = None,
    ) -> None:
        if epochs <= 0:
            raise ValueError("epochs must be greater than zero")

        _reject_unsupported_runtime_features(
            max_energy_kwh=max_energy_kwh,
            max_emissions_g=max_emissions_g,
            use_predicted_values=use_predicted_values,
            action_on_breach=action_on_breach,
            on_breach_callback=on_breach_callback,
        )
        if predict_after_units is not None and predict_after_n_units is not None:
            raise ValueError(
                "Use only one of predict_after_units or predict_after_n_units"
            )
        resolved_predict_after_units = (
            predict_after_units
            if predict_after_units is not None
            else predict_after_n_units
        )

        resolved_components = (
            components
            if components is not None
            else [Component.CPU, Component.GPU, Component.RAM]
        )
        resolved_project_name = (
            project_name if project_name is not None else "carbontracker"
        )
        resolved_run_name = (
            run_name if run_name is not None else generate_default_run_name()
        )
        resolved_total_units = total_units
        if resolved_total_units is None and total_duration_s is None:
            resolved_total_units = epochs

        self._options = RuntimeOptions(
            project_name=resolved_project_name,
            run_name=resolved_run_name,
            ignore_errors=ignore_errors,
            log_level=log_level,
            log_dir=log_dir,
            session_stat_interval_s=session_stat_interval_s,
            components=resolved_components,
            pue=pue,
            power_sampling_interval=power_sampling_interval,
            intensity_method=intensity_method,
            intensity_sampling_interval=intensity_sampling_interval,
            location=location,
            static_carbon_intensity_g_per_kwh=static_carbon_intensity_g_per_kwh,
            api_keys=api_keys,
            total_units=resolved_total_units,
            unit_name=unit_name,
            total_duration_s=total_duration_s,
            predict_after_units=resolved_predict_after_units,
            predict_after_seconds=predict_after_seconds,
            predict_interval_s=predict_interval_s,
        )
        runtime = build_manual_runtime(self._options)
        self._engine = CarbonTrackerEngine(runtime)

    def epoch_start(self) -> None:
        self._engine.epoch_start()

    def epoch_end(self) -> None:
        self._engine.epoch_end()

    def finish(self) -> SessionFinalStats:
        return self._engine.finish()


__all__ = ["CarbonTracker"]
