from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from pathlib import Path

from carbontracker.core.event_codec import events_from_jsonl_lines
from carbontracker.core.events import TrackerEvent


def read_jsonl_events(path: str | Path) -> list[TrackerEvent]:
    with open(path) as handle:
        return list(events_from_jsonl_lines(handle))


def iter_jsonl_events(
    path: str | Path,
    *,
    tail: bool = False,
    poll_interval_s: float = 0.25,
    stop_when: Callable[[], bool] | None = None,
) -> Iterator[TrackerEvent]:
    with open(path) as handle:
        while True:
            line = handle.readline()
            if line:
                yield from events_from_jsonl_lines([line])
                continue
            if not tail or (stop_when is not None and stop_when()):
                break
            time.sleep(poll_interval_s)
