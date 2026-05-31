import json
import urllib.request
import urllib.error
from typing import Optional

from carbontracker.config.location_config import location_from_config
from carbontracker.core.types import (
    CloudRegion,
    CountryCode,
    ElectricityMapsDataCenter,
    ElectricityMapsGridZone,
    ElectricityMapsZone,
    GeoLocation,
    Location,
)
from carbontracker.providers.carbon_intensity.intensity_provider import (
    ResolvedLocation
)
from carbontracker.providers.carbon_intensity.country_defaults import CLOUD_REGION_TO_COUNTRY

def geolocate_by_ip() -> Optional[GeoLocation]:
    """
    Attempts to determine the user's geolocation using a public IP-based API.
    Returns GeoLocation if successful, None if it fails.
    This is best-effort and should fail silently to avoid breaking the execution.
    """
    try:
        # Using a free service without API key requirement
        with urllib.request.urlopen("http://ip-api.com/json/", timeout=2.0) as response:
            if response.status == 200:
                data = json.loads(response.read().decode('utf-8'))
                if data.get('status') == 'success':
                    return GeoLocation(
                        latitude=float(data.get('lat')),
                        longitude=float(data.get('lon'))
                    )
    except (urllib.error.URLError, json.JSONDecodeError, ValueError, TypeError):
        # Fail silently
        pass
    
    return None

def resolve_location(raw_location: Optional[str | Location], auto_detect: bool = True) -> ResolvedLocation:
    """
    Parses a raw location string into a concrete Location object, or returns the location if it's already a Location object.
    If raw_location is None and auto_detect is True, attempts IP geolocation.
    """
    if isinstance(
        raw_location,
        (
            GeoLocation,
            CloudRegion,
            ElectricityMapsZone,
            ElectricityMapsDataCenter,
            ElectricityMapsGridZone,
            CountryCode,
        ),
    ):
        return ResolvedLocation(
            location=raw_location,
            source="config",
            raw_input=str(raw_location)
        )
        
    if raw_location:
        location = location_from_config(raw_location)
        if location is not None:
            return ResolvedLocation(
                location=location,
                source="config",
                raw_input=raw_location,
            )

    # 5. No location provided, attempt IP Geolocation if allowed
    if auto_detect:
        geo = geolocate_by_ip()
        if geo:
            return ResolvedLocation(
                location=geo,
                source="geolocation",
                raw_input=None
            )

    # 6. Fallback: Unknown
    return ResolvedLocation(
        location=None,
        source="unknown",
        raw_input=None
    )

def location_to_country(loc: Location) -> Optional[str]:
    """Helper to try to extract a country code from any Location type."""
    if isinstance(loc, CountryCode):
        return loc.country_code
    elif isinstance(loc, (ElectricityMapsZone, ElectricityMapsGridZone)):
        # Many grid zones start with the country code (e.g., DK-DK1 -> DK)
        if '-' in loc.zone_id:
            country = loc.zone_id.split('-')[0]
            if len(country) == 2:
                return country
        if isinstance(loc, ElectricityMapsZone):
            return loc.country_code
    elif isinstance(loc, ElectricityMapsDataCenter):
        if loc.zone_id and "-" in loc.zone_id:
            country = loc.zone_id.split("-")[0]
            if len(country) == 2:
                return country
        if loc.zone_id and len(loc.zone_id) == 2:
            return loc.zone_id
    elif isinstance(loc, CloudRegion):
        key = f"{loc.provider}:{loc.region}"
        return CLOUD_REGION_TO_COUNTRY.get(key)
    # Note: GeoLocation reverse geocoding is omitted here for simplicity,
    # it would require an offline database or an API call.
    return None
