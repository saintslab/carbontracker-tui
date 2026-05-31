from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from rich.style import Style
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Sparkline, Static, Tab, Tabs

from carbontracker.core.events import (
    DiagnosticEvent,
    FinishedSession,
    MeasurementEvent,
    PredictionEvent,
    ProcessExitedEvent,
    ProcessOutputEvent,
    ProcessStartedEvent,
    SessionCurrentStatsEvent,
    SpanProfileEvent,
    SpanStart,
    SpanStop,
    StartedSession,
    TrackerEvent,
)
from carbontracker.tui.formatting import (
    ellipsize,
    format_command,
    format_duration,
    format_emissions,
    format_intensity,
    format_kwh,
    format_percent,
    format_short_duration,
    format_time,
    format_watts,
    last_seen_text,
    status_style,
)
from carbontracker.tui.sources import JsonlEventSource
from carbontracker.tui.theme import BASE_CSS, TABLE_CSS
from carbontracker.tui.widgets import (
    PagedRows,
    TableColumn,
    TableRow,
    page_status,
    render_table_page,
)
from carbontracker.watch.reducer import EventRow, SpanState, WatchState, apply_event


WatchView = Literal["stats", "power", "forecast", "spans", "events"]
WATCH_VIEWS: tuple[WatchView, ...] = ("stats", "power", "forecast", "spans", "events")


DEVICE_COLUMNS = (
    TableColumn("Device"),
    TableColumn("Source", width=14),
    TableColumn("Current W", width=10),
    TableColumn("Avg W", width=8),
    TableColumn("Min W", width=8),
    TableColumn("Max W", width=8),
    TableColumn("Total kWh", width=10),
    TableColumn("% Total", width=8),
)
FORECAST_COLUMNS = (
    TableColumn("Time", width=8),
    TableColumn("gCO2eq/kWh", width=13),
    TableColumn("vs avg", width=8),
)
SPAN_COLUMNS = (
    TableColumn("Span"),
    TableColumn("Status", width=10),
    TableColumn("Reliable", width=9),
    TableColumn("Duration", width=10),
    TableColumn("Energy kWh", width=11),
    TableColumn("CO2eq", width=9),
)


def stats_values(state: WatchState) -> dict[str, str]:
    expected_runtime = (
        None
        if state.projected_duration_s is None
        else state.runtime_s + state.projected_duration_s
    )
    return {
        "current_power": "waiting"
        if state.current_wattage is None
        else format_watts(state.current_wattage, unit=True),
        "current_intensity": "waiting"
        if state.current_intensity is None
        else format_intensity(state.current_intensity, unit=True),
        "current_energy": format_kwh(state.total_power_usage_kwh, unit=True),
        "current_emissions": format_emissions(state.total_emissions_g, unit=True),
        "current_runtime": format_duration(state.runtime_s),
        "expected_energy": "waiting"
        if state.projected_energy_kwh is None
        else format_kwh(state.projected_energy_kwh, unit=True),
        "expected_emissions": "waiting"
        if state.projected_emissions_g is None
        else format_emissions(state.projected_emissions_g, unit=True),
        "expected_runtime": "waiting"
        if expected_runtime is None
        else format_duration(expected_runtime),
        "last_prediction": last_seen_text(state.last_prediction_at),
        "last_forecast": last_seen_text(state.last_forecast_at),
    }


def device_rows(state: WatchState) -> list[TableRow]:
    devices = sorted(state.devices.values(), key=lambda item: item.device_id)
    if not devices:
        return []
    total_kwh = sum(device.total_energy_kwh for device in devices)
    rows: list[TableRow] = []
    for device in devices:
        device_kwh = device.total_energy_kwh
        share = (device_kwh / total_kwh * 100) if total_kwh > 0 else None
        rows.append(
            TableRow(
                (
                    device.label or device.device_id,
                    device.source,
                    format_watts(device.watts),
                    format_watts(device.watts_avg),
                    format_watts(device.watts_min),
                    format_watts(device.watts_max),
                    format_kwh(device_kwh),
                    format_percent(share),
                ),
                key=device.device_id,
            )
        )

    rows.append(
        TableRow(
            (
                "Aggregate",
                "",
                format_watts(sum(device.watts for device in devices)),
                format_watts(sum(device.watts_avg or 0.0 for device in devices)),
                format_watts(sum(device.watts_min or 0.0 for device in devices)),
                format_watts(sum(device.watts_max or 0.0 for device in devices)),
                format_kwh(total_kwh),
                "100.0" if total_kwh > 0 else "--",
            ),
            key="aggregate",
        )
    )
    return rows


