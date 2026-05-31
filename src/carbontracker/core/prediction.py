from datetime import datetime
from enum import Enum
from pydantic import BaseModel
import logging

from carbontracker.core.stats import SpanStats
from carbontracker.providers.carbon_intensity_forecast.forecast_provider import IntensityForecastData

logger = logging.getLogger("carbontracker.prediction")



class PredictionResult(BaseModel):
    completed_units: int | None = None
    total_units: int | None = None
    total_duration_s: float | None = None
    run_duration_s: float

    estimated_duration_left_s: float
    projected_total_energy_kwh: float
    projected_total_emissions_g: float


class PredictionMode(str, Enum):
    TIME = "time"
    UNIT = "unit"


class PredictionEngine:
    def __init__(
        self,
        total_units: int | None,
        unit_name: str | None,
        total_duration_s: float | None,
        predict_after_seconds: float | None = None,
        predict_after_units: int | None = None,
        predict_interval_s: float | None = None,
    ):
        self.total_units = total_units
        self.total_duration_s = total_duration_s
        self.unit_of_interest = unit_name
        self.predict_after_seconds = predict_after_seconds
        self.predict_after_units = predict_after_units
        self.predict_interval_s = predict_interval_s
        self.mode: PredictionMode = self._define_mode(total_units, unit_name, total_duration_s)

        # Internal state:
        self._last_prediction_time: datetime | None = None
        self._has_predicted = False

    @staticmethod
    def _define_mode(total_units,unit_name,total_duration) -> PredictionMode:
        if total_units is not None:
            return PredictionMode.UNIT
        elif total_duration is not None:
            return PredictionMode.TIME

        raise ValueError(
            "Cannot define prediction mode without total_units or total_duration."
        )

    def predict(
        self,
        span_stats: list[SpanStats],
        run_duration_s: float,
        current_cumulative_energy_kwh: float,
        current_cumulative_emissions_g: float,
        forecast: IntensityForecastData | None,
        completed_span_names: list[str],
        completed_root_span_names: list[str],
    ) -> PredictionResult:
        self._last_prediction_time = datetime.now()
        self._has_predicted = True

        if self.mode == PredictionMode.UNIT:
            return self.predict_unit_based(
                span_stats,
                run_duration_s,
                current_cumulative_energy_kwh,
                current_cumulative_emissions_g,
                forecast,
                completed_span_names,
                completed_root_span_names,
            )
        else:
            return self.predict_time_based(
                run_duration_s,
                current_cumulative_energy_kwh,
                current_cumulative_emissions_g,
                forecast,
            )

    def should_predict(
        self,
        now: datetime,
        run_duration_s: float,
        completed_span_names: list[str],
        completed_root_span_names: list[str],
    ) -> bool:
        if (
            self.predict_interval_s is not None
            and self.predict_interval_s > 0
            and self._last_prediction_time is not None
        ):
            since_last = (now - self._last_prediction_time).total_seconds()
            if since_last < self.predict_interval_s:
                return False

        if self.predict_after_seconds is not None:
            if run_duration_s < self.predict_after_seconds:
                return False

        if self.mode == PredictionMode.UNIT and self.predict_after_units is not None:
            completed_units = self._completed_units(
                completed_span_names=completed_span_names,
                completed_root_span_names=completed_root_span_names,
            )
            if completed_units < self.predict_after_units:
                return False

        if self.predict_interval_s is not None and self.predict_interval_s <= 0:
            return not self._has_predicted

        return True

    def _completed_units(
        self,
        completed_span_names: list[str],
        completed_root_span_names: list[str],
    ) -> int:
        if self.unit_of_interest is None:
            return len(completed_root_span_names)
        return sum(1 for name in completed_span_names if name == self.unit_of_interest)

    def predict_unit_based(
        self,
        span_stats: list[SpanStats],
        run_duration_s: float,
        current_cumulative_energy_kwh: float,
        current_cumulative_emissions_g: float,
        forecast: IntensityForecastData | None,
        completed_span_names: list[str],
        completed_root_span_names: list[str],
    ) -> PredictionResult:

        completed_units = self._completed_units(
            completed_span_names=completed_span_names,
            completed_root_span_names=completed_root_span_names,
        )
        
        if completed_units > 0:
            avg_duration_per_unit = run_duration_s / completed_units
            avg_energy_per_unit = current_cumulative_energy_kwh / completed_units
        else:
            avg_duration_per_unit = 0.0
            avg_energy_per_unit = 0.0

        total_units = self.total_units if self.total_units is not None else 0
        remaining_units = max(0, total_units - completed_units)
        estimated_duration_left = avg_duration_per_unit * remaining_units
        projected_remaining_energy = avg_energy_per_unit * remaining_units

        if forecast is not None:
            projected_remaining_emissions = (
                projected_remaining_energy * forecast.average_intensity_g_per_kwh
            )
        else:
            logger.warning(
                "No forecast available. Falling back to extrapolating past emissions intensity."
            )
            if completed_units > 0:
                avg_emissions_per_unit = current_cumulative_emissions_g / completed_units
            else:
                avg_emissions_per_unit = 0.0
            projected_remaining_emissions = avg_emissions_per_unit * remaining_units

        return PredictionResult(
            completed_units=completed_units,
            total_units=total_units,
            run_duration_s=run_duration_s,
            estimated_duration_left_s=estimated_duration_left,
            projected_total_energy_kwh=current_cumulative_energy_kwh
            + projected_remaining_energy,
            projected_total_emissions_g=current_cumulative_emissions_g
            + projected_remaining_emissions,
        )

    def predict_time_based(
        self,
        run_duration_s: float,
        current_cumulative_energy_kwh: float,
        current_cumulative_emissions_g: float,
        forecast: IntensityForecastData | None = None,
    ) -> PredictionResult:

        if run_duration_s > 0:
            avg_energy_per_second = current_cumulative_energy_kwh / run_duration_s
        else:
            avg_energy_per_second = 0.0

        if self.total_duration_s is not None:
            remaining_duration_s = max(0.0, self.total_duration_s - run_duration_s)
        else:
            remaining_duration_s = 0.0
            
        projected_remaining_energy = avg_energy_per_second * remaining_duration_s

        if forecast is not None:
            projected_remaining_emissions = (
                projected_remaining_energy * forecast.average_intensity_g_per_kwh
            )
        else:
            logger.warning(
                "No forecast available. Falling back to extrapolating past emissions intensity."
            )
            if run_duration_s > 0:
                avg_emissions_per_second = current_cumulative_emissions_g / run_duration_s
            else:
                avg_emissions_per_second = 0.0
            projected_remaining_emissions = (
                avg_emissions_per_second * remaining_duration_s
            )

        return PredictionResult(
            total_duration_s=self.total_duration_s,
            run_duration_s=run_duration_s,
            estimated_duration_left_s=remaining_duration_s,
            projected_total_energy_kwh=current_cumulative_energy_kwh
            + projected_remaining_energy,
            projected_total_emissions_g=current_cumulative_emissions_g
            + projected_remaining_emissions,
        )
