import queue
from typing import Dict, Callable, List
from threading import Event

from carbontracker.config.config import SessionMode
from carbontracker.core.events import TrackerEvent
from carbontracker.observers.base import ObserverThread
from carbontracker.observers.providers.manual import ManualObserverThread
from carbontracker.observers.providers.subprocess import SubprocessObserverThread

def observer_factory(
    mode: SessionMode,
    command: List[str] | None,
    aggregation_queue: "queue.Queue[TrackerEvent]",
    event_sink: "List[queue.Queue[TrackerEvent]]",
    notify_events: List[Event]
) -> ObserverThread:
    
    if mode == SessionMode.PYTHON_API:
        return ManualObserverThread(aggregation_queue, event_sink, notify_events)
    elif mode == SessionMode.PYTHON_DECORATOR:
        raise NotImplementedError("python-decorator mode is not yet implemented")
    elif mode == SessionMode.SUBPROCESS:
        if command is None:
            raise ValueError("Command is required for SUBPROCESS mode")
        return SubprocessObserverThread(command, aggregation_queue, event_sink, notify_events)
    else:
        raise ValueError(f"Unknown observer mode: {mode}")
