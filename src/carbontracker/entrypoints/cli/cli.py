import click
from pathlib import Path

from carbontracker.config.config_manager import resolve_overrides
from carbontracker.config.project_init import init_global_config, init_project_config
from carbontracker.core.event_codec import events_from_jsonl_lines
from carbontracker.core.events import DiagnosticEvent
from carbontracker.core.engine import CarbonTrackerEngine
from carbontracker.core.runtime import RuntimeOptions, build_subprocess_runtime
from carbontracker.entrypoints.tui.tui import (
    run_dashboard_tui,
    run_init_tui,
    run_watch_tui,
)
from carbontracker.providers.carbon_intensity.location import resolve_location


RUN_CONTEXT = {
    "ignore_unknown_options": True,
    "allow_extra_args": True,
}


def _reject_unsupported_options(overrides: dict) -> None:
    unsupported: list[str] = []
    for key in (
        "predict_after",
        "max_energy_kwh",
        "max_emissions_g",
        "on_breach_callback",
    ):
        if overrides.get(key) is not None:
            unsupported.append(key)

    if overrides.get("use_predicted_values"):
        unsupported.append("use_predicted_values")

    action_on_breach = overrides.get("action_on_breach")
    if action_on_breach not in (None, "log"):
        unsupported.append("action_on_breach")

    if unsupported:
        joined = ", ".join(unsupported)
        raise click.ClickException(
            f"Prediction and budget options are not supported yet: {joined}"
        )


class PassThroughGroup(click.Group):
    def parse_args(self, ctx, args):
        if not args:
            return super().parse_args(ctx, args)
        if args[0] in self.commands:
            return super().parse_args(ctx, args)
            
        # Route to the hidden 'run' command
        args.insert(0, 'run')
        return super().parse_args(ctx, args)


@click.group(cls=PassThroughGroup)
def main():
    """CarbonTracker: Track the carbon footprint of your code."""
    pass


def _runtime_kwargs(kwargs: dict) -> dict:
    user_kwargs = {k: v for k, v in kwargs.items() if v is not None}
    if "components" in user_kwargs and not user_kwargs["components"]:
        del user_kwargs["components"]
    api_key_pairs = user_kwargs.pop("api_key", None)
    if api_key_pairs:
        user_kwargs["api_keys"] = dict(api_key_pairs)
    return user_kwargs


def _has_cli_init_overrides(global_config: bool, kwargs: dict) -> bool:
    if global_config:
        return True
    for value in kwargs.values():
        if isinstance(value, (tuple, list, dict)):
            if value:
                return True
        elif value is not None:
            return True
    return False


def _run_subprocess(
    command,
    kwargs: dict,
    *,
    capture_output_events: bool = False,
    persist_process_output: bool = False,
    jsonl_path: str | None = None,
) -> None:
    overrides = resolve_overrides(**_runtime_kwargs(kwargs))
    _reject_unsupported_options(overrides)

    options = RuntimeOptions.from_mapping(overrides)
    runtime = build_subprocess_runtime(
        command=list(command),
        options=options,
        capture_output_events=capture_output_events,
        persist_process_output=persist_process_output,
        jsonl_path=jsonl_path,
    )
    engine = CarbonTrackerEngine(runtime)

    try:
        engine.wait_for_observer()
    finally:
        engine.finish()


def _identity_options(function):
    function = click.option("--project-name", type=str, help="Name of the project")(function)
    function = click.option(
        "--run-name",
        "--run_name",
        "run_name",
        type=str,
        help="Name of this run",
    )(function)
    function = click.option("--log-dir", type=str, help="Directory to save logs")(function)
    return function


