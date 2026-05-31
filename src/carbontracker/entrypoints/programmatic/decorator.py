from typing import Callable

from carbontracker.core.execution_guard import GuardVerdict
from carbontracker.core.types import BreachAction, Component, IntensityMethod, Location


def track(
    *,
    project_name: str | None = None,
    log_dir: str | None = None,
    ignore_errors: bool | None = None,
    components: list[Component] | None = None,
    pue: float | None = None,
    location: Location | None = None,
    intensity_method: IntensityMethod | None = None,
    static_carbon_intensity_g_per_kwh: float | None = None,
    power_sampling_interval: float | None = None,
    intensity_sampling_interval: float | None = None,
    predict_after: int | None = None,
    predict_interval: float | None = None,
    total_units: int | None = None,
    unit_name: str | None = None,
    max_energy_kwh: float | None = None,
    max_emissions_g: float | None = None,
    use_predicted_values: bool | None = None,
    action_on_breach: BreachAction | None = None,
    on_breach_callback: Callable[[GuardVerdict], None] | None = None,
):
    """
    Decorator entrypoint placeholder.
    """
    raise NotImplementedError(
        "The @track decorator is not supported yet. Use the CarbonTracker Python API "
        "or the CLI command wrapper until decorator spans are reworked."
    )
