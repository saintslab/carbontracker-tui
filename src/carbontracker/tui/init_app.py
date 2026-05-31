from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Key
from textual.widgets import Static

from carbontracker.config.init_draft import (
    InitDraft,
    default_init_draft,
    validate_init_draft,
    write_project_config_from_draft,
)
from carbontracker.core.types import (
    CloudRegion,
    Component,
    CountryCode,
    ElectricityMapsDataCenter,
    ElectricityMapsZone,
    GeoLocation,
    IntensityMethod,
    Location,
)
from carbontracker.tui.theme import BASE_CSS


QuestionId = Literal[
    "project_name",
    "log_dir",
    "components",
    "power_sampling_interval",
    "intensity_method",
    "static_intensity",
    "location_mode",
    "location_value",
    "prediction_mode",
    "unit_name",
    "total_units",
    "total_duration_s",
    "predict_after_units",
    "predict_after_seconds",
    "predict_interval_s",
    "review",
    "done",
]
QuestionKind = Literal["text", "number", "single", "multi", "review", "done"]
LocationMode = Literal["auto", "country", "zone", "data_center", "cloud_region", "lat_lon", "none"]
PredictionMode = Literal["off", "units", "duration"]


@dataclass(frozen=True)
class Choice:
    value: Any
    label: str
    detail: str = ""


@dataclass(frozen=True)
class Question:
    question_id: QuestionId
    title: str
    prompt: str
    kind: QuestionKind
    detail: str = ""


@dataclass
class InitWizardState:
    draft: InitDraft
    project_dir: Path
    question_index: int = 0
    option_index: int = 0
    input_buffer: str = ""
    last_question_id: QuestionId | None = None
    last_action: str = "loaded project defaults"
    location_mode: LocationMode = "auto"
    location_value: str = "DK-DK1"
    prediction_mode: PredictionMode = "off"
    saved_path: Path | None = None


QUESTIONS: dict[QuestionId, Question] = {
    "project_name": Question(
        "project_name",
        "Project",
        "What should CarbonTracker call this project?",
        "text",
        "Saved as project_name in the local project config.",
    ),
    "log_dir": Question(
        "log_dir",
        "Logs",
        "Where should CarbonTracker write run logs?",
        "text",
        "Relative paths stay relative to the tracked project.",
    ),
    "components": Question(
        "components",
        "Hardware",
        "Which hardware components should be tracked?",
        "multi",
        "At least one component is required.",
    ),
    "power_sampling_interval": Question(
        "power_sampling_interval",
        "Power Sampler",
        "How often should power be sampled?",
        "single",
        "Shorter intervals are more responsive; longer intervals are quieter.",
    ),
    "intensity_method": Question(
        "intensity_method",
        "Intensity Source",
        "How should carbon intensity be resolved?",
        "single",
        "Auto can use configured providers and fall back when needed.",
    ),
    "static_intensity": Question(
        "static_intensity",
        "Static Intensity",
        "What static intensity should be used?",
        "number",
        "Unit is gCO2eq/kWh.",
    ),
    "location_mode": Question(
        "location_mode",
        "Location",
        "How should the grid/location be saved?",
        "single",
        "Use auto for runtime fallback, or save an explicit native location.",
    ),
    "location_value": Question(
        "location_value",
        "Location",
        "What location should be saved?",
        "text",
        "Examples: DK, DK-DK1, aws:eu-west-1, gcp:europe-west1, 55.67,12.56.",
    ),
    "prediction_mode": Question(
        "prediction_mode",
        "Prediction",
        "How should prediction estimate the rest of the run?",
        "single",
        "Unit and duration prediction are mutually exclusive.",
    ),
    "unit_name": Question(
        "unit_name",
        "Unit Name",
        "What is one progress unit called?",
        "text",
        "Examples: epoch, batch, request, step.",
    ),
    "total_units": Question(
        "total_units",
        "Total Units",
        "How many units should a normal run complete?",
        "number",
        "Used with unit-based predictions.",
    ),
    "total_duration_s": Question(
        "total_duration_s",
        "Expected Duration",
        "How long should a normal run take?",
        "single",
        "Used with duration-based predictions.",
    ),
    "predict_after_units": Question(
        "predict_after_units",
        "First Prediction",
        "When should the first unit-based prediction be emitted?",
        "single",
        "Waiting for at least one completed unit usually gives a better estimate.",
    ),
    "predict_after_seconds": Question(
        "predict_after_seconds",
        "First Prediction",
        "When should the first duration-based prediction be emitted?",
        "single",
        "Waiting a few minutes avoids projecting from startup noise.",
    ),
    "predict_interval_s": Question(
        "predict_interval_s",
        "Prediction Updates",
        "How often should prediction updates be emitted?",
        "single",
        "0 means emit at most once.",
    ),
    "review": Question(
        "review",
        "Review",
        "Review the wizard choices.",
        "review",
        "Enter writes .carbontracker/config.toml through the config service.",
    ),
    "done": Question(
        "done",
        "Done",
        "Config saved. Run CarbonTracker from this project.",
        "done",
    ),
}