def _runtime_options(function):
    function = click.option(
        "--api-key",
        multiple=True,
        type=(str, str),
        help="Runtime API key as PROVIDER VALUE",
    )(function)
    function = click.option("--pue", type=float, help="Power Usage Effectiveness")(function)
    function = click.option(
        "--components",
        multiple=True,
        type=str,
        help="Components to track (cpu, gpu, ram)",
    )(function)
    function = click.option(
        "--session-stat-interval",
        "session_stat_interval_s",
        type=float,
        help="Interval for live session stats in seconds",
    )(function)
    function = click.option(
        "--power-sampling-interval",
        type=float,
        help="Interval for power sampling in seconds",
    )(function)
    function = click.option(
        "--intensity-method",
        type=str,
        help="Carbon intensity method (auto, electricity_maps, static)",
    )(function)
    function = click.option(
        "--intensity-sampling-interval",
        type=float,
        help="Interval for intensity sampling in seconds",
    )(function)
    function = click.option("--location", type=str, help="Location override")(function)
    function = click.option(
        "--auto-detect-location/--no-auto-detect-location",
        default=None,
        help="Enable or disable IP geolocation fallback",
    )(function)
    function = click.option(
        "--static-carbon-intensity-g-per-kwh",
        type=float,
        help="Static intensity fallback",
    )(function)
    function = click.option(
        "--forecast-provider-name",
        type=str,
        help="Forecast provider override",
    )(function)
    return function


def _prediction_options(function):
    function = click.option(
        "--total-units",
        type=int,
        help="Total units for unit-based prediction",
    )(function)
    function = click.option(
        "--unit-name",
        type=str,
        help="Span/unit name for unit-based prediction",
    )(function)
    function = click.option(
        "--total-duration",
        "total_duration_s",
        type=float,
        help="Total duration for time-based prediction in seconds",
    )(function)
    function = click.option(
        "--predict-after-units",
        type=int,
        help="Completed units required before predicting",
    )(function)
    function = click.option(
        "--predict-after-seconds",
        type=float,
        help="Elapsed seconds required before predicting",
    )(function)
    function = click.option(
        "--predict-interval",
        "predict_interval_s",
        type=float,
        help="Seconds between predictions; <=0 emits at most one",
    )(function)
    return function


def _runner_options(function):
    return _prediction_options(_runtime_options(_identity_options(function)))


@main.command(context_settings=RUN_CONTEXT)
@click.argument("command", nargs=-1, required=True, type=click.UNPROCESSED)
@_runner_options
def run(command, **kwargs):
    """
    Wraps an arbitrary command with carbon tracking.
    """
    _run_subprocess(command, kwargs)


@main.command(context_settings=RUN_CONTEXT)
@click.argument("command", nargs=-1, required=True, type=click.UNPROCESSED)
@click.option(
    "--jsonl",
    "jsonl_path",
    type=click.Path(dir_okay=False, path_type=str),
    help="Explicit JSONL event log path",
)
@_runner_options
def track(command, jsonl_path, **kwargs):
    """Runs a command and writes complete watchable JSONL."""
    _run_subprocess(
        command,
        kwargs,
        capture_output_events=True,
        persist_process_output=True,
        jsonl_path=jsonl_path,
    )


