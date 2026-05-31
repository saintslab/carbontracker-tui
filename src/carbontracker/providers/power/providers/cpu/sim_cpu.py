from datetime import datetime
from carbontracker.core.profiling import PowerDomain, PowerSample, PowerScope
from carbontracker.providers.data_provider import DataProvider
from carbontracker.providers.power.power_provider import PowerMeasurementData

class SimulatedCPUProvider(DataProvider[PowerMeasurementData]):
    def __init__(self, name: str, tdp: float, utilization: float = 0.5):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("CPU name must be a non-empty string.")
        if tdp is None or not isinstance(tdp, (int, float)) or tdp < 0:
            raise ValueError("CPU TDP must be a non-negative number.")
        if not isinstance(utilization, (int, float)) or not (0.0 <= utilization <= 1.0):
            raise ValueError("CPU utilization must be between 0.0 and 1.0.")
            
        self.cpu_brand = name
        self.utilization = utilization
        self.tdp = tdp * utilization
        
        print(f"Using simulated CPU: {self.cpu_brand} with TDP: {self.tdp:.2f}W (at {self.utilization*100:.0f}% utilization)")

    @property
    def name(self) -> str:
        return f"Simulated CPU ({self.cpu_brand})"

    def fetch(self) -> PowerMeasurementData:
        now = datetime.now()
        return PowerMeasurementData(
            timestamp=now,
            samples=(
                PowerSample(
                    observed_at=now,
                    domain=PowerDomain.CPU,
                    device_id="cpu:simulated",
                    source="simulated",
                    scope=PowerScope.DEVICE_TOTAL,
                    watts=self.tdp,
                    label=self.cpu_brand,
                ),
            ),
        )

    def shutdown(self):
        pass
