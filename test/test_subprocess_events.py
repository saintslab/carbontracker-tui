from contextlib import contextmanager
import json
import logging
import queue
import sys
from datetime import datetime

from carbontracker.core.events import (
    ProcessExitedEvent,
    ProcessOutputEvent,
    ProcessStartedEvent,
    SpanStart,
    SpanStop,
)
from carbontracker.observers.providers.subprocess import SubprocessObserverThread


def drain(event_queue):
    events = []
    while not event_queue.empty():
        events.append(event_queue.get_nowait())
    return events


def marker(payload):
    return "carbontracker:" + json.dumps(payload, separators=(",", ":"))


class ListHandler(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


@contextmanager
def capture_subprocess_errors():
    logger = logging.getLogger("carbontracker.subprocess")
    handler = ListHandler()
    old_level = logger.level
    logger.setLevel(logging.ERROR)
    logger.addHandler(handler)
    try:
        yield handler.messages
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)


def observer_for_lines(lines, aggregation_queue=None):
    code = "lines = " + repr(lines) + "\nfor line in lines: print(line, flush=True)"
    return SubprocessObserverThread(
        command=[sys.executable, "-c", code],
        aggregation_queue=aggregation_queue or queue.Queue(),
        event_sink=[],
        notify_events=[],
        trace_id="trace-a",
        capture_output_events=True,
    )


def test_subprocess_start_exit_and_output_events_reach_watch_sink():
    sink = queue.Queue()
    observer = SubprocessObserverThread(
        command=[
            sys.executable,
            "-c",
            "import sys; print('out'); print('err', file=sys.stderr)",
        ],
        aggregation_queue=queue.Queue(),
        event_sink=[sink],
        notify_events=[],
        trace_id="trace-a",
        capture_output_events=True,
    )

    observer.run()
    events = drain(sink)

    started = [event for event in events if isinstance(event, ProcessStartedEvent)]
    exited = [event for event in events if isinstance(event, ProcessExitedEvent)]
    output = [event for event in events if isinstance(event, ProcessOutputEvent)]

    assert len(started) == 1
    assert started[0].pid > 0
    assert len(exited) == 1
    assert exited[0].return_code == 0
    assert exited[0].interrupted is False
    assert {(event.stream, event.line) for event in output} == {
        ("stdout", "out"),
        ("stderr", "err"),
    }


def test_subprocess_run_mode_passes_user_stdout_through(capsys):
    sink = queue.Queue()
    observer = SubprocessObserverThread(
        command=[sys.executable, "-c", "print('normal output')"],
        aggregation_queue=queue.Queue(),
        event_sink=[sink],
        notify_events=[],
        trace_id="trace-a",
        capture_output_events=False,
    )

    observer.run()
    events = drain(sink)

    assert "normal output" in capsys.readouterr().out
    assert not any(isinstance(event, ProcessOutputEvent) for event in events)


def test_json_start_creates_active_span():
    aggregation_queue = queue.Queue()
    observer = observer_for_lines(
        [
            marker({"type": "start", "span_id": "llm_call"}),
            marker({"type": "stop", "span_id": "llm_call"}),
        ],
        aggregation_queue=aggregation_queue,
    )

    observer.run()
    span_starts = [
        event for event in drain(aggregation_queue) if isinstance(event, SpanStart)
    ]

    assert [(event.span_id, event.parent_span_id) for event in span_starts] == [
        ("process", None),
        ("llm_call", "process"),
    ]


def test_json_start_supports_parent_span_id():
    aggregation_queue = queue.Queue()
    observer = observer_for_lines(
        [
            marker({"type": "start", "span_id": "batch"}),
            marker(
                {
                    "type": "start",
                    "span_id": "child_request",
                    "parent_span_id": "batch",
                }
            ),
            marker({"type": "stop", "span_id": "child_request"}),
            marker({"type": "stop", "span_id": "batch"}),
        ],
        aggregation_queue=aggregation_queue,
    )

    observer.run()
    span_starts = [
        event for event in drain(aggregation_queue) if isinstance(event, SpanStart)
    ]

    child = next(event for event in span_starts if event.span_id == "child_request")
    assert child.parent_span_id == "batch"


def test_json_markers_use_valid_timestamp():
    aggregation_queue = queue.Queue()
    started_at = "2026-01-01T12:00:01"
    ended_at = "2026-01-01T12:00:03"
    observer = observer_for_lines(
        [
            marker({"type": "start", "span_id": "timed", "timestamp": started_at}),
            marker({"type": "stop", "span_id": "timed", "timestamp": ended_at}),
        ],
        aggregation_queue=aggregation_queue,
    )

    observer.run()
    events = drain(aggregation_queue)
    start = next(
        event for event in events if isinstance(event, SpanStart) and event.span_id == "timed"
    )
    stop = next(
        event for event in events if isinstance(event, SpanStop) and event.span_id == "timed"
    )

    assert start.started_at == datetime.fromisoformat(started_at)
    assert stop.ended_at == datetime.fromisoformat(ended_at)


