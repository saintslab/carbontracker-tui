import ast
import asyncio
import importlib
import sys
from datetime import datetime, timedelta
from pathlib import Path

from click.testing import CliRunner
from textual.widgets import DataTable

from carbontracker.core.events import ProcessOutputEvent, ProcessStartedEvent, StartedSession
from carbontracker.dashboard.catalog import RunRecord
from carbontracker.entrypoints.cli import cli as cli_module
from carbontracker.tui.dashboard_app import DashboardApp
from carbontracker.tui.formatting import format_duration, format_kwh
from carbontracker.tui.init_app import InitApp, parse_location
from carbontracker.tui.watch_app import WatchApp, event_rows, stats_values
from carbontracker.tui.widgets import PagedRows
from carbontracker.watch.reducer import WatchState, apply_event


SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "carbontracker"


def test_production_code_does_not_import_tui_mockups():
    offenders = []
    for path in SRC_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "tui_mockups" or alias.name.startswith(
                        "tui_mockups."
                    ):
                        offenders.append((path, node.lineno, alias.name))
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "tui_mockups" or module.startswith("tui_mockups."):
                    offenders.append((path, node.lineno, module))

    assert offenders == []


def test_tui_modules_import_without_mockup_modules():
    for name in list(sys.modules):
        if name == "tui_mockups" or name.startswith("tui_mockups."):
            del sys.modules[name]

    for module_name in [
        "carbontracker.tui.theme",
        "carbontracker.tui.formatting",
        "carbontracker.tui.widgets",
        "carbontracker.tui.sources",
        "carbontracker.tui.watch_app",
        "carbontracker.tui.init_app",
        "carbontracker.tui.dashboard_app",
        "carbontracker.dashboard.catalog",
        "carbontracker.entrypoints.tui.tui",
    ]:
        importlib.import_module(module_name)

    imported_mockups = [
        name
        for name in sys.modules
        if name == "tui_mockups" or name.startswith("tui_mockups.")
    ]
    assert imported_mockups == []


def test_tui_launch_functions_import_without_running():
    module = importlib.import_module("carbontracker.entrypoints.tui.tui")

    assert callable(module.run_watch_tui)
    assert callable(module.run_init_tui)
    assert callable(module.run_dashboard_tui)


def test_production_apps_instantiate_without_running(tmp_path):
    watch_app = WatchApp(tmp_path / "events.jsonl", tail=False)
    init_app = InitApp(project_dir=tmp_path / "project-a")
    dashboard_app = DashboardApp(runs=[dashboard_run(tmp_path)])

    assert isinstance(watch_app.state, WatchState)
    assert init_app.draft.project_name == "project-a"
    assert dashboard_app.runs[0].run_name == "run-a"


def test_watch_row_projection_uses_production_watch_state():
    t0 = datetime(2026, 1, 1, 12)
    state = WatchState()
    for event in [
        StartedSession(
            timestamp=t0,
            project_name="demo",
            run_name="run-a",
            log_dir="logs",
            log_file_path="logs/run-a_events.jsonl",
            command=("python", "train.py"),
        ),
        ProcessStartedEvent(
            timestamp=t0 + timedelta(seconds=1),
            command=("python", "train.py"),
            pid=42,
            trace_id="trace-a",
        ),
        ProcessOutputEvent(
            timestamp=t0 + timedelta(seconds=2),
            stream="stdout",
            line="hello",
            trace_id="trace-a",
        ),
    ]:
        apply_event(state, event)

    rows = event_rows(state)
    stats = stats_values(state)

    assert rows[-1].cells == ("12:00:02", "ProcessOutputEvent", "stdout: hello")
    assert stats["current_runtime"] == "00:00:02"


def test_paged_rows_follow_tail_and_unseen_counts():
    pager = PagedRows(range(5), page_size=2)

    assert pager.visible_items().items == (3, 4)

    pager.page_up()
    assert pager.visible_items().items == (1, 2)

    pager.set_items(tuple(range(8)))
    page = pager.visible_items()

    assert page.items == (1, 2)
    assert page.unseen_new_rows == 3

    pager.jump_end()
    assert pager.visible_items().items == (6, 7)
    assert pager.visible_items().unseen_new_rows == 0


def test_init_location_parser_uses_production_types():
    assert parse_location("country", "dk").country_code == "DK"
    assert parse_location("zone", "DK-DK1").zone_id == "DK-DK1"
    assert parse_location("data_center", "aws:eu-west-1").provider == "aws"
    assert parse_location("cloud_region", "gcp:europe-west1").region == "europe-west1"
    assert parse_location("lat_lon", "55.67,12.56").latitude == 55.67


def test_default_cli_init_delegates_to_tui(monkeypatch):
    launched = {}

    def fake_init_tui():
        launched["called"] = True

    monkeypatch.setattr(cli_module, "run_init_tui", fake_init_tui)

    result = CliRunner().invoke(cli_module.main, ["init"])

    assert result.exit_code == 0
    assert launched["called"] is True


def test_formatting_helpers_are_plain_production_functions():
    assert format_duration(65) == "00:01:05"
    assert format_kwh(0.123456, unit=True) == "0.1235 kWh"


def test_dashboard_app_renders_runs_and_enter_opens_details(tmp_path):
    app = DashboardApp(runs=[dashboard_run(tmp_path)])

    async def run_app():
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one("#runs-table", DataTable)
            assert len(table.columns) == 6
            await pilot.press("enter")
            await pilot.pause()
            assert app.view == "details"

    asyncio.run(run_app())


def dashboard_run(tmp_path: Path) -> RunRecord:
    return RunRecord(
        project_name="demo",
        run_name="run-a",
        started_at=datetime(2026, 1, 1, 12),
        status="finished",
        command=("python", "train.py"),
        source_log_path=tmp_path / "run-a_events.jsonl",
        return_code=0,
        duration_s=30.0,
        completed_spans_count=2,
        local_power_usage_kwh=0.1,
        local_emissions_g=1.0,
        external_power_usage_kwh=0.2,
        external_emissions_g=2.0,
        external_accounting_methods=("explicit_intensity",),
        event_count=4,
        diagnostics_count=0,
        diagnostic_messages=(),
        components=("cpu",),
        intensity_method="static",
        pue=1.1,
        power_sampling_interval_s=1.0,
        intensity_sampling_interval_s=900.0,
        total_units=10,
        unit_name="request",
        total_duration_s=None,
        predict_after_units=2,
        predict_after_seconds=None,
        predict_interval_s=None,
    )
