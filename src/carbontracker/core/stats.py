from dataclasses import field
from pydantic.dataclasses import dataclass

@dataclass(frozen=True)
class SpanStats:
    """Stats calculated strictly for a specific span/epoch."""
    avg_watt: float
    min_watt: float
    max_watt: float
    avg_intensity: float
    min_intensity: float
    max_intensity: float
    power_usage_pr_device: dict[str, float]
    emissions_g: float           # Emissions generated during this span
    power_usage_kwh: float       # Power consumed during this span
    power_measurements_count: int
    intensity_measurements_count: int

@dataclass(frozen=True)
class SessionStatsData:
    """Global stats reflecting the current state of the entire tracker session."""
    current_wattage: float
    current_intensity: float
    total_emissions_g: float     # Cumulative so far
    total_power_usage_kwh: float # Cumulative so far
    power_usage_pr_device: dict[str, float] = field(default_factory=dict)

@dataclass(frozen=True)
class SessionFinalStats:
    """Final aggregated statistics for the entire session."""
    total_emissions_g: float
    total_power_usage_kwh: float
    duration_s: float
    completed_spans_count: int