def prediction_mode_from_draft(draft: InitDraft) -> PredictionMode:
    if draft.total_units is not None or draft.unit_name is not None:
        return "units"
    if draft.total_duration_s is not None:
        return "duration"
    return "off"


def active_questions(state: InitWizardState) -> list[QuestionId]:
    questions: list[QuestionId] = [
        "project_name",
        "log_dir",
        "components",
        "power_sampling_interval",
        "intensity_method",
    ]
    if state.draft.intensity_method == IntensityMethod.STATIC:
        questions.append("static_intensity")
    else:
        questions.append("location_mode")
        if state.location_mode not in {"auto", "none"}:
            questions.append("location_value")
    questions.append("prediction_mode")
    if state.prediction_mode == "units":
        questions.extend(
            ["unit_name", "total_units", "predict_after_units", "predict_interval_s"]
        )
    elif state.prediction_mode == "duration":
        questions.extend(
            [
                "total_duration_s",
                "predict_after_seconds",
                "predict_interval_s",
            ]
        )
    questions.append("review")
    if state.saved_path is not None:
        questions.append("done")
    return questions


def current_question_id(state: InitWizardState) -> QuestionId:
    questions = active_questions(state)
    state.question_index = max(0, min(state.question_index, len(questions) - 1))
    return questions[state.question_index]


def choices_for(question_id: QuestionId) -> list[Choice]:
    if question_id == "components":
        return [
            Choice(Component.CPU, "CPU", "package or generic CPU power"),
            Choice(Component.GPU, "GPU", "NVML when available"),
            Choice(Component.RAM, "RAM", "estimated memory power"),
        ]
    if question_id == "power_sampling_interval":
        return [
            Choice(5.0, "5 seconds", "responsive"),
            Choice(15.0, "15 seconds", "balanced default"),
            Choice(30.0, "30 seconds", "lower overhead"),
            Choice(60.0, "60 seconds", "coarse sampling"),
        ]
    if question_id == "intensity_method":
        return [
            Choice(IntensityMethod.AUTO, "Auto", "provider then fallback"),
            Choice(IntensityMethod.ELECTRICITY_MAPS, "Electricity Maps", "requires key and location"),
            Choice(IntensityMethod.STATIC, "Static", "constant gCO2eq/kWh value"),
        ]
    if question_id == "location_mode":
        return [
            Choice("auto", "Auto-detect", "runtime fallback"),
            Choice("country", "Country code", "DK, US, DE"),
            Choice("zone", "Grid zone", "DK-DK1, US-CAL-CISO"),
            Choice("data_center", "Data center", "aws:eu-west-1, gcp:europe-west1"),
            Choice("cloud_region", "Cloud region", "aws:eu-west-1, gcp:europe-west1"),
            Choice("lat_lon", "Latitude/longitude", "55.67,12.56"),
            Choice("none", "No location", "allow runtime fallback"),
        ]
    if question_id == "prediction_mode":
        return [
            Choice("units", "Unit-based", "unit_name + total_units"),
            Choice("duration", "Duration-based", "expected total runtime"),
            Choice("off", "Skip", "no prediction defaults"),
        ]
    if question_id == "total_duration_s":
        return [
            Choice(1800.0, "30 minutes", "1800 seconds"),
            Choice(3600.0, "1 hour", "3600 seconds"),
            Choice(7200.0, "2 hours", "7200 seconds"),
            Choice(14400.0, "4 hours", "14400 seconds"),
        ]
    if question_id == "predict_after_units":
        return [
            Choice(0, "Immediately", "predict_after_units=0"),
            Choice(1, "After 1 unit", "predict_after_units=1"),
            Choice(3, "After 3 units", "predict_after_units=3"),
        ]
    if question_id == "predict_after_seconds":
        return [
            Choice(0.0, "Immediately", "predict_after_seconds=0"),
            Choice(300.0, "After 5 minutes", "predict_after_seconds=300"),
            Choice(900.0, "After 15 minutes", "predict_after_seconds=900"),
        ]
    if question_id == "predict_interval_s":
        return [
            Choice(0.0, "Only once", "predict_interval_s=0"),
            Choice(60.0, "Every minute", "predict_interval_s=60"),
            Choice(300.0, "Every 5 minutes", "predict_interval_s=300"),
        ]
    return []


