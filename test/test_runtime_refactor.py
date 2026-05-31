import queue
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from carbontracker.core.events import SessionMetadata, StartedSession
from carbontracker.core.engine import CarbonTrackerEngine
from carbontracker.core.exceptions import WrongModeError
from carbontracker.core import runtime as runtime_module
from carbontracker.core.runtime import (
    RuntimeBundle,
    RuntimeOptions,
    build_subprocess_runtime,
    generate_default_run_name,
)
from carbontracker.core.stats import SessionFinalStats
from carbontracker.core.types import Component
import carbontracker.api as api_module
from carbontracker.entrypoints.cli import cli as cli_module


class FakeThread:
    def __init__(self, name: str, stop_result=None) -> None:
        self.name = name
        self.native_id = None
        self.daemon = True
        self.stop_result = stop_result
        self.started = False
        self.stopped = False
        self.joined = 0

    def start(self) -> None:
        self.started = True

    def stop(self):
        self.stopped = True
        return self.stop_result

    def join(self) -> None:
        self.joined += 1


class FakeManualControls:
    def __init__(self) -> None:
        self.starts = 0
        self.ends = 0
        self.finished = False

    def epoch_start(self) -> None:
        self.starts += 1

    def epoch_end(self) -> None:
        self.ends += 1

    def mark_finished(self) -> None:
        self.finished = True


def make_fake_bundle(manual_controls=None):
    stats = SessionFinalStats(
        total_emissions_g=1.0,
        total_power_usage_kwh=2.0,
        duration_s=3.0,
        completed_spans_count=4,
    )
    aggregation_queue = queue.Queue()
    terminal_queue = queue.Queue()
    logger_queue = queue.Queue()
    observer = FakeThread("observer")
    provider = FakeThread("provider")
    aggregator = FakeThread("aggregator", stop_result=stats)
    reporter = FakeThread("reporter")
    metadata = SessionMetadata(
        project_name="carbontracker",
        run_name="test",
        log_dir="carbontracker_logs/",
        log_file_path="carbontracker_logs/test_events.jsonl",
    )
    bundle = RuntimeBundle(
        options=RuntimeOptions(run_name="test", auto_detect_location=False),
        metadata=metadata,
        log_file_path=Path(metadata.log_file_path),
        observer_thread=observer,
        provider_threads=[provider],
        aggregator_thread=aggregator,
        reporter_threads=[reporter],
        aggregation_queue=aggregation_queue,
        terminal_queue=terminal_queue,
        logger_queue=logger_queue,
        event_sink=[terminal_queue, logger_queue],
        manual_controls=manual_controls,
    )
    return bundle, stats


def test_engine_starts_stops_joins_runtime_threads():
    bundle, expected_stats = make_fake_bundle()

    engine = CarbonTrackerEngine(bundle)
    assert all(thread.started for thread in bundle.threads)

    stats = engine.finish()

    assert stats == expected_stats
    assert all(thread.stopped for thread in bundle.threads)
    assert all(thread.joined == 1 for thread in bundle.threads)


def test_engine_manual_controls_fail_when_absent():
    bundle, _ = make_fake_bundle()
    engine = CarbonTrackerEngine(bundle)

    with pytest.raises(WrongModeError):
        engine.epoch_start()

    engine.finish()


def test_manual_constructor_rejects_invalid_args_before_build(monkeypatch):
    def fail_build(_options):
        raise AssertionError("runtime builder should not be called")

    monkeypatch.setattr(api_module, "build_manual_runtime", fail_build)

    with pytest.raises(ValueError, match="pue"):
        api_module.CarbonTracker(epochs=1, pue=0)

    with pytest.raises(NotImplementedError, match="max_energy_kwh"):
        api_module.CarbonTracker(epochs=1, max_energy_kwh=1.0)


def test_manual_lifecycle_delegates_to_runtime_controls(monkeypatch):
    controls = FakeManualControls()
    bundle, expected_stats = make_fake_bundle(manual_controls=controls)
    captured = {}

    def fake_build(options):
        captured["options"] = options
        return bundle

    monkeypatch.setattr(api_module, "build_manual_runtime", fake_build)

    tracker = api_module.CarbonTracker(epochs=1, components=["cpu"])
    tracker.epoch_start()
    tracker.epoch_end()
    stats = tracker.finish()

    assert captured["options"].components == [Component.CPU]
    assert captured["options"].total_units == 1
    assert controls.starts == 1
    assert controls.ends == 1
    assert controls.finished is True
    assert stats == expected_stats


def test_subprocess_runtime_rejects_empty_command():
    options = RuntimeOptions(run_name="test", auto_detect_location=False)

    with pytest.raises(ValueError, match="command"):
        build_subprocess_runtime([], options)


