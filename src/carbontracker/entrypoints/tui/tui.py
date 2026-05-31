from pathlib import Path


def run_watch_tui(path: Path, *, tail: bool = True) -> None:
    from carbontracker.tui.watch_app import WatchApp

    WatchApp(path, tail=tail).run()


def run_dashboard_tui(log_dir: Path | None = None) -> None:
    from carbontracker.config.config_manager import resolve_overrides
    from carbontracker.core.runtime import RuntimeOptions
    from carbontracker.tui.dashboard_app import DashboardApp

    resolved_log_dir = log_dir
    if resolved_log_dir is None:
        resolved_log_dir = Path(RuntimeOptions.from_mapping(resolve_overrides()).log_dir)
    DashboardApp(resolved_log_dir).run()


def run_init_tui(*, project_dir: Path | None = None) -> None:
    from carbontracker.tui.init_app import InitApp

    InitApp(project_dir=project_dir).run()


def tui_watch(log_dir: str) -> None:
    run_watch_tui(Path(log_dir))


def tui_init_wizard() -> None:
    run_init_tui()