def selected_value(state: InitWizardState, question_id: QuestionId) -> Any:
    draft = state.draft
    if question_id == "power_sampling_interval":
        return draft.power_sampling_interval
    if question_id == "intensity_method":
        return draft.intensity_method
    if question_id == "location_mode":
        return state.location_mode
    if question_id == "prediction_mode":
        return state.prediction_mode
    if question_id == "total_duration_s":
        return draft.total_duration_s
    if question_id == "predict_after_units":
        return draft.predict_after_units
    if question_id == "predict_after_seconds":
        return draft.predict_after_seconds
    if question_id == "predict_interval_s":
        return draft.predict_interval_s
    return None


def text_value(state: InitWizardState, question_id: QuestionId) -> str:
    draft = state.draft
    if question_id == "project_name":
        return draft.project_name
    if question_id == "log_dir":
        return draft.log_dir
    if question_id == "location_value":
        return state.location_value
    if question_id == "static_intensity":
        value = draft.static_carbon_intensity_g_per_kwh
        return "" if value is None else f"{value:g}"
    if question_id == "unit_name":
        return draft.unit_name or "epoch"
    if question_id == "total_units":
        return "" if draft.total_units is None else str(draft.total_units)
    return ""


def sync_question_state(state: InitWizardState) -> None:
    question_id = current_question_id(state)
    if question_id == state.last_question_id:
        return
    state.last_question_id = question_id
    state.option_index = 0
    question = QUESTIONS[question_id]
    if question.kind in {"text", "number"}:
        state.input_buffer = text_value(state, question_id)
        return
    selected = selected_value(state, question_id)
    for index, choice in enumerate(choices_for(question_id)):
        if choice.value == selected:
            state.option_index = index
            break
    state.input_buffer = ""


def apply_choice(state: InitWizardState, question_id: QuestionId, value: Any) -> None:
    draft = state.draft
    if question_id == "power_sampling_interval":
        state.draft = replace(draft, power_sampling_interval=float(value))
    elif question_id == "intensity_method":
        method = value
        if method == IntensityMethod.STATIC:
            state.draft = replace(
                draft,
                intensity_method=method,
                forecast_provider_name="static",
                location=None,
                static_carbon_intensity_g_per_kwh=(
                    draft.static_carbon_intensity_g_per_kwh or 390.0
                ),
            )
            state.location_mode = "none"
        else:
            state.draft = replace(
                draft,
                intensity_method=method,
                forecast_provider_name=(
                    "electricity_maps"
                    if method == IntensityMethod.ELECTRICITY_MAPS
                    else draft.forecast_provider_name
                ),
                static_carbon_intensity_g_per_kwh=None,
            )
    elif question_id == "location_mode":
        state.location_mode = value
        defaults = {
            "country": "DK",
            "zone": "DK-DK1",
            "data_center": "aws:eu-west-1",
            "cloud_region": "aws:eu-west-1",
            "lat_lon": "55.67,12.56",
        }
        state.location_value = defaults.get(value, state.location_value)
        if value in {"auto", "none"}:
            state.draft = replace(draft, location=None)
    elif question_id == "prediction_mode":
        state.prediction_mode = value
        if value == "off":
            state.draft = replace(
                draft,
                unit_name=None,
                total_units=None,
                total_duration_s=None,
                predict_after_units=None,
                predict_after_seconds=None,
                predict_interval_s=None,
            )
        elif value == "units":
            state.draft = replace(
                draft,
                unit_name=draft.unit_name or "epoch",
                total_units=draft.total_units or 10,
                total_duration_s=None,
                predict_after_units=draft.predict_after_units
                if draft.predict_after_units is not None
                else 1,
                predict_after_seconds=None,
                predict_interval_s=draft.predict_interval_s
                if draft.predict_interval_s is not None
                else 0.0,
            )
        elif value == "duration":
            state.draft = replace(
                draft,
                unit_name=None,
                total_units=None,
                total_duration_s=draft.total_duration_s or 3600.0,
                predict_after_units=None,
                predict_after_seconds=draft.predict_after_seconds
                if draft.predict_after_seconds is not None
                else 300.0,
                predict_interval_s=draft.predict_interval_s
                if draft.predict_interval_s is not None
                else 0.0,
            )
    elif question_id == "total_duration_s":
        state.draft = replace(draft, total_duration_s=float(value))
    elif question_id == "predict_after_units":
        state.draft = replace(draft, predict_after_units=int(value))
    elif question_id == "predict_after_seconds":
        state.draft = replace(draft, predict_after_seconds=float(value))
    elif question_id == "predict_interval_s":
        state.draft = replace(draft, predict_interval_s=float(value))


