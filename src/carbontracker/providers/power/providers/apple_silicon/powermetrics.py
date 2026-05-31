import platform
import subprocess
import re
import time
from datetime import datetime
from typing import Union, List, Pattern

from carbontracker.core.profiling import PowerDomain, PowerSample, PowerScope
from carbontracker.providers.data_provider import DataProvider
from carbontracker.providers.power.power_provider import PowerMeasurementData
from carbontracker.core.exceptions import ProviderUnavailableError


class PowerMetricsUnified:
    _output: Union[None, str] = None
    _last_updated: Union[None, float] = None

    @staticmethod
    def get_output():
        if (
            PowerMetricsUnified._output is None
            or PowerMetricsUnified._last_updated is None
            or time.time() - PowerMetricsUnified._last_updated > 1
        ):
            PowerMetricsUnified._output = subprocess.check_output(
                [
                    "sudo",
                    "powermetrics",
                    "-n",
                    "1",
                    "-i",
                    "100",
                    "--samplers",
                    "all",
                ],
                universal_newlines=True,
                stderr=subprocess.DEVNULL,
            )
            PowerMetricsUnified._last_updated = time.time()
        return PowerMetricsUnified._output


class AppleSiliconCPU(DataProvider[PowerMeasurementData]):
    def __init__(self, pids: List[int]):
        self.pids = pids
        if platform.system() != "Darwin":
            raise ProviderUnavailableError("Apple Silicon providers are only available on macOS (Darwin).")
        
        self.cpu_pattern = re.compile(r"CPU Power: (\d+) mW")

    @property
    def name(self) -> str:
        return "Apple Silicon CPU"

    def fetch(self) -> PowerMeasurementData:
        output = PowerMetricsUnified.get_output()
        cpu_power = self.parse_power(output, self.cpu_pattern)
        now = datetime.now()
        
        return PowerMeasurementData(
            timestamp=now,
            samples=(
                PowerSample(
                    observed_at=now,
                    domain=PowerDomain.CPU,
                    device_id="cpu:apple-silicon",
                    source="powermetrics",
                    scope=PowerScope.DEVICE_TOTAL,
                    watts=cpu_power,
                    label="CPU",
                ),
            ),
        )

    def parse_power(self, output: str, pattern: Pattern[str]) -> float:
        match = pattern.search(output)
        if match:
            power = float(match.group(1)) / 1000  # Convert mW to W
            return power
        else:
            return 0.0

    def shutdown(self):
        pass


class AppleSiliconGPU(DataProvider[PowerMeasurementData]):
    def __init__(self, pids: List[int]):
        self.pids = pids
        if platform.system() != "Darwin":
            raise ProviderUnavailableError("Apple Silicon providers are only available on macOS (Darwin).")

        self.gpu_pattern = re.compile(r"GPU Power: (\d+) mW")

    @property
    def name(self) -> str:
        return "Apple Silicon GPU"

    def fetch(self) -> PowerMeasurementData:
        output = PowerMetricsUnified.get_output()
        gpu_power = self.parse_power(output, self.gpu_pattern)
        now = datetime.now()

        return PowerMeasurementData(
            timestamp=now,
            samples=(
                PowerSample(
                    observed_at=now,
                    domain=PowerDomain.GPU,
                    device_id="gpu:apple-silicon",
                    source="powermetrics",
                    scope=PowerScope.DEVICE_TOTAL,
                    watts=gpu_power,
                    label="GPU",
                ),
            ),
        )

    def parse_power(self, output: str, pattern: Pattern[str]) -> float:
        match = pattern.search(output)
        if match:
            power = float(match.group(1)) / 1000  # Convert mW to W
            return power
        else:
            return 0.0
            
    def shutdown(self):
        pass

class AppleSiliconANE(DataProvider[PowerMeasurementData]):
    def __init__(self, pids: List[int]):
        self.pids = pids
        if platform.system() != "Darwin":
            raise ProviderUnavailableError("Apple Silicon providers are only available on macOS (Darwin).")

        self.ane_pattern = re.compile(r"ANE Power: (\d+) mW")

    @property
    def name(self) -> str:
        return "Apple Silicon ANE"

    def fetch(self) -> PowerMeasurementData:
        output = PowerMetricsUnified.get_output()
        ane_power = self.parse_power(output, self.ane_pattern)
        now = datetime.now()

        return PowerMeasurementData(
            timestamp=now,
            samples=(
                PowerSample(
                    observed_at=now,
                    domain=PowerDomain.ANE,
                    device_id="ane:apple-silicon",
                    source="powermetrics",
                    scope=PowerScope.DEVICE_TOTAL,
                    watts=ane_power,
                    label="ANE",
                ),
            ),
        )

    def parse_power(self, output: str, pattern: Pattern[str]) -> float:
        match = pattern.search(output)
        if match:
            power = float(match.group(1)) / 1000  # Convert mW to W (J/s)
            return power
        else:
            return 0.0
        
    def shutdown(self):
        pass
