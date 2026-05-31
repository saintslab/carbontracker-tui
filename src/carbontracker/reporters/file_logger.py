from pathlib import Path
from queue import Queue
from threading import Thread

from carbontracker.core.event_codec import event_to_json
from carbontracker.core.events import ProcessOutputEvent, TrackerEvent

class FileWriterThread(Thread):
    def __init__(
        self,
        log_dir: str,
        run_name: str,
        event_queue: Queue[TrackerEvent],
        persist_process_output: bool = False,
        log_file_path: str | Path | None = None,
    ):
        super().__init__()
        self.log_dir = log_dir
        self.run_name = run_name
        self.event_queue = event_queue
        self.persist_process_output = persist_process_output
        self.name = "File Logger Thread"
       
        # Making it a daemon thread ensures it automatically shuts down 
        # when your main application exits
        self.daemon = True
        
        if log_file_path is None:
            log_dir_path = Path(self.log_dir)
            log_dir_path.mkdir(parents=True, exist_ok=True)
            run_name = self.run_name if self.run_name else "carbontracker"
            self.log_file_path = log_dir_path / f"{run_name}_events.jsonl"
        else:
            self.log_file_path = Path(log_file_path)
            self.log_file_path.parent.mkdir(parents=True, exist_ok=True)

    def stop(self) -> None:
        self.event_queue.put(None)

    def run(self) -> None:
        """Continuously monitors the queue and writes full events to a JSONL file."""
        with open(self.log_file_path, "a") as log_file:
            while True:
                event = self.event_queue.get()

                # Close signal
                if event is None:
                    self.event_queue.task_done()
                    break
                    
                try:
                    if (
                        isinstance(event, ProcessOutputEvent)
                        and not self.persist_process_output
                    ):
                        continue

                    json_str = event_to_json(event)
                    log_file.write(json_str + "\n")
                    log_file.flush()
                except Exception:
                    # Fallback or silent failure for logging errors to not block application
                    pass
                finally:
                    # Tell the queue that processing for this item is complete
                    self.event_queue.task_done()
