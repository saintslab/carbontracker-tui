import queue
from threading import Thread, Event
from typing import TypeVar, Generic
from carbontracker.providers.data_provider import DataProvider, MeasurementData
from carbontracker.core.events import TrackerEvent, MeasurementEvent

TData = TypeVar("TData", bound=MeasurementData)


class DataProviderThread(Thread, Generic[TData]):
    """
    Statically typed, autonomous base provider thread.
    """

    def __init__(
        self,
        sample_interval: float,
        providers: list[DataProvider[TData]],
        aggregation_queue: "queue.Queue[TrackerEvent]",
        notify_event: Event,
        initial_work: bool = False,
    ) -> None:
        super().__init__()
        self.sample_interval_s = sample_interval
        self.providers = providers
        self.aggregation_queue = aggregation_queue
        self._trigger_event = notify_event
        self._initial_work: bool = initial_work
        self._stop_event = Event()
        self.daemon = True
        self.name: str = "_".join([provider.name for provider in self.providers])

    def stop(self) -> None:
        self._stop_event.set()
        self._trigger_event.set()

    def run(self) -> None:
        if self._initial_work:
            self._work()

        while not self._stop_event.is_set():
            # Blocks until sample_interval passes (in-between fetch) OR trigger_event is set (forced fetch)
            # Goal is to ensure that we always fetch after new epoch & we can have rergular samples
            self._trigger_event.wait(timeout=self.sample_interval_s)
            self._work()
            self._trigger_event.clear()

    def _work(self) -> None:
        for provider in self.providers:
            measurement = provider.fetch()
            event = MeasurementEvent(
                provider_name=provider.name,
                timestamp=measurement.timestamp,
                data=measurement,
            )
            self.aggregation_queue.put(event)
