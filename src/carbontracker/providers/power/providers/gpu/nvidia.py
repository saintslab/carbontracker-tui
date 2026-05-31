"""Utilities to query NVIDIA GPUs.

This module provides utilities to query NVIDIA GPUs using NVIDIA Management
Library (NVML). It is important to run nvmlInit() before any queries are made
and nvmlShutdown() after all queries are finished. For performance, it is
recommended to run nvmlInit() and nvmlShutdown() as few times as possible, e.g.
by running queries in batches (initializing and shutdown after each query can
result in more than a 10x slowdown).
"""

import sys
import os
from datetime import datetime
from typing import List, Union

from carbontracker.core.exceptions import ProviderUnavailableError, ProviderError
from carbontracker.core.profiling import PowerDomain, PowerSample, PowerScope
from carbontracker.providers.data_provider import DataProvider
from carbontracker.providers.power.power_provider import PowerMeasurementData


class NvidiaGPU(DataProvider[PowerMeasurementData]):
    def __init__(self, pids: List[int]):
        try:
            import pynvml
        except ModuleNotFoundError as e:
            raise ProviderUnavailableError(
                "NVIDIA GPU tracking requires the optional 'gpu' extra: "
                "pip install 'carbontracker-tui[gpu]'"
            ) from e

        self._pynvml = pynvml
        self.pids = pids
        self.devices_by_pid = bool(pids)
        self._handles = []
        
        try:
            self._pynvml.nvmlInit()
            if self.devices_by_pid:
                self._handles = self._get_handles_by_pid()
            else:
                self._handles = self._get_handles()
                
            if len(self._handles) == 0:
                self._pynvml.nvmlShutdown()
                raise ProviderUnavailableError("No NVIDIA GPUs found.")
        except self._pynvml.NVMLError as e:
            raise ProviderUnavailableError(f"NVML Initialization failed: {e}")

        # Cache names
        self._names = []
        self._device_ids = []
        for handle in self._handles:
            name = self._pynvml.nvmlDeviceGetName(handle)
            if sys.version_info < (3, 10) and isinstance(name, bytes):
                name = name.decode()
            self._names.append(name)
            self._device_ids.append(f"gpu:{self._pynvml.nvmlDeviceGetIndex(handle)}")

    @property
    def name(self) -> str:
        return "Nvidia NVML GPU"

    def fetch(self) -> PowerMeasurementData:
        """Retrieves instantaneous power usages (W) of all GPUs in a list.

        Note:
            Requires NVML to be initialized.
        """
        now = datetime.now()
        samples = []

        for device_id, name, handle in zip(self._device_ids, self._names, self._handles):
            try:
                # Retrieves power usage in mW, divide by 1000 to get in W.
                power_usage = self._pynvml.nvmlDeviceGetPowerUsage(handle) / 1000
                samples.append(
                    PowerSample(
                        observed_at=now,
                        domain=PowerDomain.GPU,
                        device_id=device_id,
                        source="nvml",
                        scope=PowerScope.DEVICE_TOTAL,
                        watts=power_usage,
                        label=name,
                    )
                )
            except self._pynvml.NVMLError:
                raise ProviderError("Failed to retrieve GPU power usage via NVML.")
                
        return PowerMeasurementData(
            timestamp=now,
            samples=tuple(samples),
        )

    def shutdown(self):
        self._pynvml.nvmlShutdown()
        self._handles = []
        self._names = []
        self._device_ids = []

    def _get_handles(self) -> List:
        """Returns handles of GPUs in slurm job if existent otherwise all
        available GPUs."""
        device_indices = self._slurm_gpu_indices()

        # If we cannot retrieve indices from slurm then we retrieve all GPUs.
        if not device_indices:
            device_count = self._pynvml.nvmlDeviceGetCount()
            device_indices = range(device_count)

        return [self._pynvml.nvmlDeviceGetHandleByIndex(i) for i in device_indices]

    def _slurm_gpu_indices(self) -> Union[List[int], None]:
        """Returns indices of GPUs for the current slurm job if existent.

        Note:
            Relies on the environment variable CUDA_VISIBLE_DEVICES to not
            overwritten. Alternative variables could be SLURM_JOB_GPUS and
            GPU_DEVICE_ORDINAL.
        """
        index_str = os.environ.get("CUDA_VISIBLE_DEVICES")
        try:
            indices = (
                [int(i) for i in index_str.split(",")]
                if index_str is not None
                else None
            )
        except:
            indices = None
        return indices

    def _get_handles_by_pid(self) -> List:
        """Returns handles of GPU running at least one process from PIDS.

        Note:
            GPUs need to have started work before showing any processes.
            Requires NVML to be initialized.
            Bug: Containers need to be started with --pid=host for NVML to show
            processes: https://github.com/NVIDIA/nvidia-docker/issues/179.
        """
        device_count = self._pynvml.nvmlDeviceGetCount()
        devices = []

        for index in range(device_count):
            handle = self._pynvml.nvmlDeviceGetHandleByIndex(index)
            gpu_pids = [
                p.pid
                for p in self._pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
                + self._pynvml.nvmlDeviceGetGraphicsRunningProcesses(handle)
            ]

            if set(gpu_pids).intersection(self.pids):
                devices.append(handle)

        return devices
