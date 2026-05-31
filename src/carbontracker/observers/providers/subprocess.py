import json
import logging
import os
import queue
import subprocess
import sys
import uuid
from datetime import datetime
from threading import Event, Thread
from typing import List, Optional

from carbontracker.core.events import (
    ProcessExitedEvent,
    ProcessOutputEvent,
    ProcessStartedEvent,
    TrackerEvent,
)
from carbontracker.core.external import ExternalUsage
from carbontracker.core.markers import Marker
from carbontracker.observers.base import ObserverThread

logger = logging.getLogger("carbontracker.subprocess")


class SubprocessObserverThread(ObserverThread):
    def __init__(
        self,
        command: List[str],
        aggregation_queue: "queue.Queue[TrackerEvent]",
        event_sink: "List[queue.Queue[TrackerEvent]]",
        notify_events: List[Event],
        trace_id: str | None = None,
        capture_output_events: bool = False,
    ) -> None:
        super().__init__(
            aggregation_queue=aggregation_queue,
            event_sink=event_sink,
            notify_events=notify_events,
            name="subprocess"
        )
        self.command = command
        self._active_span_ids: set[str] = set()
        self._active_span_parents: dict[str, str | None] = {}
        self._active_span_order: list[str] = []
        self._trace_id = trace_id if trace_id is not None else str(uuid.uuid4())
        self.capture_output_events = capture_output_events

    def _make_marker(
        self,
        span_id: str,
        parent_span_id: Optional[str],
        timestamp: datetime | None = None,
    ) -> Marker:
        return Marker(
            marker_id=str(uuid.uuid4()),
            trace_id=self._trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            timestamp=timestamp if timestamp is not None else datetime.now(),
        )

    def _emit_event(self, event: TrackerEvent) -> None:
        for sink in self.event_sink:
            sink.put(event)

    def _handle_stdout_line(self, line: str) -> None:
        if line.startswith("carbontracker:"):
            self._handle_marker(line.strip())
            return
        if self.capture_output_events:
            self._emit_event(
                ProcessOutputEvent(
                    timestamp=datetime.now(),
                    stream="stdout",
                    line=line.rstrip("\n"),
                    trace_id=self._trace_id,
                )
            )
        else:
            sys.stdout.write(line)
            sys.stdout.flush()

    def _handle_stderr_line(self, line: str) -> None:
        if self.capture_output_events:
            self._emit_event(
                ProcessOutputEvent(
                    timestamp=datetime.now(),
                    stream="stderr",
                    line=line.rstrip("\n"),
                    trace_id=self._trace_id,
                )
            )
        else:
            sys.stderr.write(line)
            sys.stderr.flush()

    def run(self) -> None:
        if not self.command:
            return

        # Emit root span start
        root_span = "process"
        self._activate_span(root_span, parent_span_id=None)
        self._emit_start(self._make_marker(root_span, parent_span_id=None))

        env = os.environ.copy()
        # Ensure python processes are unbuffered so we get markers immediately
        env["PYTHONUNBUFFERED"] = "1"
        env["CARBONTRACKER_TRACE_ID"] = self._trace_id
        
        proc = subprocess.Popen(
            self.command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE if self.capture_output_events else None,
            env=env,
            text=True,
            bufsize=1,  # line-buffered
        )
        self._emit_event(
            ProcessStartedEvent(
                timestamp=datetime.now(),
                command=tuple(self.command),
                pid=proc.pid,
                trace_id=self._trace_id,
            )
        )

        stdout_thread = None
        stderr_thread = None
        interrupted = False

        if proc.stdout is not None:
            stdout_thread = Thread(
                target=self._drain_stream,
                args=(proc.stdout, self._handle_stdout_line),
                daemon=True,
            )
            stdout_thread.start()

        if proc.stderr is not None:
            stderr_thread = Thread(
                target=self._drain_stream,
                args=(proc.stderr, self._handle_stderr_line),
                daemon=True,
            )
            stderr_thread.start()

        try:
            while proc.poll() is None:
                if self._stop_event.wait(timeout=0.1):
                    interrupted = True
                    proc.terminate()
                    break
            proc.wait()
        except KeyboardInterrupt:
            interrupted = True
            proc.terminate()
            proc.wait()
            raise
        finally:
            if stdout_thread is not None:
                stdout_thread.join()
            if stderr_thread is not None:
                stderr_thread.join()
            self._emit_event(
                ProcessExitedEvent(
                    timestamp=datetime.now(),
                    return_code=proc.returncode,
                    interrupted=interrupted,
                    trace_id=self._trace_id,
                )
            )

        # Close any unclosed spans (in reverse start order)
        while self._active_span_order:
            span = self._active_span_order.pop()
            parent = self._active_span_parents.pop(span, None)
            self._active_span_ids.discard(span)
            self._emit_stop(self._make_marker(span, parent_span_id=parent))

    def _drain_stream(self, stream, line_handler) -> None:
        try:
            for line in stream:
                line_handler(line)
        finally:
            stream.close()

    def _handle_marker(self, line: str) -> None:
        payload = line.removeprefix("carbontracker:")
        if not payload.startswith("{"):
            logger.error("Unsupported carbontracker marker format: %s", line)
            return

        try:
            marker = json.loads(payload)
        except json.JSONDecodeError as exc:
            logger.error("Malformed carbontracker JSON marker: %s", exc.msg)
            return

        if not isinstance(marker, dict):
            logger.error("Carbontracker marker must decode to a JSON object")
            return

        marker_type = marker.get("type")
        if marker_type == "start":
            self._handle_start_marker(marker)
        elif marker_type == "stop":
            self._handle_stop_marker(marker)
        else:
            logger.error("Unsupported carbontracker marker type: %r", marker_type)

    def _handle_start_marker(self, marker: dict[str, object]) -> None:
        allowed_fields = {"type", "span_id", "parent_span_id", "timestamp"}
        unexpected_fields = set(marker) - allowed_fields
        if unexpected_fields:
            logger.error(
                "Unsupported fields in carbontracker start marker: %s",
                sorted(unexpected_fields),
            )
            return

        span_id = self._span_id_from_marker(marker)
        if span_id is None:
            return

        if span_id in self._active_span_ids:
            logger.error("Duplicate active span_id in carbontracker marker: %s", span_id)
            return

        parent_span_id = marker.get("parent_span_id", "process")
        if not isinstance(parent_span_id, str) or not parent_span_id:
            logger.error("Carbontracker start marker parent_span_id must be a string")
            return
        if parent_span_id not in self._active_span_ids:
            logger.error(
                "Carbontracker start marker parent_span_id is not active: %s",
                parent_span_id,
            )
            return

        event_time = self._timestamp_from_marker(marker)
        self._activate_span(span_id, parent_span_id=parent_span_id)
        self._emit_start(
            self._make_marker(
                span_id,
                parent_span_id=parent_span_id,
                timestamp=event_time,
            )
        )

    def _handle_stop_marker(self, marker: dict[str, object]) -> None:
        allowed_fields = {
            "type",
            "span_id",
            "timestamp",
            "external_energy_kwh",
            "external_emissions_g",
            "external_carbon_intensity_g_per_kwh",
        }
        unexpected_fields = set(marker) - allowed_fields
        if unexpected_fields:
            logger.error(
                "Unsupported fields in carbontracker stop marker: %s",
                sorted(unexpected_fields),
            )
            return

        span_id = self._span_id_from_marker(marker)
        if span_id is None:
            return

        if span_id not in self._active_span_ids:
            logger.error("Carbontracker stop marker span_id is not active: %s", span_id)
            return

        event_time = self._timestamp_from_marker(marker)
        external_usage = self._external_usage_from_marker(marker)
        self._deactivate_span(span_id)
        parent_span_id = self._active_span_parents.pop(span_id, None)
        self._emit_stop(
            self._make_marker(
                span_id,
                parent_span_id=parent_span_id,
                timestamp=event_time,
            ),
            external_usage=external_usage,
        )

    def _span_id_from_marker(self, marker: dict[str, object]) -> str | None:
        span_id = marker.get("span_id")
        if not isinstance(span_id, str) or not span_id:
            logger.error("Carbontracker marker span_id must be a non-empty string")
            return None
        return span_id

    def _timestamp_from_marker(self, marker: dict[str, object]) -> datetime:
        value = marker.get("timestamp")
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                logger.error("Malformed carbontracker marker timestamp: %s", value)
                return datetime.now()
        if self._is_json_number(value):
            try:
                return datetime.fromtimestamp(float(value))
            except (OverflowError, OSError, ValueError):
                logger.error("Malformed carbontracker marker timestamp: %s", value)
                return datetime.now()
        if value is not None:
            logger.error("Carbontracker marker timestamp must be an ISO string or epoch number")
        return datetime.now()

    def _external_usage_from_marker(
        self, marker: dict[str, object]
    ) -> ExternalUsage | None:
        external_fields = {
            "external_energy_kwh": "energy_kwh",
            "external_emissions_g": "emissions_g",
            "external_carbon_intensity_g_per_kwh": "carbon_intensity_g_per_kwh",
        }
        if not any(field in marker for field in external_fields):
            return None

        values: dict[str, float | None] = {
            "energy_kwh": None,
            "emissions_g": None,
            "carbon_intensity_g_per_kwh": None,
        }
        for marker_field, usage_field in external_fields.items():
            if marker_field not in marker:
                continue
            value = marker[marker_field]
            if not self._is_json_number(value):
                logger.error(
                    "Carbontracker external field must be numeric: %s",
                    marker_field,
                )
                continue
            values[usage_field] = float(value)

        return ExternalUsage(**values)

    def _is_json_number(self, value: object) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _activate_span(self, span_id: str, parent_span_id: str | None) -> None:
        self._active_span_ids.add(span_id)
        self._active_span_parents[span_id] = parent_span_id
        self._active_span_order.append(span_id)

    def _deactivate_span(self, span_id: str) -> None:
        self._active_span_ids.remove(span_id)
        self._active_span_order.remove(span_id)