def forecast_rows(state: WatchState) -> list[TableRow]:
    if not state.forecast_points:
        return []
    values = [value for _, value in state.forecast_points]
    avg = sum(values) / len(values)
    rows: list[TableRow] = []
    for index, (timestamp, value) in enumerate(state.forecast_points):
        diff = value - avg
        marker = "low" if diff < -2 else "high" if diff > 2 else "avg"
        rows.append(
            TableRow(
                (timestamp.strftime("%H:%M"), f"{value:.0f}", marker),
                key=f"forecast-{index}",
            )
        )
    return rows


def _span_depth(span: SpanState, spans: dict[str, SpanState]) -> int:
    depth = 0
    seen: set[str] = set()
    parent_id = span.parent_span_id
    while parent_id and parent_id in spans and parent_id not in seen:
        seen.add(parent_id)
        depth += 1
        parent_id = spans[parent_id].parent_span_id
    return depth


def span_rows(state: WatchState) -> list[TableRow]:
    rows: list[TableRow] = []
    spans = sorted(
        state.spans.values(),
        key=lambda item: (item.started_at is None, item.started_at, item.span_id),
    )
    for span in spans:
        depth = _span_depth(span, state.spans)
        reliable = "--" if span.reliable is None else str(span.reliable).lower()
        rows.append(
            TableRow(
                (
                    f"{'  ' * depth}{span.span_id}",
                    span.status,
                    reliable,
                    _span_duration_text(span, state),
                    format_kwh(span.power_usage_kwh),
                    format_emissions(span.emissions_g),
                ),
                key=span.span_id,
            )
        )
    return rows


def event_rows(state: WatchState, *, description_width: int = 80) -> list[TableRow]:
    rows: list[TableRow] = []
    for index, row in enumerate(state.events):
        rows.append(
            TableRow(
                (
                    format_time(row.timestamp),
                    ellipsize(row.kind, 22),
                    ellipsize(describe_event(row), description_width),
                ),
                key=f"event-{index}",
            )
        )
    return rows


def describe_event(row: EventRow) -> str:
    event = row.event
    if isinstance(event, ProcessOutputEvent):
        return f"{event.stream}: {event.line}"
    if isinstance(event, DiagnosticEvent):
        return f"{event.severity.value}: {event.message}"
    if isinstance(event, StartedSession):
        command = format_command(event.command)
        return f"started {event.project_name}/{event.run_name} {command}".strip()
    if isinstance(event, ProcessStartedEvent):
        return f"pid {event.pid} {format_command(event.command)}".strip()
    if isinstance(event, ProcessExitedEvent):
        interrupted = " interrupted" if event.interrupted else ""
        return f"process exited {event.return_code}{interrupted}"
    if isinstance(event, FinishedSession):
        return (
            f"finished in {format_short_duration(event.stats.duration_s)}; "
            f"{format_kwh(event.stats.total_power_usage_kwh, unit=True)}, "
            f"{format_emissions(event.stats.total_emissions_g, unit=True)}"
        )
    if isinstance(event, SessionCurrentStatsEvent):
        return (
            f"{format_watts(event.stats.current_wattage, unit=True)}, "
            f"{format_kwh(event.stats.total_power_usage_kwh, unit=True)}, "
            f"{format_emissions(event.stats.total_emissions_g, unit=True)}"
        )
    if isinstance(event, MeasurementEvent):
        return f"measurement from {event.provider_name}"
    if isinstance(event, SpanStart):
        return f"span started {event.span_id}"
    if isinstance(event, SpanStop):
        return f"span stopped {event.span_id}"
    if isinstance(event, SpanProfileEvent):
        return f"span profiled {event.span_id}"
    if isinstance(event, PredictionEvent) and event.result is not None:
        return (
            f"prediction "
            f"{format_kwh(event.result.projected_total_energy_kwh, unit=True)}, "
            f"{format_emissions(event.result.projected_total_emissions_g, unit=True)}"
        )
    return row.kind


