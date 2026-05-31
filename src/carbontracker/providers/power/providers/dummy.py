from datetime import datetime
from carbontracker.core.profiling import PowerDomain, PowerSample, PowerScope
from carbontracker.providers.data_provider import DataProvider
from carbontracker.providers.power.power_provider import PowerMeasurementData


class DummyGPU(DataProvider[PowerMeasurementData]):
    def __init__(self, pids=None) -> None:
        super().__init__()
        
    @property
    def name(self) -> str:
        return "Dummy GPU"

    def fetch(self) -> PowerMeasurementData:
        now = datetime.now()
        return PowerMeasurementData(
            timestamp=now,
            samples=(
                PowerSample(
                    observed_at=now,
                    domain=PowerDomain.GPU,
                    device_id="gpu:0",
                    source="dummy",
                    scope=PowerScope.DEVICE_TOTAL,
                    watts=50.0,
                    label="GPU:0",
                ),
            ),
        )

    def shutdown(self) -> None:
        pass


class DummyCPU(DataProvider[PowerMeasurementData]):
    def __init__(self, pids=None) -> None:
        super().__init__()
        
    @property
    def name(self) -> str:
        return "Dummy CPU"

    def fetch(self) -> PowerMeasurementData:
        now = datetime.now()
        return PowerMeasurementData(
            timestamp=now,
            samples=(
                PowerSample(
                    observed_at=now,
                    domain=PowerDomain.CPU,
                    device_id="cpu:0",
                    source="dummy",
                    scope=PowerScope.DEVICE_TOTAL,
                    watts=10.0,
                    label="CPU:0",
                ),
            ),
        )

    def shutdown(self) -> None:
        pass