def apply_text(state: InitWizardState, question_id: QuestionId, value: str) -> str | None:
    value = value.strip()
    draft = state.draft
    if question_id in {"project_name", "log_dir", "unit_name"} and not value:
        return f"{question_id} must be non-empty"
    if question_id == "project_name":
        state.draft = replace(draft, project_name=value)
    elif question_id == "log_dir":
        state.draft = replace(draft, log_dir=value)
    elif question_id == "location_value":
        try:
            location = parse_location(state.location_mode, value)
        except ValueError as exc:
            return str(exc)
        state.location_value = value
        state.draft = replace(draft, location=location)
    elif question_id == "static_intensity":
        try:
            number = float(value)
        except ValueError:
            return "static intensity must be a number"
        if number <= 0:
            return "static intensity must be positive"
        state.draft = replace(draft, static_carbon_intensity_g_per_kwh=number)
    elif question_id == "unit_name":
        state.draft = replace(draft, unit_name=value)
    elif question_id == "total_units":
        try:
            number = int(value)
        except ValueError:
            return "total_units must be an integer"
        if number <= 0:
            return "total_units must be positive"
        state.draft = replace(draft, total_units=number)
    return None


def parse_location(mode: LocationMode, value: str) -> Location | None:
    text = value.strip()
    if mode in {"auto", "none"}:
        return None
    if not text:
        raise ValueError("location must be non-empty")
    if mode == "country":
        return CountryCode(text.upper())
    if mode == "zone":
        return ElectricityMapsZone(text)
    if mode == "data_center":
        provider, region = _split_provider_region(text)
        return ElectricityMapsDataCenter(provider, region)
    if mode == "cloud_region":
        provider, region = _split_provider_region(text)
        return CloudRegion(provider, region)
    if mode == "lat_lon":
        parts = [part.strip() for part in text.split(",")]
        if len(parts) != 2:
            raise ValueError("latitude/longitude must look like 55.67,12.56")
        try:
            return GeoLocation(float(parts[0]), float(parts[1]))
        except ValueError as exc:
            raise ValueError("latitude/longitude must be numeric") from exc
    return None


def _split_provider_region(value: str) -> tuple[str, str]:
    if ":" not in value:
        raise ValueError("provider region must look like aws:eu-west-1")
    provider, region = value.split(":", 1)
    provider = provider.strip()
    region = region.strip()
    if not provider or not region:
        raise ValueError("provider and region must be non-empty")
    return provider, region


def toggle_component(state: InitWizardState) -> None:
    if current_question_id(state) != "components":
        return
    choices = choices_for("components")
    component = choices[state.option_index].value
    components = set(state.draft.components)
    if component in components:
        if len(components) == 1:
            state.last_action = "at least one component is required"
            return
        components.remove(component)
    else:
        components.add(component)
    state.draft = replace(
        state.draft,
        components=tuple(sorted(components, key=lambda item: item.value)),
    )
    state.last_action = f"toggled {component.value}"


