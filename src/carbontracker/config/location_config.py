from __future__ import annotations

from typing import Any

from carbontracker.core.types import (
    CloudRegion,
    CountryCode,
    ElectricityMapsDataCenter,
    ElectricityMapsGridZone,
    ElectricityMapsZone,
    GeoLocation,
    Location,
)


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return None


def location_to_config(location: Location | None) -> dict[str, object] | None:
    if location is None:
        return None
    if isinstance(location, GeoLocation):
        return {
            "type": "geo_location",
            "latitude": location.latitude,
            "longitude": location.longitude,
        }
    if isinstance(location, CloudRegion):
        return {
            "type": "cloud_region",
            "provider": location.provider,
            "region": location.region,
        }
    if isinstance(location, ElectricityMapsDataCenter):
        data: dict[str, object] = {
            "type": "electricity_maps_data_center",
            "provider": location.provider,
            "region": location.region,
        }
        for key in ("zone_id", "display_name", "status"):
            value = getattr(location, key)
            if value is not None:
                data[key] = value
        return data
    if isinstance(location, ElectricityMapsZone):
        data = {
            "type": "electricity_maps_zone",
            "zone_id": location.zone_id,
        }
        for key in (
            "zone_name",
            "country_code",
            "display_name",
            "tier",
            "is_commercially_available",
        ):
            value = getattr(location, key)
            if value is not None:
                data[key] = value
        return data
    if isinstance(location, ElectricityMapsGridZone):
        return {
            "type": "electricity_maps_zone",
            "zone_id": location.zone_id,
        }
    if isinstance(location, CountryCode):
        return {
            "type": "country_code",
            "country_code": location.country_code,
        }
    raise TypeError(f"Unsupported location type: {type(location).__name__}")


def location_from_config(value: object) -> Location | None:
    if value is None:
        return None
    if isinstance(
        value,
        (
            GeoLocation,
            CloudRegion,
            ElectricityMapsZone,
            ElectricityMapsDataCenter,
            ElectricityMapsGridZone,
            CountryCode,
        ),
    ):
        return value
    if isinstance(value, str):
        return _legacy_location_from_string(value)
    if not isinstance(value, dict):
        return None

    location_type = _str_or_none(value.get("type"))

    if location_type in {"geo_location", "lat_lon"} or (
        location_type is None and {"latitude", "longitude"}.issubset(value)
    ):
        try:
            return GeoLocation(
                latitude=float(value["latitude"]),
                longitude=float(value["longitude"]),
            )
        except (KeyError, TypeError, ValueError):
            return None

    if location_type == "cloud_region":
        provider = _str_or_none(value.get("provider"))
        region = _str_or_none(value.get("region"))
        if provider and region:
            return CloudRegion(provider=provider, region=region)
        return None

    if location_type == "electricity_maps_data_center":
        provider = _str_or_none(value.get("provider"))
        region = _str_or_none(value.get("region"))
        if provider and region:
            return ElectricityMapsDataCenter(
                provider=provider,
                region=region,
                zone_id=_str_or_none(value.get("zone_id") or value.get("zoneKey")),
                display_name=_str_or_none(
                    value.get("display_name") or value.get("displayName")
                ),
                status=_str_or_none(value.get("status")),
            )
        return None

    if location_type in {"electricity_maps_zone", "grid_zone"} or (
        location_type is None and ("zone_id" in value or "zoneKey" in value)
    ):
        zone_id = _str_or_none(value.get("zone_id") or value.get("zoneKey"))
        if zone_id:
            return ElectricityMapsZone(
                zone_id=zone_id,
                zone_name=_str_or_none(value.get("zone_name") or value.get("zoneName")),
                country_code=_str_or_none(
                    value.get("country_code") or value.get("countryCode")
                ),
                display_name=_str_or_none(
                    value.get("display_name") or value.get("displayName")
                ),
                tier=_str_or_none(value.get("tier")),
                is_commercially_available=_bool_or_none(
                    value.get("is_commercially_available")
                    if "is_commercially_available" in value
                    else value.get("isCommerciallyAvailable")
                ),
            )
        return None

    if location_type == "country_code" or (
        location_type is None and "country_code" in value
    ):
        country_code = _str_or_none(value.get("country_code") or value.get("countryCode"))
        if country_code:
            return CountryCode(country_code=country_code.upper())
        return None

    if location_type is None and {"provider", "region"}.issubset(value):
        provider = _str_or_none(value.get("provider"))
        region = _str_or_none(value.get("region"))
        if provider and region:
            return CloudRegion(provider=provider, region=region)

    return None


def _legacy_location_from_string(value: str) -> Location | None:
    raw = value.strip()
    if not raw:
        return None

    if "," in raw:
        parts = raw.split(",")
        if len(parts) == 2:
            try:
                return GeoLocation(
                    latitude=float(parts[0].strip()),
                    longitude=float(parts[1].strip()),
                )
            except ValueError:
                pass

    if ":" in raw:
        provider, region = raw.split(":", 1)
        provider = provider.strip().lower()
        region = region.strip().lower()
        if provider and region:
            return CloudRegion(provider=provider, region=region)

    if "-" in raw:
        return ElectricityMapsZone(zone_id=raw.upper())

    if len(raw) == 2:
        return CountryCode(country_code=raw.upper())

    return CountryCode(country_code=raw.upper())