def test_cli_passthrough_builds_subprocess_runtime_and_finishes(monkeypatch, tmp_path):
    script = tmp_path / "tiny.py"
    script.write_text("print('ok')\n")
    bundle, _ = make_fake_bundle()
    captured = {}

    monkeypatch.setattr(cli_module, "resolve_overrides", lambda **kwargs: kwargs)

    def fake_build(command, options, **kwargs):
        captured["command"] = command
        captured["options"] = options
        captured["runtime_kwargs"] = kwargs
        return bundle

    monkeypatch.setattr(cli_module, "build_subprocess_runtime", fake_build)

    result = CliRunner().invoke(cli_module.main, [sys.executable, str(script)])

    assert result.exit_code == 0
    assert captured["command"] == [sys.executable, str(script)]
    assert isinstance(captured["options"], RuntimeOptions)
    assert captured["runtime_kwargs"]["capture_output_events"] is False
    assert captured["runtime_kwargs"]["persist_process_output"] is False
    assert bundle.observer_thread.joined == 2
    assert bundle.aggregator_thread.stopped is True


def test_generated_run_name_is_timestamp_shaped():
    run_name = generate_default_run_name()

    assert re.fullmatch(r"run_\d{8}_\d{6}", run_name)


def test_runtime_metadata_and_jsonl_path_share_run_identity(monkeypatch, tmp_path):
    class FakeProviderThread(FakeThread):
        def __init__(self, name):
            super().__init__(name)

    def fake_power_thread(**_kwargs):
        return FakeProviderThread("power")

    def fake_intensity_thread(**_kwargs):
        resolution = SimpleNamespace(
            provider_name="static",
            location=None,
            static_intensity=100.0,
        )
        return FakeProviderThread("intensity"), resolution

    def fake_forecast_thread(**_kwargs):
        return FakeProviderThread("forecast")

    monkeypatch.setattr(runtime_module, "create_power_thread", fake_power_thread)
    monkeypatch.setattr(runtime_module, "create_intensity_thread", fake_intensity_thread)
    monkeypatch.setattr(
        runtime_module, "create_intensity_forecast_thread", fake_forecast_thread
    )

    options = RuntimeOptions(
        project_name="project-a",
        run_name="run-a",
        log_dir=str(tmp_path),
        auto_detect_location=False,
    )
    bundle = build_subprocess_runtime(["python"], options)

    assert bundle.options.project_name == "project-a"
    assert bundle.options.run_name == "run-a"
    assert bundle.metadata.project_name == "project-a"
    assert bundle.metadata.run_name == "run-a"
    assert bundle.log_file_path == tmp_path / "run-a_events.jsonl"
    assert bundle.metadata.log_file_path == str(tmp_path / "run-a_events.jsonl")

    started_event = bundle.logger_queue.get_nowait()
    assert isinstance(started_event, StartedSession)
    assert started_event.metadata == bundle.metadata


def test_cli_run_name_override_does_not_replace_project_name(monkeypatch, tmp_path):
    script = tmp_path / "tiny.py"
    script.write_text("print('ok')\n")
    bundle, _ = make_fake_bundle()
    captured = {}

    monkeypatch.setattr(cli_module, "resolve_overrides", lambda **kwargs: kwargs)

    def fake_build(command, options, **_kwargs):
        captured["options"] = options
        return bundle

    monkeypatch.setattr(cli_module, "build_subprocess_runtime", fake_build)

    result = CliRunner().invoke(
        cli_module.main,
        [
            "--project-name",
            "proj",
            "--run-name",
            "run-explicit",
            sys.executable,
            str(script),
        ],
    )

    assert result.exit_code == 0
    assert captured["options"].project_name == "proj"
    assert captured["options"].run_name == "run-explicit"


def test_cli_run_name_underscore_alias(monkeypatch, tmp_path):
    script = tmp_path / "tiny.py"
    script.write_text("print('ok')\n")
    bundle, _ = make_fake_bundle()
    captured = {}

    monkeypatch.setattr(cli_module, "resolve_overrides", lambda **kwargs: kwargs)

    def fake_build(command, options, **_kwargs):
        captured["options"] = options
        return bundle

    monkeypatch.setattr(cli_module, "build_subprocess_runtime", fake_build)

    result = CliRunner().invoke(
        cli_module.main,
        ["run", "--run_name", "alias-run", sys.executable, str(script)],
    )

    assert result.exit_code == 0
    assert captured["options"].run_name == "alias-run"


def test_manual_prediction_options_are_passed_to_runtime(monkeypatch):
    bundle, _ = make_fake_bundle(manual_controls=FakeManualControls())
    captured = {}

    def fake_build(options):
        captured["options"] = options
        return bundle

    monkeypatch.setattr(api_module, "build_manual_runtime", fake_build)

    tracker = api_module.CarbonTracker(
        epochs=4,
        total_units=8,
        unit_name="batch",
        predict_after_units=2,
        predict_after_seconds=30,
        predict_interval_s=0,
    )
    tracker.finish()

    assert captured["options"].total_units == 8
    assert captured["options"].unit_name == "batch"
    assert captured["options"].predict_after_units == 2
    assert captured["options"].predict_after_seconds == 30
    assert captured["options"].predict_interval_s == 0


