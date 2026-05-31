from __future__ import annotations

from pathlib import Path
from typing import Literal

from rich.console import Group
from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Static, Tab, Tabs

from carbontracker.dashboard.catalog import RunRecord, build_run_catalog
from carbontracker.tui.formatting import (
    ellipsize,
    format_command,
    format_duration,
    format_emissions,
    format_intensity,
    format_kwh,
)
from carbontracker.tui.theme import BASE_CSS, TABLE_CSS
from carbontracker.tui.widgets import TableColumn, TableRow, render_table_page

DashboardView = Literal["runs", "details"]
DASHBOARD_VIEWS: tuple[DashboardView, ...] = ("runs", "details")

RUN_COLUMNS = (
    TableColumn("Run name"),
    TableColumn("Start date", width=16),
    TableColumn("Power usage", width=11),
    TableColumn("Emissions", width=10),
    TableColumn("Duration", width=9),
    TableColumn("Average intensity", width=17),
)

UNITS_NOTE = (
    "Units: power_usage = kWh; emissions = gCO2eq; "
    "average_intensity = gCO2eq/kWh; totals include external_accounting"
)


class RunsTable(DataTable[object]):
    pass


class DashboardApp(App[None]):
    CSS = (
        BASE_CSS
        + TABLE_CSS
        + """
#project-header {
    height: 1;
    margin-bottom: 1;
    padding: 0 1;
    color: $text;
    text-style: bold;
}

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

#runs-view, #details-view {
    height: 1fr;
}

#runs-units-note {
    height: 1;
    color: $text-muted;
    padding: 0 1;
}

#details-text {
    height: 1fr;
    padding: 1 2;
    border: round #5f9f6a;
    overflow-y: auto;
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
        Binding("down", "nav_down", "Down", show=False, priority=True),
        Binding("up", "nav_up", "Up", show=False, priority=True),
        Binding("enter", "open_details", "Open details"),
    ]

    def __init__(
        self,
        log_dir: str | Path | None = None,
        *,
        runs: list[RunRecord] | tuple[RunRecord, ...] | None = None,
        view: DashboardView = "runs",
    ) -> None:
        super().__init__()
        self.log_dir = Path(log_dir) if log_dir is not None else None
        self.runs = list(runs) if runs is not None else build_run_catalog(self.log_dir or ".")
        self.view = view
        self.selected_log_path = str(self.runs[0].source_log_path) if self.runs else None

    def compose(self) -> ComposeResult:
        with Vertical(id="body"):
            yield Static(id="project-header")
            yield Tabs(
                Tab("Runs", id="runs"),
                Tab("Details", id="details"),
                active=self.view,
                id="view-tabs",
            )
            with Vertical(id="view-panel"):
                with Vertical(id="runs-view"):
                    yield RunsTable(id="runs-table")
                    yield Static(UNITS_NOTE, id="runs-units-note")
                with Vertical(id="details-view"):
                    yield Static(id="details-text")
        with Horizontal(id="footer-line"):
            yield Static(id="footer-left")
            yield Static(
                "enter details | up/down select | left/right tabs",
                id="footer-right",
            )

    def on_mount(self) -> None:
        self.title = "CarbonTracker dashboard"
        self.sub_title = "" if self.log_dir is None else str(self.log_dir)
        self.refresh_view()
        self.focus_runs_table()

    def action_previous_view(self) -> None:
        self.move_view(-1)

    def action_next_view(self) -> None:
        self.move_view(1)

    def action_nav_down(self) -> None:
        if self.view != "runs":
            self.view = "runs"
            self.refresh_view()
            self.focus_runs_table()
            return
        table = self.query_one("#runs-table", DataTable)
        table.action_cursor_down()
        self.sync_selection_from_table()

    def action_nav_up(self) -> None:
        if self.view != "runs":
            self.view = "runs"
            self.refresh_view()
            self.focus_runs_table()
            return
        table = self.query_one("#runs-table", DataTable)
        table.action_cursor_up()
        self.sync_selection_from_table()

    def action_open_details(self) -> None:
        self.view = "details"
        self.refresh_view()
        self.query_one("#view-tabs", Tabs).focus()

    def move_view(self, direction: int) -> None:
        current_index = DASHBOARD_VIEWS.index(self.view)
        self.view = DASHBOARD_VIEWS[(current_index + direction) % len(DASHBOARD_VIEWS)]
        self.refresh_view()
        if self.view == "runs":
            self.focus_runs_table()
        else:
            self.query_one("#view-tabs", Tabs).focus()

    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        if event.tab.id in DASHBOARD_VIEWS:
            self.view = event.tab.id  # type: ignore[assignment]
            self.refresh_view()
            if self.view == "runs":
                self.focus_runs_table()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id != "runs-table" or event.row_key is None:
            return
        self.selected_log_path = str(event.row_key.value)
        self.update_project_header()
        self.update_details()
        self.update_footer_line()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "runs-table" and event.row_key is not None:
            self.selected_log_path = str(event.row_key.value)
        self.action_open_details()

    def selected_run(self) -> RunRecord | None:
        if self.selected_log_path is None:
            return self.runs[0] if self.runs else None
        for run in self.runs:
            if str(run.source_log_path) == self.selected_log_path:
                return run
        return self.runs[0] if self.runs else None

    def sync_selection_from_table(self) -> None:
        table = self.query_one("#runs-table", DataTable)
        if table.cursor_row < 0 or table.cursor_row >= len(self.runs):
            return
        self.selected_log_path = str(self.runs[table.cursor_row].source_log_path)
        self.refresh_view()
        self.restore_table_cursor()

    def restore_table_cursor(self) -> None:
        table = self.query_one("#runs-table", DataTable)
        if self.selected_log_path is None:
            return
        for index, run in enumerate(self.runs):
            if str(run.source_log_path) == self.selected_log_path:
                table.move_cursor(row=index)
                return

    def focus_runs_table(self) -> None:
        self.set_focus(self.query_one("#runs-table", DataTable))

    def refresh_view(self) -> None:
        self.update_project_header()
        self.update_runs_table()
        self.update_details()
        self.update_active_view()
        self.update_footer_line()

    def update_project_header(self) -> None:
        selected = self.selected_run()
        text = Text()
        text.append("carbontracker dashboard", style="bold")
        text.append(" | ", style="dim bold")
        text.append("project_name: ", style="dim bold")
        text.append(
            selected.project_name if selected is not None else "none",
            style="bold",
        )
        self.query_one("#project-header", Static).update(text)

    def update_runs_table(self) -> None:
        table = self.query_one("#runs-table", RunsTable)
        table.border_title = "Runs"
        render_table_page(
            table,
            RUN_COLUMNS,
            run_rows(self.runs),
            empty_message="no JSONL run logs found",
        )
        self.restore_table_cursor()

    def update_details(self) -> None:
        self.query_one("#details-text", Static).update(details_text(self.selected_run()))

    def update_active_view(self) -> None:
        views = {
            "runs": self.query_one("#runs-view", Vertical),
            "details": self.query_one("#details-view", Vertical),
        }
        for name, widget in views.items():
            if name == self.view:
                widget.remove_class("hidden")
            else:
                widget.add_class("hidden")
        tabs = self.query_one("#view-tabs", Tabs)
        if tabs.active != self.view:
            tabs.active = self.view

    def update_footer_line(self) -> None:
        selected = self.selected_run()
        text = Text()
        text.append("selected: ", style="dim bold")
        text.append(selected.run_name if selected is not None else "none", style="bold")
        self.query_one("#footer-left", Static).update(text)
        self.query_one("#footer-right", Static).update(
            "enter details | up/down select | left/right tabs"
        )


def run_rows(runs: list[RunRecord]) -> list[TableRow]:
    rows: list[TableRow] = []
    for run in runs:
        rows.append(
            TableRow(
                (
                    run.run_name,
                    _format_start(run),
                    format_kwh(run.power_usage_kwh),
                    format_emissions(run.emissions_g),
                    format_duration(run.duration_s),
                    format_intensity(run.average_intensity_g_per_kwh),
                ),
                key=str(run.source_log_path),
            )
        )
    return rows


def details_text(run: RunRecord | None) -> Group:
    if run is None:
        return Group(Text("No runs found", style="bold yellow"))

    title = Text()
    title.append(run.run_name, style="bold cyan")
    title.append("  ")
    title.append(run.status, style=_status_style(run.status))

    metrics = Table.grid(expand=True)
    metrics.add_column(ratio=1)
    metrics.add_column(ratio=1)
    metrics.add_column(ratio=1)
    metrics.add_row(
        _metric_cell("power_usage", format_kwh(run.power_usage_kwh), "yellow"),
        _metric_cell("emissions", format_emissions(run.emissions_g), "magenta"),
        _metric_cell(
            "average_intensity",
            format_intensity(run.average_intensity_g_per_kwh),
            "cyan",
        ),
    )

    sections: list[object] = [
        title,
        "",
        metrics,
        "",
        _section_title("source"),
        _section_table(
            [
                ("timestamp", _format_start(run, with_seconds=True)),
                ("command", ellipsize(format_command(run.command), 90) or "--"),
                ("log_file_path", str(run.source_log_path)),
                (
                    "events / diagnostics",
                    f"{run.event_count} / {run.diagnostics_count}",
                ),
            ]
        ),
        "",
        _section_title("accounting"),
        _section_table(_accounting_rows(run)),
        "",
        _section_title("runtime config"),
        _section_table(
            [
                (
                    "duration / completed spans",
                    f"{format_duration(run.duration_s)} / {run.completed_spans_count}",
                ),
                ("components", ", ".join(run.components) or "--"),
                ("intensity_method", run.intensity_method or "--"),
                ("pue", "--" if run.pue is None else f"{run.pue:g}"),
                (
                    "sampling",
                    _sampling_text(run),
                ),
            ]
        ),
    ]

    prediction_rows = _prediction_rows(run)
    if prediction_rows:
        sections.extend(
            ["", _section_title("prediction target"), _section_table(prediction_rows)]
        )

    if run.diagnostic_messages:
        sections.extend(
            [
                "",
                _section_title("diagnostics"),
                _section_table(
                    [
                        (f"diagnostic {index}", ellipsize(message, 110))
                        for index, message in enumerate(run.diagnostic_messages, start=1)
                    ]
                ),
            ]
        )

    return Group(*sections)


def _metric_cell(label: str, value: str, style: str) -> Text:
    text = Text()
    text.append(f"{label}\n", style="dim")
    text.append(value, style=f"bold {style}")
    return text


def _section_table(rows: list[tuple[str, str]]) -> Table:
    table = Table.grid(expand=True)
    table.add_column(style="dim", width=28)
    table.add_column(ratio=1)
    for label, value in rows:
        table.add_row(label, value)
    return table


def _section_title(label: str) -> Text:
    text = Text()
    text.append(label, style="bold")
    return text


def _accounting_rows(run: RunRecord) -> list[tuple[str, str]]:
    rows = [
        (
            "session_stats",
            (
                f"{format_kwh(run.local_power_usage_kwh, unit=True)}, "
                f"{format_emissions(run.local_emissions_g, unit=True)}"
            ),
        ),
        (
            "external_accounting",
            (
                f"{format_kwh(run.external_power_usage_kwh, unit=True)}, "
                f"{format_emissions(run.external_emissions_g, unit=True)}"
                f"{_method_suffix(run)}"
            ),
        ),
    ]
    if run.unit_name is not None and run.unit_emissions_g is not None:
        rows.append(
            (
                f"per {run.unit_name}",
                (
                    f"{format_emissions(run.unit_emissions_g, unit=True)} "
                    f"over {run.total_units} units"
                ),
            )
        )
    return rows


def _prediction_rows(run: RunRecord) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    if run.total_units is not None:
        rows.append(("total_units", str(run.total_units)))
    if run.unit_name is not None:
        rows.append(("unit_name", run.unit_name))
    if run.total_duration_s is not None:
        rows.append(("total_duration_s", format_duration(run.total_duration_s)))
    if run.predict_after_units is not None:
        rows.append(("predict_after_units", str(run.predict_after_units)))
    if run.predict_after_seconds is not None:
        rows.append(
            ("predict_after_seconds", format_duration(run.predict_after_seconds))
        )
    if run.predict_interval_s is not None:
        rows.append(("predict_interval_s", format_duration(run.predict_interval_s)))
    return rows


def _method_suffix(run: RunRecord) -> str:
    if not run.external_accounting_methods:
        return ""
    return f" ({', '.join(run.external_accounting_methods)})"


def _sampling_text(run: RunRecord) -> str:
    power = (
        "--"
        if run.power_sampling_interval_s is None
        else f"{run.power_sampling_interval_s:g}s"
    )
    intensity = (
        "--"
        if run.intensity_sampling_interval_s is None
        else f"{run.intensity_sampling_interval_s:g}s"
    )
    return f"power {power}, intensity {intensity}"


def _format_start(run: RunRecord, *, with_seconds: bool = False) -> str:
    if run.started_at is None:
        return "--"
    return run.started_at.strftime("%Y-%m-%d %H:%M:%S" if with_seconds else "%m-%d %H:%M")


def _status_style(status: str) -> str:
    if status == "finished":
        return "bold green"
    if status == "failed":
        return "bold red"
    if status == "warning":
        return "bold yellow"
    if status == "running":
        return "bold cyan"
    return "bold yellow"
