from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Generic, TypeVar

# Define the generic type for the payload
TData = TypeVar('TData')

# 1. Base Provider Interface
class DataProvider(ABC, Generic[TData]):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def fetch(self) -> TData:
        pass

    @abstractmethod
    def shutdown(self) -> None:
        pass

@dataclass(frozen=True)
class MeasurementData:
    timestamp: datetime
