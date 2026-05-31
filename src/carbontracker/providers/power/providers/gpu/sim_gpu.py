from datetime import datetime
from carbontracker.core.profiling import PowerDomain, PowerSample, PowerScope
from carbontracker.providers.data_provider import DataProvider
from carbontracker.providers.power.power_provider import PowerMeasurementData

class SimulatedGPUProvider(DataProvider[PowerMeasurementData]):
    def __init__(self, name: str, watts: float, utilization: float = 0.5):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("GPU name must be a non-empty string.")
        if watts is None or not isinstance(watts, (int, float)) or watts < 0:
            raise ValueError("GPU watts must be a non-negative number.")
        if not isinstance(utilization, (int, float)) or not (0.0 <= utilization <= 1.0):
            raise ValueError("GPU utilization must be between 0.0 and 1.0.")
            
        self.gpu_brand = name
        self.utilization = utilization
        self.watts = watts * utilization
        
        print(f"Using simulated GPU: {self.gpu_brand} with power consumption: {self.watts:.2f}W (at {self.utilization*100:.0f}% utilization)")

    @property
    def name(self) -> str:
        return f"Simulated GPU ({self.gpu_brand})"

    def fetch(self) -> PowerMeasurementData:
        now = datetime.now()
        return PowerMeasurementData(
            timestamp=now,
            samples=(
                PowerSample(
                    observed_at=now,
                    domain=PowerDomain.GPU,
                    device_id="gpu:simulated",
                    source="simulated",
                    scope=PowerScope.DEVICE_TOTAL,
                    watts=self.watts,
                    label=self.gpu_brand,
                ),
            ),
        )

    def shutdown(self):
        pass
