import logging
import queue
from datetime import datetime
from threading import Thread
from typing import Any

from carbontracker.core.events import (
    FinishedSession,
    GuardEvent,
    MeasurementEvent,
    PredictionEvent,
    SessionCurrentStatsEvent,
    SessionMetadata,
    SpanProfileEvent,
    SpanStart,
    SpanStop,
    TrackerEvent,
)
from carbontracker.core.execution_guard import BudgetGuard
from carbontracker.core.external import compute_external_accounting
from carbontracker.core.prediction import PredictionEngine, PredictionResult
from carbontracker.core.profiling import (
    PowerSample,
    SpanPowerProfiler,
    SpanProfile,
    WindowProfile,
    span_profile_to_stats,
)
from carbontracker.core.spans import SpanRecord
from carbontracker.core.stats import SessionFinalStats, SessionStatsData, SpanStats
from carbontracker.providers.carbon_intensity.intensity_provider import IntensityMeasurementData
from carbontracker.providers.carbon_intensity_forecast.forecast_provider import (
    IntensityForecastData,
)
from carbontracker.providers.power.power_provider import PowerMeasurementData

logger = logging.getLogger("carbontracker.aggregator")


class AggregatorThread(Thread):
    def __init__(
        self,
        session_stats_interval_s: float,
        aggregation_queue: queue.Queue[TrackerEvent],
        event_sink: list[queue.Queue[TrackerEvent]],
        profiler: SpanPowerProfiler,
        session_metadata: SessionMetadata | None = None,
        prediction_engine: PredictionEngine | None = None,
        budget_guard: BudgetGuard | None = None,
    ) -> None:
        super().__init__()
        self.aggregation_queue = aggregation_queue
        self.event_sink = event_sink
        self._profiler = profiler
        self._session_metadata = session_metadata or SessionMetadata(
            project_name="carbontracker",
            run_name="carbontracker",
            log_dir="carbontracker_logs/",
            log_file_path="carbontracker_logs/carbontracker_events.jsonl",
        )
        self._prediction_engine = prediction_engine
        self._budget_guard = budget_guard

        self.daemon = True
        self.name = "aggregator_thread"

        self.session_stats_interval_s = session_stats_interval_s

        self._active_spans: dict[str, SpanRecord] = {}
        self._completed_spans: list[SpanRecord] = []
        self._power_samples: list[PowerSample] = []
        self._intensity_measurements: list[IntensityMeasurementData] = []
        self._forecast: IntensityForecastData | None = None
        self._span_profiles: dict[str, SpanProfile] = {}
        self._session_start_time = datetime.now()
        self._span_stats_history: list[SpanStats] = []
        self._completed_span_names: list[str] = []
        self._completed_root_span_names: list[str] = []
        self._span_durations_s: list[float] = []
        self._last_stats_emit = datetime.min

        self._cumulative_emissions_g = 0.0
        self._cumulative_power_kwh = 0.0
        self._completed_root_spans_count = 0

    def stop(self) -> SessionFinalStats:
        self.aggregation_queue.put(None)
        self._refresh_cumulative_stats(datetime.now())

        final_stats = SessionFinalStats(
            total_emissions_g=self._cumulative_emissions_g,
            total_power_usage_kwh=self._cumulative_power_kwh,
            duration_s=sum(self._span_durations_s),
            completed_spans_count=self._completed_root_spans_count,
        )

        event = FinishedSession(
            timestamp=datetime.now(),
            project_name=self._session_metadata.project_name,
            run_name=self._session_metadata.run_name,
            log_dir=self._session_metadata.log_dir,
            log_file_path=self._session_metadata.log_file_path,
            command=self._session_metadata.command,
            trace_id=self._session_metadata.trace_id,
            config_summary=self._session_metadata.config_summary,
            stats=final_stats,
        )
        self._emit_event(event)

        return final_stats

    def run(self) -> None:
        while True:
            try:
                event = self.aggregation_queue.get(timeout=self.session_stats_interval_s)
                if event is None:
                    break

                if isinstance(event, SpanStart):
                    self._handle_span_start(event)

                elif isinstance(event, SpanStop):
                    self._handle_span_stop(event)

                elif isinstance(event, MeasurementEvent):
                    self._handle_measurement(event)

            except queue.Empty:
                self._emit_session_stats()
                self._update_predictions()

            except Exception as e:
                logger.error(f"Aggregator encountered error processing event: {e}")

    def _emit_event(self, event: TrackerEvent) -> None:
        for sink in self.event_sink:
            sink.put(event)

    def _handle_span_start(self, event: SpanStart) -> None :
        self._active_spans[event.span_id] = SpanRecord.from_start(event)

    def _handle_measurement(self, event: MeasurementEvent[Any]) -> None:
        if isinstance(event.data, PowerMeasurementData):
            self._power_samples.extend(event.data.samples)
        elif isinstance(event.data, IntensityMeasurementData):
            self._intensity_measurements.append(event.data)
        elif isinstance(event.data, IntensityForecastData):
            self._forecast = event.data
        else:
            logger.error("Unknown measurement event: %s", event)

        self._emit_event(event)

    def _handle_span_stop(self, event: SpanStop) -> None:
        span_id = event.span_id
        if span_id not in self._active_spans:
            logger.error("SpanStop triggered, but could not find active span_id")
            return

        span = self._active_spans.pop(span_id)
        span.close(event)
        span.external_accounting = compute_external_accounting(span.external_usage)
        if span.external_usage is not None and span.external_accounting is None:
            logger.error("Invalid external usage for span_id %s", span_id)
        self._completed_spans.append(span)

        profile = self._profiler.profile_span(
            span=span,
            all_spans=self._completed_spans,
            power_samples=self._power_samples,
            intensity_measurements=self._intensity_measurements,
        )
        self._span_profiles[span_id] = profile
        stats = span_profile_to_stats(profile)

        stats_event = SpanProfileEvent(
            created_at=datetime.now(),
            span_id=span_id,
            parent_span_id=span.parent_span_id,
            started_at=span.started_at,
            ended_at=span.ended_at,
            profile=profile,
            stats=stats,
            external_accounting=span.external_accounting,
        )
        self._emit_event(stats_event)

        self._span_stats_history.append(stats)
        self._completed_span_names.append(span_id)
        if span.parent_span_id is None:
            self._completed_root_spans_count += 1
            self._completed_root_span_names.append(span_id)
            self._span_durations_s.append(
                (span.ended_at - span.started_at).total_seconds()
            )

    def _update_predictions(self) -> None:
        if self._prediction_engine is None:
            return

        now = datetime.now()
        run_duration_s = (now - self._session_start_time).total_seconds()

        should_predict = self._prediction_engine.should_predict(
            now=now,
            run_duration_s=run_duration_s,
            completed_span_names=self._completed_span_names,
            completed_root_span_names=self._completed_root_span_names,
        )

        if not should_predict:
            return

        prediction = self._prediction_engine.predict(
            span_stats=self._span_stats_history,
            run_duration_s=run_duration_s,
            current_cumulative_energy_kwh=self._cumulative_power_kwh,
            current_cumulative_emissions_g=self._cumulative_emissions_g,
            forecast=self._forecast,
            completed_span_names=self._completed_span_names,
            completed_root_span_names=self._completed_root_span_names,
        )

        pred_event = PredictionEvent(created_at=datetime.now(), result=prediction)
        self._emit_event(pred_event)

        if self._budget_guard is not None and self._budget_guard.use_predicted_values:
            self._check_guard(prediction=prediction)

    def _emit_session_stats(self) -> None:
        if (not self._power_samples) or (not self._intensity_measurements):
            return
        now = datetime.now()
        time_since_last_update_s = (now - self._last_stats_emit).total_seconds()
        if time_since_last_update_s < self.session_stats_interval_s:
            return

        self._last_stats_emit = now
        profile = self._refresh_cumulative_stats(now)

        stats = SessionStatsData(
            current_wattage=profile.current_wattage,
            current_intensity=profile.current_intensity,
            total_emissions_g=self._cumulative_emissions_g,
            total_power_usage_kwh=self._cumulative_power_kwh,
            power_usage_pr_device=profile.current_power_by_device,
        )
        event = SessionCurrentStatsEvent(timestamp=now, stats=stats)
        self._emit_event(event)

        if self._budget_guard is not None and not self._budget_guard.use_predicted_values:
            self._check_guard(prediction=None)

    def _check_guard(self, prediction: PredictionResult | None = None) -> None:
        if self._budget_guard is None:
            return

        verdict = self._budget_guard.check(
            cumulative_energy_kwh=self._cumulative_power_kwh,
            cumulative_emissions_g=self._cumulative_emissions_g,
            prediction=prediction,
        )
        guard_event = GuardEvent(
            created_at=datetime.now(),
            verdict=verdict,
            prediction=prediction,
        )
        self._emit_event(guard_event)

    def _refresh_cumulative_stats(self, now: datetime) -> WindowProfile:
        profile = self._profiler.profile_window(
            start=self._session_start_time,
            end=now,
            power_samples=self._power_samples,
            intensity_measurements=self._intensity_measurements,
        )
        self._cumulative_power_kwh = profile.gross_energy_kwh
        self._cumulative_emissions_g = profile.gross_emissions_g
        return profile
