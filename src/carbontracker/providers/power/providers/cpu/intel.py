import os
import re
import time
from datetime import datetime
from typing import List, Union

from carbontracker.core.exceptions import ProviderUnavailableError, ProviderPermissionError
from carbontracker.core.profiling import PowerDomain, PowerSample, PowerScope
from carbontracker.providers.data_provider import DataProvider
from carbontracker.providers.power.power_provider import PowerMeasurementData

# RAPL Literature:
# https://www.researchgate.net/publication/322308215_RAPL_in_Action_Experiences_in_Using_RAPL_for_Power_Measurements

RAPL_DIR = "/sys/class/powercap/"
CPU = 0
DRAM = 2
MEASURE_DELAY = 1


class IntelCPU(DataProvider[PowerMeasurementData]):
    def __init__(self, pids: List[int]):
        self.pids = pids
        
        if not (os.path.exists(RAPL_DIR) and bool(os.listdir(RAPL_DIR))):
            raise ProviderUnavailableError(f"RAPL directory {RAPL_DIR} not found or empty. Intel RAPL not available.")
            
        # Get amount of intel-rapl folders
        packages = list(filter(lambda x: ":" in x, os.listdir(RAPL_DIR)))
        self.device_count = len(packages)
        self._devices: List[str] = []
        self._rapl_devices: List[str] = []
        self.parts_pattern = re.compile(r"intel-rapl:(\d):(\d)")
        devices_pattern = re.compile(r"intel-rapl:(\d)(:\d)?")

        for package in packages:
            if re.fullmatch(devices_pattern, package):
                with open(os.path.join(RAPL_DIR, package, "name"), "r") as f:
                    name = f.read().strip()
                if name != "psys" and ("package" in name or "dram" in name):
                    self._rapl_devices.append(package)
                    rapl_name = self._convert_rapl_name(package, name, devices_pattern)
                    if rapl_name is not None:
                        self._devices.append(rapl_name)

    @property
    def name(self) -> str:
        return "Intel RAPL CPU"

    def fetch(self) -> PowerMeasurementData:
        before_measures = self._get_measurements()
        time.sleep(MEASURE_DELAY)
        after_measures = self._get_measurements()
        
        # Ensure all power measurements >= 0 and retry up to 3 times.
        attempts = 3
        power_usages = []
        while attempts > 0:
            power_usages = [
                self._compute_power(before, after)
                for before, after in zip(before_measures, after_measures)
            ]
            if all(power >= 0 for power in power_usages):
                break
            attempts -= 1
            if attempts > 0:
                # Need to remeasure if failed
                before_measures = self._get_measurements()
                time.sleep(MEASURE_DELAY)
                after_measures = self._get_measurements()
                
        if not power_usages or not all(power >= 0 for power in power_usages):
            power_usages = [0.0 for _ in self._devices]

        now = datetime.now()
        samples = []
        for device, watts in zip(self._devices, power_usages):
            domain = PowerDomain.RAM if device.startswith("dram") else PowerDomain.CPU
            samples.append(
                PowerSample(
                    observed_at=now,
                    domain=domain,
                    device_id=device,
                    source="rapl",
                    scope=PowerScope.DEVICE_TOTAL,
                    watts=watts,
                    label=device,
                )
            )
        
        return PowerMeasurementData(
            timestamp=now,
            samples=tuple(samples),
        )

    def _compute_power(self, before: int, after: int) -> float:
        """Compute avg. power usage from two samples in microjoules."""
        joules = (after - before) / 1000000
        watt = joules / MEASURE_DELAY
        return watt

    def _read_energy(self, path: str) -> int:
        with open(os.path.join(path, "energy_uj"), "r") as f:
            return int(f.read())

    def _get_measurements(self):
        measurements = []
        permission_errors = []
        for package in self._rapl_devices:
            try:
                power_usage = self._read_energy(os.path.join(RAPL_DIR, package))
                measurements.append(power_usage)
            # If there is no sudo access, we cannot read the energy_uj file.
            # Permission denied error is raised.
            except PermissionError:
                permission_errors += [os.path.join(RAPL_DIR, package, "energy_uj")]

            except FileNotFoundError:
                # check cpu/gpu/dram
                parts = [
                    f
                    for f in os.listdir(os.path.join(RAPL_DIR, package))
                    if re.match(self.parts_pattern, f)
                ]
                total_power_usage = 0
                for part in parts:
                    total_power_usage += self._read_energy(
                        os.path.join(RAPL_DIR, package, part)
                    )

                measurements.append(total_power_usage)
        if permission_errors:
            raise ProviderPermissionError(f"Permission denied reading RAPL files: {permission_errors}")
        return measurements

    def _convert_rapl_name(self, package, name, pattern) -> Union[None, str]:
        match = re.match(pattern, package)
        name = name if "package" not in name else "cpu"
        if match:
            return name + ":" + match.group(1)

    def shutdown(self):
        pass