def test_cli_track_prediction_options_override_project_defaults(monkeypatch):
    bundle, _ = make_fake_bundle()
    captured = {}

    monkeypatch.setattr(
        cli_module,
        "resolve_overrides",
        lambda **kwargs: {
            "total_units": 10,
            "predict_after_units": 1,
            **kwargs,
        },
    )

    def fake_build(
        command,
        options,
        capture_output_events=False,
        enable_tui_sink=False,
        persist_process_output=False,
        jsonl_path=None,
    ):
        captured["command"] = command
        captured["options"] = options
        captured["capture_output_events"] = capture_output_events
        captured["enable_tui_sink"] = enable_tui_sink
        captured["persist_process_output"] = persist_process_output
        captured["jsonl_path"] = jsonl_path
        return bundle

    monkeypatch.setattr(cli_module, "build_subprocess_runtime", fake_build)

    result = CliRunner().invoke(
        cli_module.main,
        [
            "track",
            "--jsonl",
            "events.jsonl",
            "--total-units",
            "20",
            "--predict-after-units",
            "3",
            "--predict-interval",
            "0",
            sys.executable,
            "-c",
            "print('ok')",
        ],
    )

    assert result.exit_code == 0
    assert captured["options"].total_units == 20
    assert captured["options"].predict_after_units == 3
    assert captured["options"].predict_interval_s == 0
    assert captured["capture_output_events"] is True
    assert captured["enable_tui_sink"] is False
    assert captured["persist_process_output"] is True
    assert captured["jsonl_path"] == "events.jsonl"


def test_cli_track_direct_api_key_reaches_runtime_options(monkeypatch):
    bundle, _ = make_fake_bundle()
    captured = {}

    monkeypatch.setattr(cli_module, "resolve_overrides", lambda **kwargs: kwargs)

    def fake_build(command, options, **_kwargs):
        captured["command"] = command
        captured["options"] = options
        return bundle

    monkeypatch.setattr(cli_module, "build_subprocess_runtime", fake_build)

    result = CliRunner().invoke(
        cli_module.main,
        [
            "track",
            "--api-key",
            "electricity_maps",
            "secret",
            sys.executable,
            "-c",
            "print('ok')",
        ],
    )

    assert result.exit_code == 0
    assert captured["command"] == [sys.executable, "-c", "print('ok')"]
    assert captured["options"].api_keys == {"electricity_maps": "secret"}


def test_cli_passthrough_direct_api_key_reaches_runtime_options(monkeypatch):
    bundle, _ = make_fake_bundle()
    captured = {}

    monkeypatch.setattr(cli_module, "resolve_overrides", lambda **kwargs: kwargs)

    def fake_build(command, options, **_kwargs):
        captured["command"] = command
        captured["options"] = options
        return bundle

    monkeypatch.setattr(cli_module, "build_subprocess_runtime", fake_build)

    result = CliRunner().invoke(
        cli_module.main,
        [
            "--api-key",
            "electricity_maps",
            "secret",
            sys.executable,
            "-c",
            "print('ok')",
        ],
    )

    assert result.exit_code == 0
    assert captured["command"] == [sys.executable, "-c", "print('ok')"]
    assert captured["options"].api_keys == {"electricity_maps": "secret"}


def test_cli_watch_reads_jsonl_without_building_runtime(monkeypatch, tmp_path):
    log_path = tmp_path / "events.jsonl"
    log_path.write_text(
        '{"__type__":"StartedSession","timestamp":"2026-01-01T12:00:00",'
        '"project_name":"demo","run_name":"run-a","log_dir":"logs",'
        '"log_file_path":"logs/run-a_events.jsonl"}\n'
    )
    launched = {}

    def fail_build(*_args, **_kwargs):
        raise AssertionError("watch must not build a runtime")

    def fake_watch_tui(path):
        launched["path"] = path

    monkeypatch.setattr(cli_module, "build_subprocess_runtime", fail_build)
    monkeypatch.setattr(cli_module, "run_watch_tui", fake_watch_tui)

    result = CliRunner().invoke(cli_module.main, ["watch", str(log_path)])

    assert result.exit_code == 0
    assert launched["path"] == log_path


def test_cli_dashboard_uses_configured_log_dir_without_building_runtime(
    monkeypatch, tmp_path
):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    launched = {}

    def fail_build(*_args, **_kwargs):
        raise AssertionError("dashboard must not build a runtime")

    def fake_dashboard_tui(path):
        launched["path"] = path

    monkeypatch.setattr(
        cli_module,
        "resolve_overrides",
        lambda **_kwargs: {"log_dir": str(log_dir)},
    )
    monkeypatch.setattr(cli_module, "build_subprocess_runtime", fail_build)
    monkeypatch.setattr(cli_module, "run_dashboard_tui", fake_dashboard_tui)

    result = CliRunner().invoke(cli_module.main, ["dashboard"])

    assert result.exit_code == 0
    assert launched["path"] == log_dir


def test_cli_dashboard_rejects_missing_log_dir(tmp_path):
    missing = tmp_path / "missing"

    result = CliRunner().invoke(cli_module.main, ["dashboard", str(missing)])

    assert result.exit_code != 0
    assert "Dashboard log directory not found" in result.output
