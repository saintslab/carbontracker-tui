import time
import sys
import json


def marker(payload):
    return "carbontracker:" + json.dumps(payload, separators=(",", ":"))


def simulate_training():
    print("Starting training script...", flush=True)
    
    # Outer span (Epoch 1)
    print(marker({"type": "start", "span_id": "epoch_1"}), flush=True)
    time.sleep(0.5)
    
    # Nested inner span (Batch 1)
    print(
        marker(
            {
                "type": "start",
                "span_id": "batch_1",
                "parent_span_id": "epoch_1",
            }
        ),
        flush=True,
    )
    time.sleep(0.5)
    print(marker({"type": "stop", "span_id": "batch_1"}), flush=True)
    
    # Nested inner span (Batch 2)
    print(
        marker(
            {
                "type": "start",
                "span_id": "batch_2",
                "parent_span_id": "epoch_1",
            }
        ),
        flush=True,
    )
    time.sleep(0.5)
    print(marker({"type": "stop", "span_id": "batch_2"}), flush=True)
    
    # Close outer span
    print(marker({"type": "stop", "span_id": "epoch_1"}), flush=True)
    print("Training complete.", flush=True)


if __name__ == "__main__":
    simulate_training()