def _span_duration_text(span: SpanState, state: WatchState) -> str:
    if span.duration_s is not None:
        return format_short_duration(span.duration_s)
    if span.started_at is not None and state.latest_at is not None:
        return format_short_duration(
            max((state.latest_at - span.started_at).total_seconds(), 0.0)
        )
    return "--"


class PowerUsageTable(DataTable[object]):
    def _get_row_style(self, row_index: int, base_style: Style) -> Style:
        row_style = super()._get_row_style(row_index, base_style)
        if row_index >= 0:
            row = self.ordered_rows[row_index]
            if row.key.value == "aggregate":
                return Style(color="white", bgcolor="#2f6f44", bold=True)
        return row_style


class WatchApp(App[None]):
    CSS = (
        BASE_CSS
        + TABLE_CSS
        + """
#view-tabs {
    height: 1;
    margin-bottom: 1;
    color: #5f9f6a;
}

#view-tabs Underline {
    display: none;
}

#view-panel {
    height: 1fr;
    padding: 0 1;
}

#stats-panel {
    height: 1fr;
    padding: 0;
    content-align: center middle;
}

#metric-row {
    height: 5;
}

#metric-meta {
    height: 1;
    margin-top: 1;
    color: $text-muted;
    text-align: center;
}

.metric-card {
    width: 1fr;
    height: 5;
    border: round #5f9f6a;
    margin-right: 1;
    content-align: center middle;
    text-align: center;
}

#stats-panel, #devices, #forecast-panel, #span-table, #event-table {
    height: 1fr;
}

#forecast-summary {
    height: 2;
    color: $text-muted;
}

#forecast-sparkline {
    height: 4;
    margin-top: 1;
}

Tab.-active {
    background: #5f9f6a 25%;
    color: $text;
}

Tabs:focus Tab.-active {
    background: #5f9f6a 70%;
    color: $text;
}
"""
    )

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("left", "previous_view", "Previous view", show=False, priority=True),
        Binding("right", "next_view", "Next view", show=False, priority=True),
        Binding("down", "nav_down", "Enter table", show=False, priority=True),
        Binding("up", "nav_up", "Leave table", show=False, priority=True),
        Binding("pageup", "page_up", "Older page", show=False, priority=True),
        Binding("pagedown", "page_down", "Newer page", show=False, priority=True),
        Binding("ctrl+home", "jump_start", "Oldest", show=False, priority=True),
        Binding("ctrl+end", "jump_end", "Newest", show=False, priority=True),
        Binding("r", "refresh_source", "Refresh"),
        Binding("space", "pause", "Pause"),
    ]

    def __init__(
        self,
        path: str | Path,
        *,
        tail: bool = True,
        poll_interval_s: float = 0.5,
        initial_events: Sequence[TrackerEvent] | None = None,
        view: WatchView = "stats",
    ) -> None:
        super().__init__()
        self.path = Path(path)
        self.tail = tail
        self.poll_interval_s = poll_interval_s
        self.view = view
        self.paused = False
        self.state = WatchState()
        self.source = JsonlEventSource(self.path)
        self.event_pager = PagedRows[TableRow](page_size=200)
        self.span_pager = PagedRows[TableRow](page_size=100)
        self.forecast_pager = PagedRows[TableRow](page_size=100)
        for event in initial_events or ():
            apply_event(self.state, event)

    def compose(self) -> ComposeResult:
        with Vertical(id="body"):
            yield Tabs(
                Tab("Stats", id="stats"),
                Tab("Power Usage", id="power"),
                Tab("Intensity Forecast", id="forecast"),
                Tab("Spans", id="spans"),
                Tab("Events", id="events"),
                active=self.view,
                id="view-tabs",
            )
            with Vertical(id="view-panel"):
                with Vertical(id="stats-panel"):
                    with Horizontal(id="metric-row"):
                        yield Static(id="metric-energy", classes="metric-card")
                        yield Static(id="metric-emissions", classes="metric-card")
                        yield Static(id="metric-runtime", classes="metric-card")
                        yield Static(id="metric-power", classes="metric-card")
                        yield Static(id="metric-intensity", classes="metric-card")
                    yield Static(id="metric-meta")
                yield PowerUsageTable(id="devices")
                with Vertical(id="forecast-panel"):
                    yield DataTable(id="forecast-table")
                    yield Static(id="forecast-summary")
                    yield Sparkline(
                        id="forecast-sparkline",
                        min_color="green",
                        max_color="yellow",
                    )
                yield DataTable(id="span-table")
                yield DataTable(id="event-table")
        with Horizontal(id="footer-line"):
            yield Static(id="footer-left")
            yield Static("left/right tabs, page keys rows", id="footer-right")

    def on_mount(self) -> None:
        self.title = "CarbonTracker watch"
        self.sub_title = str(self.path)
        self.poll_source()
        if self.tail:
            self.set_interval(self.poll_interval_s, self.poll_source)
        self.refresh_view()
        self.focus_tabs()

    def poll_source(self) -> None:
        if self.paused:
            return
        events = self.source.read_available()
        if not events:
            return
        for event in events:
            apply_event(self.state, event)
        self.refresh_view()

    def action_refresh_source(self) -> None:
        self.poll_source()

    def action_previous_view(self) -> None:
        self.move_view(-1)

    def action_next_view(self) -> None:
        self.move_view(1)

    def action_nav_down(self) -> None:
        focused = self.focused
        if isinstance(focused, DataTable):
            focused.action_cursor_down()
            return
        self.focus_active_table()

    def action_nav_up(self) -> None:
        focused = self.focused
        if isinstance(focused, DataTable):
            if focused.cursor_coordinate.row <= 0:
                self.focus_tabs()
            else:
                focused.action_cursor_up()
            return
        self.focus_tabs()

    def action_page_up(self) -> None:
        pager = self.active_pager()
        if pager is None:
            return
        pager.page_up()
        self.refresh_view()
        self.focus_active_table()

    def action_page_down(self) -> None:
        pager = self.active_pager()
        if pager is None:
            return
        pager.page_down()
        self.refresh_view()
        self.focus_active_table()

    def action_jump_start(self) -> None:
        pager = self.active_pager()
        if pager is None:
            return
        pager.jump_start()
        self.refresh_view()
        self.focus_active_table()

    def action_jump_end(self) -> None:
        pager = self.active_pager()
        if pager is None:
            return
        pager.jump_end()
        self.refresh_view()
        self.focus_active_table()

    def action_pause(self) -> None:
        self.paused = not self.paused
        self.refresh_view()

    def move_view(self, direction: int) -> None:
        current_index = WATCH_VIEWS.index(self.view)
        self.view = WATCH_VIEWS[(current_index + direction) % len(WATCH_VIEWS)]
        self.refresh_view()
        self.focus_tabs()

    def focus_tabs(self) -> None:
        self.set_focus(self.query_one("#view-tabs", Tabs))

    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        if event.tab.id in WATCH_VIEWS:
            self.view = event.tab.id  # type: ignore[assignment]
            self.refresh_view()

    def active_pager(self) -> PagedRows[TableRow] | None:
        if self.view == "events":
            return self.event_pager
        if self.view == "spans":
            return self.span_pager
        if self.view == "forecast":
            return self.forecast_pager
        return None

    def active_table_selector(self) -> str | None:
        return {
            "power": "#devices",
            "forecast": "#forecast-table",
            "spans": "#span-table",
            "events": "#event-table",
        }.get(self.view)

    def focus_active_table(self) -> None:
        selector = self.active_table_selector()
        if selector is not None:
            self.set_focus(self.query_one(selector, DataTable))

    def refresh_view(self) -> None:
        self.update_footer_line()
        self.update_stats()
        self.update_devices()
        self.update_forecast()
        self.update_spans()
        self.update_events()
        self.update_active_view()

    def update_active_view(self) -> None:
        widgets = {
            "stats": self.query_one("#stats-panel", Vertical),
            "power": self.query_one("#devices", DataTable),
            "forecast": self.query_one("#forecast-panel", Vertical),
            "spans": self.query_one("#span-table", DataTable),
            "events": self.query_one("#event-table", DataTable),
        }
        for name, widget in widgets.items():
            if name == self.view:
                widget.remove_class("hidden")
            else:
                widget.add_class("hidden")
        tabs = self.query_one("#view-tabs", Tabs)
        if tabs.active != self.view:
            tabs.active = self.view

    def update_footer_line(self) -> None:
        status = self.state.status
        if self.paused:
            status += " paused"
        text = Text()
        text.append("status: ", style="dim bold")
        text.append(status, style=status_style(self.state.status))
        text.append(" | run: ", style="dim bold")
        text.append(self.state.run_name, style="bold")
        if self.state.diagnostics:
            text.append(" | diagnostics: ", style="dim bold")
            text.append(str(len(self.state.diagnostics)), style="bold yellow")
        self.query_one("#footer-left", Static).update(text)

    def update_stats(self) -> None:
        stats = stats_values(self.state)
        cards = [
            (
                "#metric-energy",
                "Energy usage",
                stats["current_energy"],
                stats["expected_energy"],
                "yellow",
            ),
            (
                "#metric-emissions",
                "Emissions",
                stats["current_emissions"],
                stats["expected_emissions"],
                "magenta",
            ),
            (
                "#metric-runtime",
                "Runtime",
                stats["current_runtime"],
                stats["expected_runtime"],
                "white",
            ),
            ("#metric-power", "Current power", stats["current_power"], "live", "green"),
            (
                "#metric-intensity",
                "Current intensity",
                stats["current_intensity"],
                "live",
                "cyan",
            ),
        ]
        for selector, title, current, expected, style in cards:
            text = Text()
            text.append(f"{title}\n", style="dim")
            text.append(f"{current}\n", style=f"bold {style}")
            text.append(f"exp {expected}" if expected != "live" else "live", style="dim")
            self.query_one(selector, Static).update(text)
        self.query_one("#metric-meta", Static).update(
            f"last pred. {stats['last_prediction']}    "
            f"last forecast {stats['last_forecast']}"
        )

    def update_devices(self) -> None:
        table = self.query_one("#devices", DataTable)
        table.border_title = "Devices"
        render_table_page(
            table,
            DEVICE_COLUMNS,
            device_rows(self.state),
            empty_message="waiting for power samples",
        )

    def update_forecast(self) -> None:
        table = self.query_one("#forecast-table", DataTable)
        summary = self.query_one("#forecast-summary", Static)
        sparkline = self.query_one("#forecast-sparkline", Sparkline)
        rows = forecast_rows(self.state)
        self.forecast_pager.set_items(rows)
        page = self.forecast_pager.visible_items()
        table.border_title = f"Intensity Forecast ({page_status(page)})"
        render_table_page(
            table,
            FORECAST_COLUMNS,
            page.items,
            empty_message="waiting for forecast points",
        )
        if not self.state.forecast_points:
            summary.update("waiting for forecast points")
            sparkline.data = []
            return
        values = [value for _, value in self.state.forecast_points]
        window = (
            f"{self.state.forecast_points[0][0].strftime('%H:%M')}"
            f"-{self.state.forecast_points[-1][0].strftime('%H:%M')}"
        )
        summary.update(
            f"range {min(values):.0f}-{max(values):.0f} gCO2eq/kWh  "
            f"avg {sum(values) / len(values):.0f}  window {window}"
        )
        sparkline.data = values

    def update_spans(self) -> None:
        table = self.query_one("#span-table", DataTable)
        rows = span_rows(self.state)
        self.span_pager.set_items(rows)
        page = self.span_pager.visible_items()
        table.border_title = f"Spans ({page_status(page)})"
        render_table_page(
            table,
            SPAN_COLUMNS,
            page.items,
            empty_message="waiting for span activity",
        )

    def update_events(self) -> None:
        table = self.query_one("#event-table", DataTable)
        description_width = max(self.size.width - 40, 32)
        rows = event_rows(self.state, description_width=description_width)
        self.event_pager.set_items(rows)
        page = self.event_pager.visible_items()
        table.border_title = f"Events ({page_status(page)})"
        render_table_page(
            table,
            (
                TableColumn("Time", width=8),
                TableColumn("Kind", width=22),
                TableColumn("Event", width=description_width),
            ),
            page.items,
            empty_message="waiting for events",
        )

