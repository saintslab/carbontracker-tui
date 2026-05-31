from dataclasses import dataclass
from enum import Enum
from typing import Callable
from carbontracker.core.types import Location, Component, IntensityMethod, BreachAction


class ProviderType(str, Enum):
    POWER = "power"
    INTENSITY = "intensity"


class LogLevel(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class SessionMode(str, Enum):
    PYTHON_API = "python_api"
    PYTHON_DECORATOR = "python_decorator"
    SUBPROCESS = "subprocess"
    SLURM = "slurm"

    @property
    def is_python(self) -> bool:
        return self in (SessionMode.PYTHON_API, SessionMode.PYTHON_DECORATOR)

    @property
    def is_process(self) -> bool:
        return self in (SessionMode.SUBPROCESS, SessionMode.SLURM)


@dataclass(frozen=True)
class SessionConfig:
    # Session identity
    mode: SessionMode
    run_name: str
    command: list[str] | None
    ignore_errors: bool
    log_level: LogLevel
    log_dir: str
    session_stat_interval_s: float
    # Hardware & Power
    components: list[Component]
    pue: float
    power_sampling_interval: float
    devices_by_pids: list[str]
    # Carbon Intensity
    intensity_method: IntensityMethod
    intensity_sampling_interval: float
    location: Location | None
    static_carbon_intensity_g_per_kwh: float | None
    api_keys: dict[str, str] | None
    # Prediction
    forecast_provider_name: str | None
    unit_name: str | None
    total_units: int | None
    total_duration: int | None
    predict_after_n_units: int | None
    predict_after_n_secounds: int | None
    predict_interval_s: float | None
    # Budget / Guardrails
    max_energy_kwh: float | None
    max_emissions_g: float | None
    use_predicted_values: bool
    action_on_breach: BreachAction
    on_breach_callback: Callable | None

    def __post_init__(self):
        if self.total_units is not None and self.total_units <= 0:
            raise ValueError("total_units must be greater than zero")
            
        if self.total_duration is not None and self.total_duration <= 0:
            raise ValueError("total_duration must be greater than zero")

        if self.predict_after_n_units is not None and self.predict_after_n_units <= 0:
            raise ValueError("predict_after_n_units must be greater than zero")
