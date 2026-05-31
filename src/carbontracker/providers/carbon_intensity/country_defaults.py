from typing import Dict

# Source: Our World in Data / Ember (2023)
# Global average carbon intensity of electricity generation
GLOBAL_AVERAGE_INTENSITY: float = 475.0

# Country ISO 3166-1 alpha-2 codes mapped to carbon intensity (gCO2eq/kWh)
COUNTRY_INTENSITY_DEFAULTS: Dict[str, float] = {
    "DK": 166.0,
    "SE": 45.0,
    "NO": 29.0,
    "FR": 85.0,
    "DE": 385.0,
    "US": 390.0,
    "GB": 258.0,
    "CN": 555.0,
    "IN": 632.0,
    "AU": 510.0,
    "JP": 462.0,
    "BR": 75.0,
    "CA": 120.0,
    # Can be expanded with more countries
}

# Mapping of cloud regions to country codes for fallback
CLOUD_REGION_TO_COUNTRY: Dict[str, str] = {
    "aws:us-east-1": "US",
    "aws:us-west-1": "US",
    "aws:us-west-2": "US",
    "aws:eu-west-1": "IE", # Ireland
    "aws:eu-central-1": "DE",
    "aws:eu-north-1": "SE",
    "gcp:europe-west1": "BE",
    "gcp:europe-west4": "NL",
    "gcp:us-central1": "US",
    "azure:westeurope": "NL",
    "azure:northeurope": "IE",
    "azure:eastus": "US",
}
