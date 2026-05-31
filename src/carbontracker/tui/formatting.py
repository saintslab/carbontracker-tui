from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime


def ellipsize(value: object, width: int) -> str:
    text = str(value)
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    return text[: width - 3] + "..."


def format_command(command: Sequence[str] | tuple[str, ...] | None) -> str:
    if not command:
        return ""
    return " ".join(str(part) for part in command)


def format_duration(seconds: float | int | None) -> str:
    if seconds is None:
        return "waiting"
    total = max(int(seconds), 0)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def format_short_duration(seconds: float | int | None) -> str:
    if seconds is None:
        return "--"
    total = max(int(seconds), 0)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def format_watts(value: float | None, *, unit: bool = False) -> str:
    if value is None:
        return "--"
    suffix = " W" if unit else ""
    return f"{value:.1f}{suffix}"


def format_kwh(value: float | None, *, unit: bool = False) -> str:
    if value is None:
        return "--"
    suffix = " kWh" if unit else ""
    return f"{value:.4f}{suffix}"


def format_emissions(value: float | None, *, unit: bool = False) -> str:
    if value is None:
        return "--"
    suffix = " gCO2eq" if unit else ""
    return f"{value:.2f}{suffix}"


def format_intensity(value: float | None, *, unit: bool = False) -> str:
    if value is None:
        return "--"
    suffix = " gCO2eq/kWh" if unit else ""
    return f"{value:.1f}{suffix}"


def format_percent(value: float | None) -> str:
    if value is None:
        return "--"
    return f"{value:.1f}"


def format_time(value: datetime | None) -> str:
    if value is None:
        return "--:--:--"
    return value.strftime("%H:%M:%S")


def last_seen_text(value: datetime | None) -> str:
    if value is None:
        return "waiting"
    return value.strftime("%H:%M:%S")


def status_style(status: str) -> str:
    if status == "running":
        return "bold green"
    if status == "finished":
        return "bold cyan"
    if status == "finishing":
        return "bold yellow"
    return "bold yellow"

