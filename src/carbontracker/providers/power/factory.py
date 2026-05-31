import logging
from typing import Protocol, Sequence
import queue
from threading import Event

from carbontracker.core.exceptions import ProviderUnavailableError, ProviderPermissionError
from carbontracker.providers.data_provider_thread import DataProviderThread
from carbontracker.providers.power.power_provider import PowerMeasurementData
from carbontracker.core.events import TrackerEvent
from carbontracker.core.resolution import ResolutionStep, log_resolution_steps
from carbontracker.core.types import Component

from carbontracker.providers.power.providers.cpu.intel import IntelCPU
from carbontracker.providers.power.providers.cpu.generic import GenericCPU
from carbontracker.providers.power.providers.gpu.nvidia import NvidiaGPU
from carbontracker.providers.power.providers.apple_silicon.powermetrics import AppleSiliconCPU, AppleSiliconGPU, AppleSiliconANE


logger = logging.getLogger("carbontracker.power_factory")


class PowerRuntimeConfig(Protocol):
    components: Sequence[Component | str]
    devices_by_pids: list[str]
    power_sampling_interval: float


def create_power_thread(
    config: PowerRuntimeConfig,
    aggregation_queue: "queue.Queue[TrackerEvent]", 
    notify_event: Event
) -> DataProviderThread[PowerMeasurementData]:
    
    providers = []
    pids = [int(pid) for pid in config.devices_by_pids] if config.devices_by_pids else []
    steps: list[ResolutionStep] = []
    
    # We no longer handle simulated components here natively based on a config flag.
    # The config components array drives real provider instantiation.
    component_names = [
        c.value.lower() if hasattr(c, "value") else str(c).lower()
        for c in config.components
    ]
    
    if "cpu" in component_names:
        for cls in [IntelCPU, AppleSiliconCPU, GenericCPU]:
            try:
                cpu_provider = cls(pids=pids)
                steps.append(ResolutionStep("provider_resolved", f"CPU: {cpu_provider.name}", "success"))
                providers.append(cpu_provider)
                break
            except (ProviderPermissionError, ProviderUnavailableError):
                continue
        else:
            steps.append(ResolutionStep("no_provider", "No CPU provider available", "warning"))
            
    if "gpu" in component_names:
        for cls in [NvidiaGPU, AppleSiliconGPU]:
            try:
                gpu_provider = cls(pids=pids)
                steps.append(ResolutionStep("provider_resolved", f"GPU: {gpu_provider.name}", "success"))
                providers.append(gpu_provider)
                break
            except (ProviderPermissionError, ProviderUnavailableError):
                continue
        else:
            steps.append(ResolutionStep("no_provider", "No GPU provider available", "warning"))
        
        try:
            ane_provider = AppleSiliconANE(pids=pids)
            steps.append(ResolutionStep("provider_resolved", f"ANE: {ane_provider.name}", "success"))
            providers.append(ane_provider)
        except (ProviderPermissionError, ProviderUnavailableError):
            pass

    log_resolution_steps(steps, logger)

    return DataProviderThread(
        sample_interval=config.power_sampling_interval, 
        providers=providers, 
        aggregation_queue=aggregation_queue, 
        notify_event=notify_event
    )