def accept_current_answer(state: InitWizardState) -> None:
    question_id = current_question_id(state)
    question = QUESTIONS[question_id]
    if question.kind in {"text", "number"}:
        error = apply_text(state, question_id, state.input_buffer)
        if error:
            state.last_action = error
            return
    elif question.kind == "single":
        choices = choices_for(question_id)
        if choices:
            apply_choice(state, question_id, choices[state.option_index].value)
    elif question.kind == "review":
        diagnostics = validate_init_draft(state.draft)
        errors = [item.message for item in diagnostics if item.severity == "error"]
        if errors:
            state.last_action = "; ".join(errors)
            return
        state.saved_path = write_project_config_from_draft(state.draft)
        state.last_action = f"wrote {state.saved_path}"
        questions = active_questions(state)
        state.question_index = questions.index("done")
        state.last_question_id = None
        sync_question_state(state)
        return
    elif question.kind == "done":
        state.last_action = "ready to run carbontracker"
        return

    questions = active_questions(state)
    state.question_index = min(state.question_index + 1, len(questions) - 1)
    state.last_question_id = None
    state.last_action = f"accepted {question.title}"
    sync_question_state(state)


def move_question(state: InitWizardState, delta: int) -> None:
    questions = active_questions(state)
    state.question_index = max(0, min(state.question_index + delta, len(questions) - 1))
    state.last_question_id = None
    sync_question_state(state)


def move_option(state: InitWizardState, delta: int) -> None:
    choices = choices_for(current_question_id(state))
    if choices:
        state.option_index = max(0, min(state.option_index + delta, len(choices) - 1))


def runtime_validation_text(draft: InitDraft) -> str:
    diagnostics = validate_init_draft(draft)
    errors = [item.message for item in diagnostics if item.severity == "error"]
    if errors:
        return f"invalid: {errors[0]}"
    return "valid"


def draft_summary(state: InitWizardState) -> list[tuple[str, str]]:
    draft = state.draft
    location = "auto" if draft.location is None else str(draft.location)
    prediction = state.prediction_mode
    if state.prediction_mode == "units":
        prediction = f"{draft.total_units} {draft.unit_name}"
    elif state.prediction_mode == "duration":
        prediction = f"{draft.total_duration_s:g}s"
    return [
        ("Project", draft.project_name),
        ("Logs", draft.log_dir),
        ("Hardware", " ".join(component.value for component in draft.components)),
        ("Power", f"{draft.power_sampling_interval:g}s"),
        ("Intensity", draft.intensity_method.value),
        ("Location", location),
        ("Prediction", prediction),
    ]


class InitApp(App[None]):
    CSS = (
        BASE_CSS
        + """
#prompt {
    width: 100%;
    height: 1fr;
    padding: 1 2;
}

#footer-right {
    width: 44;
}
"""
    )

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("left", "previous_question", "Previous", show=False, priority=True),
        Binding("right", "next_question", "Next", show=False, priority=True),
        Binding("up", "option_up", "Up", show=False, priority=True),
        Binding("down", "option_down", "Down", show=False, priority=True),
        Binding("space", "space", "Toggle", show=False, priority=True),
        Binding("enter", "accept", "Accept", show=False, priority=True),
        Binding("backspace", "backspace", "Backspace", show=False, priority=True),
    ]

    def __init__(self, project_dir: str | Path | None = None) -> None:
        super().__init__()
        path = Path(project_dir) if project_dir is not None else Path.cwd()
        draft = default_init_draft(path)
        self.state = InitWizardState(
            draft=draft,
            project_dir=path,
            prediction_mode=prediction_mode_from_draft(draft),
        )
        sync_question_state(self.state)

    @property
    def draft(self) -> InitDraft:
        return self.state.draft

    def compose(self) -> ComposeResult:
        with Vertical(id="body"):
            yield Static(id="prompt")
        with Horizontal(id="footer-line"):
            yield Static(id="footer-left")
            yield Static("left/right steps, up/down choices", id="footer-right")

    def on_mount(self) -> None:
        self.title = "CarbonTracker init"
        self.sub_title = str(self.state.project_dir)
        self.refresh_screen()

    def on_key(self, event: Key) -> None:
        question = QUESTIONS[current_question_id(self.state)]
        if question.kind not in {"text", "number"} or event.character is None:
            return
        char = event.character
        if question.kind == "number" and char not in "0123456789.":
            event.stop()
            return
        if char.isprintable():
            self.state.input_buffer += char
            self.refresh_screen()
            event.stop()

    def action_previous_question(self) -> None:
        move_question(self.state, -1)
        self.refresh_screen()

    def action_next_question(self) -> None:
        move_question(self.state, 1)
        self.refresh_screen()

    def action_option_up(self) -> None:
        move_option(self.state, -1)
        self.refresh_screen()

    def action_option_down(self) -> None:
        move_option(self.state, 1)
        self.refresh_screen()

    def action_space(self) -> None:
        toggle_component(self.state)
        self.refresh_screen()

    def action_accept(self) -> None:
        accept_current_answer(self.state)
        self.refresh_screen()

    def action_backspace(self) -> None:
        question = QUESTIONS[current_question_id(self.state)]
        if question.kind in {"text", "number"}:
            self.state.input_buffer = self.state.input_buffer[:-1]
            self.refresh_screen()

    def refresh_screen(self) -> None:
        sync_question_state(self.state)
        self.query_one("#prompt", Static).update(render_prompt(self.state))
        self.query_one("#footer-left", Static).update(render_footer_left(self.state))


