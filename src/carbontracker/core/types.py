from dataclasses import dataclass
from enum import Enum
from typing import Union


class Component(str, Enum):
    CPU = "cpu"
    GPU = "gpu"
    RAM = "ram"


class BreachAction(str, Enum):
    """
    BreachAction describes the action executed by carbontracker on budget breach
        STOP: Stops the subprocess or training run by raising an error
        LOG: Logs a warning to the output event stream
        Callback: Calls the supplied Callback stream

    If callback function is supplied, it will overwrite the BreachAction to CALLBACK

    """

    LOG = "log"
    STOP = "stop"
    CALLBACK = "callback"
    PASS = "pass"


class IntensityMethod(str, Enum):
    """
    IntensityMethod describes the method which is used for fetch carbonintensity
        AUTO: Denotes automatically selects the best intensity estimate based on the config. API -> Location based average -> World Average
        ELECTRICITY_MAPS: Uses the electricityMaps API
        STATIC: Uses constant static input that must be supplied by the user
    """

    AUTO = "auto"
    ELECTRICITY_MAPS = "electricity_maps"
    STATIC = "static"


@dataclass(frozen=True)
class GeoLocation:
    latitude: float
    longitude: float


@dataclass(frozen=True)
class CloudRegion:
    provider: str  # e.g., 'aws', 'gcp', 'azure'
    region: str  # e.g., 'eu-west-1'


@dataclass(frozen=True)
class ElectricityMapsZone:
    """
    Native Electricity Maps zone location.
    """

    zone_id: str
    zone_name: str | None = None
    country_code: str | None = None
    display_name: str | None = None
    tier: str | None = None
    is_commercially_available: bool | None = None

    def __post_init__(self) -> None:
        zone_id = str(self.zone_id).strip()
        if not zone_id:
            raise ValueError("zone_id must be a non-empty string")
        object.__setattr__(self, "zone_id", zone_id)


@dataclass(frozen=True)
class ElectricityMapsDataCenter:
    """
    Native Electricity Maps data-center location.
    """

    provider: str
    region: str
    zone_id: str | None = None
    display_name: str | None = None
    status: str | None = None

    def __post_init__(self) -> None:
        provider = str(self.provider).strip()
        region = str(self.region).strip()
        if not provider:
            raise ValueError("provider must be a non-empty string")
        if not region:
            raise ValueError("region must be a non-empty string")
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "region", region)
        if self.zone_id is not None:
            zone_id = str(self.zone_id).strip()
            object.__setattr__(self, "zone_id", zone_id or None)


@dataclass(frozen=True)
class ElectricityMapsGridZone:
    """
    Legacy Electricity Maps grid zone location.

    New code should use ElectricityMapsZone. This type remains temporarily
    for backwards-compatible config and event decoding.
    """

    zone_id: str  # e.g., 'DK-DK1' or 'US-CAL-CISO' useful for electricityMaps

    def __post_init__(self) -> None:
        zone_id = str(self.zone_id).strip()
        if not zone_id:
            raise ValueError("zone_id must be a non-empty string")
        object.__setattr__(self, "zone_id", zone_id)


@dataclass(frozen=True)
class CountryCode:
    country_code: str  # e.g., 'DK', 'US'


Location = (
    GeoLocation
    | CloudRegion
    | ElectricityMapsZone
    | ElectricityMapsDataCenter
    | ElectricityMapsGridZone
    | CountryCode
)
