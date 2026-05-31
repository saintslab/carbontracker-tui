from dataclasses import dataclass
import logging
@dataclass(frozen=True)
class ResolutionStep:
    action: str          # e.g. "provider_resolved", "no_provider"
    detail: str          # human-readable
    level: str           # "info", "warning", "success"


def print_resolution_steps(steps: list[ResolutionStep], logger: logging.Logger) -> None:
    """Prints the resolution steps using the provided logger."""
    for step in steps:
        if step.level == "success":
            logger.info(f"Success: {step.detail}")
        elif step.level == "warning":
            logger.warning(f"Warning: {step.detail}")
        else:
            logger.info(f"Info: {step.detail}")


def log_resolution_steps(steps: list[ResolutionStep], logger: logging.Logger) -> None:
    print_resolution_steps(steps, logger)