def render_prompt(state: InitWizardState) -> Text:
    question_id = current_question_id(state)
    question = QUESTIONS[question_id]
    questions = active_questions(state)
    text = Text()
    text.append("carbontracker init", style="bold")
    text.append(f"  {state.question_index + 1}/{len(questions)}", style="dim")
    text.append("\n\n")
    text.append(f"{question.prompt}\n", style="bold")
    if question.detail:
        text.append(f"{question.detail}\n\n", style="dim")

    if question.kind in {"text", "number"}:
        text.append("> ", style="green bold")
        text.append(state.input_buffer or " ", style="bold")
        text.append("\n\nenter accepts, backspace edits", style="dim")
    elif question.kind == "multi":
        selected_components = set(state.draft.components)
        for index, choice in enumerate(choices_for(question_id)):
            active = index == state.option_index
            checked = choice.value in selected_components
            marker = ">" if active else " "
            box = "[x]" if checked else "[ ]"
            style = "bold green" if active else ""
            text.append(f"{marker} {box} {choice.label}", style=style)
            text.append(f"  {choice.detail}\n", style="dim")
        text.append("\nspace toggles, enter continues", style="dim")
    elif question.kind == "single":
        selected = selected_value(state, question_id)
        for index, choice in enumerate(choices_for(question_id)):
            active = index == state.option_index
            is_selected = choice.value == selected
            marker = ">" if active else " "
            suffix = " selected" if is_selected else ""
            style = "bold green" if active else ""
            text.append(f"{marker} {choice.label}", style=style)
            text.append(f"  {choice.detail}{suffix}\n", style="dim")
        text.append("\nenter accepts", style="dim")
    elif question.kind == "review":
        text.append("Summary\n", style="bold")
        for label, value in draft_summary(state):
            text.append(f"{label:<12}", style="dim")
            text.append(f"{value}\n")
        text.append("\nSave target\n", style="bold")
        text.append(".carbontracker/config.toml\n", style="green")
        diagnostics = validate_init_draft(state.draft)
        if diagnostics:
            text.append("\nDiagnostics\n", style="bold yellow")
            for diagnostic in diagnostics:
                text.append(f"- {diagnostic.message}\n", style="yellow")
        text.append("\nenter writes config", style="dim")
    else:
        text.append("Config saved\n", style="bold green")
        if state.saved_path is not None:
            text.append(f"{state.saved_path}\n", style="dim")
        text.append("\nRun with saved defaults\n", style="bold")
        text.append("carbontracker python train.py\n", style="green")
        text.append("\nOpen a watchable JSONL run\n", style="bold")
        text.append("carbontracker watch carbontracker_logs/<run>_events.jsonl\n", style="green")
    return text


def render_footer_left(state: InitWizardState) -> Text:
    text = Text()
    text.append("status: ", style="dim bold")
    status = runtime_validation_text(state.draft)
    text.append(status, style="bold green" if status == "valid" else "bold yellow")
    text.append(" | project: ", style="dim bold")
    text.append(state.draft.project_name, style="bold")
    text.append(" | ", style="dim")
    text.append(state.last_action, style="dim")
    return text