def test_json_marker_malformed_timestamp_falls_back_and_logs():
    aggregation_queue = queue.Queue()
    observer = observer_for_lines(
        [marker({"type": "start", "span_id": "timed", "timestamp": "not-a-date"})],
        aggregation_queue=aggregation_queue,
    )

    with capture_subprocess_errors() as errors:
        observer.run()

    starts = [
        event
        for event in drain(aggregation_queue)
        if isinstance(event, SpanStart) and event.span_id == "timed"
    ]
    assert len(starts) == 1
    assert any("Malformed carbontracker marker timestamp" in message for message in errors)


def test_json_start_with_inactive_parent_is_ignored_and_logged():
    aggregation_queue = queue.Queue()
    observer = observer_for_lines(
        [
            marker(
                {
                    "type": "start",
                    "span_id": "child_request",
                    "parent_span_id": "missing_parent",
                }
            )
        ],
        aggregation_queue=aggregation_queue,
    )

    with capture_subprocess_errors() as errors:
        observer.run()
    starts = [
        event
        for event in drain(aggregation_queue)
        if isinstance(event, SpanStart) and event.span_id == "child_request"
    ]

    assert starts == []
    assert any(
        "parent_span_id is not active: missing_parent" in message
        for message in errors
    )


def test_malformed_json_marker_is_rejected_and_logged():
    aggregation_queue = queue.Queue()
    observer = observer_for_lines(
        ["carbontracker:{not-json"],
        aggregation_queue=aggregation_queue,
    )

    with capture_subprocess_errors() as errors:
        observer.run()

    assert any("Malformed carbontracker JSON marker" in message for message in errors)


def test_unsupported_json_marker_type_is_rejected_and_logged():
    aggregation_queue = queue.Queue()
    observer = observer_for_lines(
        [marker({"type": "pause", "span_id": "api_call"})],
        aggregation_queue=aggregation_queue,
    )

    with capture_subprocess_errors() as errors:
        observer.run()

    assert any(
        "Unsupported carbontracker marker type" in message for message in errors
    )


def test_duplicate_active_json_start_is_ignored_and_logged():
    aggregation_queue = queue.Queue()
    observer = observer_for_lines(
        [
            marker({"type": "start", "span_id": "duplicate"}),
            marker({"type": "start", "span_id": "duplicate"}),
            marker({"type": "stop", "span_id": "duplicate"}),
        ],
        aggregation_queue=aggregation_queue,
    )

    with capture_subprocess_errors() as errors:
        observer.run()
    starts = [
        event
        for event in drain(aggregation_queue)
        if isinstance(event, SpanStart) and event.span_id == "duplicate"
    ]

    assert len(starts) == 1
    assert any("Duplicate active span_id" in message for message in errors)


def test_inactive_json_stop_is_ignored_and_logged():
    aggregation_queue = queue.Queue()
    observer = observer_for_lines(
        [marker({"type": "stop", "span_id": "missing"})],
        aggregation_queue=aggregation_queue,
    )

    with capture_subprocess_errors() as errors:
        observer.run()
    stops = [
        event
        for event in drain(aggregation_queue)
        if isinstance(event, SpanStop) and event.span_id == "missing"
    ]

    assert stops == []
    assert any("span_id is not active: missing" in message for message in errors)


def test_legacy_colon_marker_is_rejected_and_logged():
    aggregation_queue = queue.Queue()
    observer = observer_for_lines(
        ["carbontracker:legacy:start"],
        aggregation_queue=aggregation_queue,
    )

    with capture_subprocess_errors() as errors:
        observer.run()
    starts = [
        event
        for event in drain(aggregation_queue)
        if isinstance(event, SpanStart) and event.span_id == "legacy"
    ]

    assert starts == []
    assert any(
        "Unsupported carbontracker marker format" in message for message in errors
    )


def test_json_stop_captures_direct_external_emissions_from_stdout():
    aggregation_queue = queue.Queue()
    observer = observer_for_lines(
        [
            marker({"type": "start", "span_id": "db_query"}),
            marker(
                {
                    "type": "stop",
                    "span_id": "db_query",
                    "external_emissions_g": 0.004,
                }
            ),
        ],
        aggregation_queue=aggregation_queue,
    )

    observer.run()
    stop = next(
        event
        for event in drain(aggregation_queue)
        if isinstance(event, SpanStop) and event.span_id == "db_query"
    )

    assert stop.external_usage is not None
    assert stop.external_usage.energy_kwh is None
    assert stop.external_usage.emissions_g == 0.004


def test_json_stop_captures_external_energy_and_intensity_from_stdout():
    aggregation_queue = queue.Queue()
    observer = observer_for_lines(
        [
            marker({"type": "start", "span_id": "llm_call"}),
            marker(
                {
                    "type": "stop",
                    "span_id": "llm_call",
                    "external_energy_kwh": 0.00012,
                    "external_carbon_intensity_g_per_kwh": 65,
                }
            ),
        ],
        aggregation_queue=aggregation_queue,
    )

    observer.run()
    stop = next(
        event
        for event in drain(aggregation_queue)
        if isinstance(event, SpanStop) and event.span_id == "llm_call"
    )

    assert stop.external_usage is not None
    assert stop.external_usage.energy_kwh == 0.00012
    assert stop.external_usage.carbon_intensity_g_per_kwh == 65.0
