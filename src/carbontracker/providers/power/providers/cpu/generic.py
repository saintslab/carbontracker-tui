import cpuinfo
import csv
import os
import statistics
from datetime import datetime
from typing import List, Optional

import logging
from carbontracker.core.profiling import PowerDomain, PowerSample, PowerScope
from carbontracker.providers.data_provider import DataProvider
from carbontracker.providers.power.power_provider import PowerMeasurementData

logger = logging.getLogger(__name__)

class GenericCPU(DataProvider[PowerMeasurementData]):
    def __init__(self, pids: List[int]):
        self.pids = pids
        self.cpu_brand = self.get_cpu_brand()
        self.tdp = None
        self.cpu_power_data = self.load_cpu_power_data()
        self.average_tdp = self.calculate_average_tdp()
        
        if not self.cpu_brand:
            logger.warning("Failed to detect CPU. Falling back to generic CPU handler.")
            self.cpu_brand = "Unknown CPU"
        
        self.tdp = self.find_matching_tdp()
        
        if self.tdp is None:
            self.tdp = self.average_tdp
            logger.warning(f"No matching TDP found for CPU: {self.cpu_brand}. Using average TDP of {self.tdp:.2f}W at 50% utilization as fallback.")
        else:
            self.tdp = self.tdp / 2  # 50% utilization
            logger.info(f"Using TDP of {self.tdp:.2f}W for {self.cpu_brand} at 50% utilization")

    def get_cpu_brand(self) -> str:
        try:
            info = cpuinfo.get_cpu_info()
            cpu_brand = info.get('brand_raw', '')
            logger.info(f"Detected CPU: {cpu_brand}")
            return cpu_brand
        except Exception as e:
            logger.warning(f"Failed to get CPU info: {e}")
            return ''

    def load_cpu_power_data(self):
        csv_path = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'cpu_power.csv')
        cpu_power_data = {}
        try:
            with open(csv_path, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        tdp_value = row['TDP']
                        if '.' in tdp_value:
                            # Handle range case
                            tdp_parts = tdp_value.split('.')
                            if len(tdp_parts) == 3:  # e.g., "33.34.8"
                                lower = float(f"{tdp_parts[0]}.{tdp_parts[1]}")
                                upper = float(f"{tdp_parts[0]}.{tdp_parts[2]}")
                                tdp = (lower + upper) / 2
                            else:
                                tdp = float(tdp_value)
                        else:
                            tdp = float(tdp_value)
                        cpu_power_data[row['Name']] = tdp
                    except ValueError:
                        logger.warning(f"Invalid TDP value for CPU {row['Name']}: {row['TDP']}")
            return cpu_power_data
        except Exception as e:
            logger.warning(f"Failed to load CPU power data: {e}")
            return {}

    def calculate_average_tdp(self) -> float:
        if not self.cpu_power_data:
            return 0.0
        return statistics.mean(self.cpu_power_data.values()) / 2  # 50% utilization

    def find_matching_tdp(self) -> Optional[float]:
        # Try direct match
        if self.cpu_brand in self.cpu_power_data:
            return self.cpu_power_data[self.cpu_brand]
        
        # Try matching without frequency
        cpu_name_without_freq = self.cpu_brand.split('@')[0].strip()
        for cpu_name, tdp in self.cpu_power_data.items():
            if cpu_name_without_freq in cpu_name:
                logger.info(f"Matched CPU {self.cpu_brand} to {cpu_name} with TDP {tdp}W")
                return tdp
        
        return None

    @property
    def name(self) -> str:
        return "Generic CPU"

    @property
    def provider_name(self) -> str:
        return self.name

    def fetch(self) -> PowerMeasurementData:
        # Already adjusted for 50% utilization
        now = datetime.now()
        return PowerMeasurementData(
            timestamp=now,
            samples=(
                PowerSample(
                    observed_at=now,
                    domain=PowerDomain.CPU,
                    device_id="cpu:generic",
                    source="generic_cpu",
                    scope=PowerScope.DEVICE_TOTAL,
                    watts=self.tdp,
                    label=self.cpu_brand,
                ),
            ),
        )

    def shutdown(self):
        pass
