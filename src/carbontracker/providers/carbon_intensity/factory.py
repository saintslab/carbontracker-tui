import logging
import queue
from threading import Event
from typing import Protocol
from carbontracker.core.events import TrackerEvent
from carbontracker.core.exceptions import ProviderConfigError, APIError
from carbontracker.providers.data_provider_thread import DataProviderThread
from carbontracker.providers.carbon_intensity.intensity_provider import (
    IntensityMeasurementData, 
    IntensityResolution,
)

from carbontracker.core.resolution import ResolutionStep, print_resolution_steps
from carbontracker.core.types import IntensityMethod, Location
from carbontracker.providers.carbon_intensity.location import resolve_location, location_to_country
from carbontracker.providers.carbon_intensity.providers.electricity_maps import ElectricityMapsProvider
from carbontracker.providers.carbon_intensity.providers.static_provider import (
    StaticProvider,
    StaticCountryProvider,
    GlobalAverageProvider
)

logger = logging.getLogger("carbontracker.intensity_factory")


class IntensityRuntimeConfig(Protocol):
    intensity_method: IntensityMethod | str
    intensity_sampling_interval: float
    location: Location | str | None
    static_carbon_intensity_g_per_kwh: float | None
    api_keys: dict[str, str] | None


def create_intensity_thread(
    config: IntensityRuntimeConfig,
    aggregation_queue: "queue.Queue[TrackerEvent]",
    notify_event: Event
) -> tuple[DataProviderThread[IntensityMeasurementData], IntensityResolution]:
    """
    Creates a ProviderThread encapsulating the resolved intensity provider.
    This also handles printing the resolution log to the user.
    """
    resolution = resolve_intensity_provider(config)
    print_resolution_steps(resolution.steps, logger)
    
    return (DataProviderThread(
        sample_interval=config.intensity_sampling_interval,
        providers=[resolution.provider],
        aggregation_queue=aggregation_queue,
        notify_event=notify_event
    ), resolution)


def resolve_intensity_provider(config: IntensityRuntimeConfig) -> IntensityResolution:
    """
    Implements the deterministic fallback chain for intensity providers.
    """
    steps: list[ResolutionStep] = []
    
    # 1. Resolve Location
    auto_detect = getattr(config, "auto_detect_location", True)
    resolved_loc = resolve_location(config.location, auto_detect)
    
    if resolved_loc.source == "config":
        steps.append(ResolutionStep(
            action="location_config",
            detail=f"Using configured location: {resolved_loc.raw_input}",
            level="info"
        ))
    elif resolved_loc.source == "geolocation":
        loc_data = resolved_loc.location
        steps.append(ResolutionStep(
            action="location_geolocation",
            detail=f"Location detected via IP geolocation: {loc_data.latitude}, {loc_data.longitude}",
            level="info"
        ))
    else:
        steps.append(ResolutionStep(
            action="location_unknown",
            detail="No location specified and geolocation failed or disabled.",
            level="warning"
        ))
        
    # 2. Select Provider based on Method
    method = config.intensity_method.value if hasattr(config.intensity_method, 'value') else config.intensity_method
    
    if method == "static":
        if config.static_carbon_intensity_g_per_kwh is not None:
            provider = StaticProvider(resolved_loc, config.static_carbon_intensity_g_per_kwh)
            steps.append(ResolutionStep(
                action="provider_static_override",
                detail=f"Using static carbon intensity (user-defined: {config.static_carbon_intensity_g_per_kwh} g CO₂eq/kWh)",
                level="success"
            ))
            return IntensityResolution(provider, resolved_loc, steps, provider_name="static", static_intensity=config.static_carbon_intensity_g_per_kwh)
        else:
            # Try country fallback
            country = location_to_country(resolved_loc.location) if resolved_loc.location else None
            if country:
                provider = StaticCountryProvider(resolved_loc, country)
                steps.append(ResolutionStep(
                    action="provider_static_country",
                    detail=f"Using static country average ({country})",
                    level="success"
                ))
                return IntensityResolution(provider, resolved_loc, steps, provider_name="static", static_intensity=provider.intensity_value)
            else:
                provider = GlobalAverageProvider(resolved_loc)
                steps.append(ResolutionStep(
                    action="provider_global_average",
                    detail="Using global average (475 g CO₂eq/kWh)",
                    level="warning"
                ))
                return IntensityResolution(provider, resolved_loc, steps, provider_name="static", static_intensity=provider.intensity_value)

    elif method == "electricity_maps":
        em_key = config.api_keys.get("electricity_maps") if config.api_keys else None
        if not em_key:
            raise ProviderConfigError("electricity_maps method requires an API key in config.api_keys['electricity_maps']")
            
        provider = ElectricityMapsProvider(resolved_loc, em_key)
        steps.append(ResolutionStep(
            action="provider_electricitymaps",
            detail=f"Using: {provider.name}",
            level="success"
        ))
        return IntensityResolution(provider, resolved_loc, steps, provider_name="electricity_maps", static_intensity=None)

    elif method == "auto":
        # Check keys
        em_key = config.api_keys.get("electricity_maps") if config.api_keys else None
        if em_key and resolved_loc.source != "unknown":
            try:
                provider = ElectricityMapsProvider(resolved_loc, em_key)
                steps.append(ResolutionStep(
                    action="api_key_found",
                    detail="Electricity Maps API key found",
                    level="info"
                ))
                steps.append(ResolutionStep(
                    action="provider_electricitymaps",
                    detail=f"Using: {provider.name}",
                    level="success"
                ))
                return IntensityResolution(provider, resolved_loc, steps, provider_name="electricity_maps", static_intensity=None)
            except ProviderConfigError as e:
                # E.g. couldn't build query params from location
                steps.append(ResolutionStep(
                    action="api_provider_failed",
                    detail=f"Electricity Maps API configured but location format unsupported: {e}",
                    level="warning"
                ))
                logger.warning(f"Electricity Maps API configured but location format unsupported: {e}")
            except APIError as e:
                steps.append(ResolutionStep(
                    action="api_provider_failed",
                    detail=f"Electricity Maps API failed: {e}",
                    level="warning"
                ))
                logger.warning(f"Electricity Maps API failed: {e}")
        
        # Auto fallback -> country average -> global average
        if not em_key:
            steps.append(ResolutionStep(
                action="no_api_key",
                detail="No API key configured for real-time data.",
                level="warning"
            ))
            
        country = location_to_country(resolved_loc.location) if resolved_loc.location else None
        if country:
            provider = StaticCountryProvider(resolved_loc, country)
            steps.append(ResolutionStep(
                action="provider_static_country",
                detail=f"Using static country average ({country})",
                level="success"
            ))
            return IntensityResolution(provider, resolved_loc, steps, provider_name="static", static_intensity=provider.intensity_value)
        else:
            provider = GlobalAverageProvider(resolved_loc)
            steps.append(ResolutionStep(
                action="provider_global_average",
                detail="Using global average (475 g CO₂eq/kWh)",
                level="warning"
            ))
            return IntensityResolution(provider, resolved_loc, steps, provider_name="static", static_intensity=provider.intensity_value)
        
    else:
        raise ValueError(f"Unrecognized intensity method: {method}")

