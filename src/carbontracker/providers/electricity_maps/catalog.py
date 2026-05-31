from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from carbontracker.core.types import ElectricityMapsDataCenter, ElectricityMapsZone


BASE_URL = "https://api.electricitymap.org/v3"


class ElectricityMapsCatalogError(Exception):
    pass


@dataclass(frozen=True)
class ElectricityMapsCatalog:
    zones: tuple[ElectricityMapsZone, ...]
    data_centers: tuple[ElectricityMapsDataCenter, ...]


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def decode_zones(payload: object) -> tuple[ElectricityMapsZone, ...]:
    if not isinstance(payload, dict):
        raise ElectricityMapsCatalogError("Electricity Maps zones payload must be an object")

    zones: list[ElectricityMapsZone] = []
    for key, value in sorted(payload.items()):
        if not isinstance(value, dict):
            continue
        zone_id = _str_or_none(value.get("zoneKey") or key)
        if not zone_id:
            continue
        zones.append(
            ElectricityMapsZone(
                zone_id=zone_id,
                zone_name=_str_or_none(value.get("zoneName")),
                country_code=_str_or_none(value.get("countryCode")),
                display_name=_str_or_none(value.get("displayName")),
                tier=_str_or_none(value.get("tier")),
                is_commercially_available=value.get("isCommerciallyAvailable")
                if isinstance(value.get("isCommerciallyAvailable"), bool)
                else None,
            )
        )
    return tuple(zones)


def decode_data_centers(payload: object) -> tuple[ElectricityMapsDataCenter, ...]:
    if not isinstance(payload, list):
        raise ElectricityMapsCatalogError(
            "Electricity Maps data-centers payload must be a list"
        )

    data_centers: list[ElectricityMapsDataCenter] = []
    for value in payload:
        if not isinstance(value, dict):
            continue
        provider = _str_or_none(value.get("provider"))
        region = _str_or_none(value.get("region"))
        if not provider or not region:
            continue
        data_centers.append(
            ElectricityMapsDataCenter(
                provider=provider,
                region=region,
                zone_id=_str_or_none(value.get("zoneKey") or value.get("zone_id")),
                display_name=_str_or_none(
                    value.get("displayName") or value.get("display_name")
                ),
                status=_str_or_none(value.get("status")),
            )
        )
    data_centers.sort(key=lambda item: (item.provider, item.region))
    return tuple(data_centers)


def _fetch_json(path: str, timeout_s: float) -> object:
    url = f"{BASE_URL}/{path.lstrip('/')}"
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as response:
            if response.status != 200:
                raise ElectricityMapsCatalogError(
                    f"Electricity Maps catalog returned status {response.status}"
                )
            return json.loads(response.read().decode("utf-8"))
    except ElectricityMapsCatalogError:
        raise
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        raise ElectricityMapsCatalogError(
            f"Failed to fetch Electricity Maps catalog {path}: {exc}"
        ) from exc


def fetch_zones(timeout_s: float = 10.0) -> tuple[ElectricityMapsZone, ...]:
    return decode_zones(_fetch_json("zones", timeout_s=timeout_s))


def fetch_data_centers(
    timeout_s: float = 10.0,
) -> tuple[ElectricityMapsDataCenter, ...]:
    return decode_data_centers(_fetch_json("data-centers", timeout_s=timeout_s))


def fetch_catalog(timeout_s: float = 10.0) -> ElectricityMapsCatalog:
    return ElectricityMapsCatalog(
        zones=fetch_zones(timeout_s=timeout_s),
        data_centers=fetch_data_centers(timeout_s=timeout_s),
    )
