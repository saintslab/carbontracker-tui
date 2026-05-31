import logging
import threading
from threading import Thread

from carbontracker.core.exceptions import WrongModeError
from carbontracker.core.runtime import RuntimeBundle
from carbontracker.core.stats import SessionFinalStats


class CarbonTrackerEngine:
    """
    Lifecycle controller CarbonTracker runtime.
    """

    def __init__(self, runtime: RuntimeBundle) -> None:
        self.runtime = runtime
        self.observer_thread = runtime.observer_thread
        self.aggregator_thread = runtime.aggregator_thread
        self.threads: list[Thread] = runtime.threads
        self.logger = logging.getLogger("carbontracker")
        self._finished = False

        for thread in self.threads:
            thread.start()

        self.logger.debug("Active threads list:")
        for thread in threading.enumerate():
            self.logger.debug(
                f" - Name: {thread.name}, ID: {thread.native_id}, Daemon: {thread.daemon}"
            )

    def _raise_if_finished(self) -> None:
        if self._finished:
            raise RuntimeError("CarbonTrackerEngine has already been finished")

    def epoch_start(self) -> None:
        self._raise_if_finished()
        if self.runtime.manual_controls is None:
            raise WrongModeError("epoch_start() is only available in Python API mode")
        self.runtime.manual_controls.epoch_start()

    def epoch_end(self) -> None:
        self._raise_if_finished()
        if self.runtime.manual_controls is None:
            raise WrongModeError("epoch_end() is only available in Python API mode")
        self.runtime.manual_controls.epoch_end()

    def wait_for_observer(self) -> None:
        self._raise_if_finished()
        self.observer_thread.join()

    def finish(self) -> SessionFinalStats:
        self._raise_if_finished()
        final_stats = None

        for thread in self.threads:
            result = thread.stop()
            if thread is self.aggregator_thread:
                final_stats = result
            thread.join()

        if self.runtime.manual_controls is not None:
            self.runtime.manual_controls.mark_finished()
        self._finished = True

        for thread in threading.enumerate():
            self.logger.debug(
                f" - Name: {thread.name}, ID: {thread.native_id}, Daemon: {thread.daemon}"
            )

        if final_stats is None:
            raise RuntimeError("Aggregator did not return final session stats")
        return final_stats
