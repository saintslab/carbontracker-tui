from dataclasses import dataclass


@dataclass(frozen=True)
class ExternalUsage:
    energy_kwh: float | None = None
    emissions_g: float | None = None
    carbon_intensity_g_per_kwh: float | None = None


@dataclass(frozen=True)
class ExternalAccounting:
    energy_kwh: float
    emissions_g: float
    method: str


def compute_external_accounting(
    usage: ExternalUsage | None,
) -> ExternalAccounting | None:
    if usage is None:
        return None

    values = (
        usage.energy_kwh,
        usage.emissions_g,
        usage.carbon_intensity_g_per_kwh,
    )
    if any(value is not None and value < 0 for value in values):
        return None

    if usage.emissions_g is not None:
        if usage.energy_kwh is not None:
            return ExternalAccounting(
                energy_kwh=usage.energy_kwh,
                emissions_g=usage.emissions_g,
                method="direct_emissions_and_energy",
            )
        return ExternalAccounting(
            energy_kwh=0.0,
            emissions_g=usage.emissions_g,
            method="direct_emissions",
        )

    if (
        usage.energy_kwh is not None
        and usage.carbon_intensity_g_per_kwh is not None
    ):
        return ExternalAccounting(
            energy_kwh=usage.energy_kwh,
            emissions_g=usage.energy_kwh * usage.carbon_intensity_g_per_kwh,
            method="explicit_intensity",
        )

    return None
