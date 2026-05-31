from typing import Optional, Literal, Callable
from pydantic import BaseModel
from carbontracker.core.prediction import PredictionResult
from carbontracker.core.types import BreachAction

class GuardVerdict(BaseModel):
    action: BreachAction
    reason: str | None = None
    violated_field: str | None = None  # "max_emissions_g", "max_energy_kwh", etc.

class BudgetGuard:
    """Checks predictions against budget policies."""
    
    def __init__(
        self,
        max_energy_kwh: float | None = None,
        max_emissions_g: float | None = None,
        use_predicted_values: bool = False,
        action_on_breach: BreachAction = BreachAction.LOG,
        patience: int = 2,
        callback: Callable[['GuardVerdict'], None] | None = None
    ):
        if max_energy_kwh is None and max_emissions_g is None:
            raise ValueError("BudgetGuard requires at least one of max_energy_kwh or max_emissions_g to be set.")
        if max_energy_kwh is not None and max_energy_kwh <= 0:
            raise ValueError("max_energy_kwh must be greater than 0.")
        if max_emissions_g is not None and max_emissions_g <= 0:
            raise ValueError("max_emissions_g must be greater than 0.")

        self.max_energy_kwh = max_energy_kwh
        self.max_emissions_g = max_emissions_g
        self.use_predicted_values = use_predicted_values
        self.action_on_breach = action_on_breach
        self.patience = patience
        self.callback = callback
        self._consecutive_violations = 0
        
    def check(
        self, 
        cumulative_energy_kwh: float, 
        cumulative_emissions_g: float, 
        prediction: PredictionResult | None = None
    ) -> GuardVerdict:
        
        energy_kwh = cumulative_energy_kwh
        emissions_g = cumulative_emissions_g
        
        if self.use_predicted_values and prediction is not None:
            energy_kwh = prediction.projected_total_energy_kwh
            emissions_g = prediction.projected_total_emissions_g

        violated_field = None
        reason = None
        
        if self.max_energy_kwh is not None and energy_kwh > self.max_energy_kwh:
            violated_field = "max_energy_kwh"
            prefix = "Predicted energy" if self.use_predicted_values and prediction is not None else "Cumulative energy"
            reason = f"{prefix} ({energy_kwh:.2f} kWh) exceeds budget ({self.max_energy_kwh} kWh)"
        elif self.max_emissions_g is not None and emissions_g > self.max_emissions_g:
            violated_field = "max_emissions_g"
            prefix = "Predicted emissions" if self.use_predicted_values and prediction is not None else "Cumulative emissions"
            reason = f"{prefix} ({emissions_g:.2f} g) exceeds budget ({self.max_emissions_g} g)"
            
        if violated_field:
            self._consecutive_violations += 1
            if self._consecutive_violations >= self.patience:
                verdict = GuardVerdict(action=self.action_on_breach, reason=reason, violated_field=violated_field)
            else:
                verdict = GuardVerdict(action=BreachAction.PASS, reason=f"Violation ({self._consecutive_violations}/{self.patience}): {reason}", violated_field=violated_field)
        else:
            self._consecutive_violations = 0
            verdict = GuardVerdict(action=BreachAction.PASS)
            
        if self.callback is not None:
            self.callback(verdict)
            
        return verdict