@main.command()
@click.option("--global", "global_config", is_flag=True, help="Write user-level defaults")
@click.option("--project-name", type=str, help="Project name for local config")
@click.option("--log-dir", type=str, help="Default project log directory")
@click.option("--components", multiple=True, type=str, help="Default components to track")
@click.option("--power-sampling-interval", type=float, help="Default power sampling interval")
@click.option("--intensity-sampling-interval", type=float, help="Default intensity sampling interval")
@click.option("--intensity-method", type=str, help="Default intensity method")
@click.option("--static-carbon-intensity-g-per-kwh", type=float, help="Static intensity fallback")
@click.option("--total-units", type=int, help="Default total units for prediction")
@click.option("--unit-name", type=str, help="Default unit/span name for prediction")
@click.option("--total-duration", "total_duration_s", type=float, help="Default total duration for prediction in seconds")
@click.option("--predict-after-units", type=int, help="Default completed units before predicting")
@click.option("--predict-after-seconds", type=float, help="Default elapsed seconds before predicting")
@click.option("--predict-interval", "predict_interval_s", type=float, help="Default seconds between predictions; <=0 emits at most one")
@click.option("--api-key", multiple=True, type=(str, str), help="Global API key as PROVIDER VALUE")
@click.option("--location", type=str, help="Global default location")
@click.option("--pue", type=float, help="Global default PUE")
def init(global_config, **kwargs):
    """Initialize CarbonTracker config."""
    if not _has_cli_init_overrides(global_config, kwargs):
        run_init_tui()
        return

    if global_config:
        raw_location = kwargs.get("location")
        location = (
            resolve_location(raw_location, auto_detect=False).location
            if raw_location
            else None
        )
        api_keys = dict(kwargs.get("api_key") or ())
        path = init_global_config(
            api_keys=api_keys,
            default_location=location,
            default_pue=kwargs.get("pue"),
        )
        click.echo(f"Wrote global config: {path}")
        return

    components = kwargs.get("components")
    path = init_project_config(
        project_name=kwargs.get("project_name"),
        log_dir=kwargs.get("log_dir"),
        components=components if components else None,
        power_sampling_interval=kwargs.get("power_sampling_interval"),
        intensity_sampling_interval=kwargs.get("intensity_sampling_interval"),
        intensity_method=kwargs.get("intensity_method"),
        static_carbon_intensity_g_per_kwh=kwargs.get(
            "static_carbon_intensity_g_per_kwh"
        ),
        total_units=kwargs.get("total_units"),
        unit_name=kwargs.get("unit_name"),
        total_duration_s=kwargs.get("total_duration_s"),
        predict_after_units=kwargs.get("predict_after_units"),
        predict_after_seconds=kwargs.get("predict_after_seconds"),
        predict_interval_s=kwargs.get("predict_interval_s"),
    )
    click.echo(f"Wrote project config: {path}")


@main.command()
@click.argument("path", required=True, type=click.Path(dir_okay=False, path_type=str))
def watch(path):
    """Open an existing CarbonTracker JSONL event log in the TUI."""
    log_path = Path(path)
    if not log_path.exists():
        raise click.ClickException(f"JSONL log not found: {log_path}")

    run_watch_tui(log_path)


@main.command()
@click.argument(
    "log_dir",
    required=False,
    type=click.Path(file_okay=False, path_type=str),
)
def dashboard(log_dir):
    """Open a dashboard of CarbonTracker JSONL event logs."""
    if log_dir is None:
        overrides = resolve_overrides()
        options = RuntimeOptions.from_mapping(overrides)
        dashboard_log_dir = Path(options.log_dir)
    else:
        dashboard_log_dir = Path(log_dir)

    if not dashboard_log_dir.exists():
        raise click.ClickException(
            f"Dashboard log directory not found: {dashboard_log_dir}"
        )
    if not dashboard_log_dir.is_dir():
        raise click.ClickException(
            f"Dashboard log path is not a directory: {dashboard_log_dir}"
        )

    run_dashboard_tui(dashboard_log_dir)


@main.command()
@click.argument("path", required=False)
def replay(path):
    """Reads JSONL event logs and reports decode diagnostics."""
    if path is None:
        overrides = resolve_overrides()
        options = RuntimeOptions.from_mapping(overrides)
        log_path = Path(options.log_dir)
    else:
        log_path = Path(path)
    if log_path.is_dir():
        files = sorted(log_path.glob("*_events.jsonl"))
    else:
        files = [log_path]

    if not files:
        click.echo(f"No JSONL logs found at {log_path}")
        return

    for file_path in files:
        with open(file_path) as handle:
            for event in events_from_jsonl_lines(handle):
                if isinstance(event, DiagnosticEvent):
                    click.echo(f"[{event.severity.value}] {event.message}", err=True)
                else:
                    click.echo(f"[Replay] {type(event).__name__}")


if __name__ == "__main__":
    main()
