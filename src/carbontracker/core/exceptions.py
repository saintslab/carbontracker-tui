class CarbonTrackerError(Exception):
    """Base class for all carbontracker exceptions."""
    pass

class ProviderError(CarbonTrackerError):
    """Base class for errors related to data providers."""
    pass

class ProviderUnavailableError(ProviderError):
    """Raised when a provider's hardware or API is not present or supported on this system."""
    pass

class ProviderPermissionError(ProviderError):
    """Raised when a provider exists, but we lack permissions to read from it (e.g., Intel RAPL)."""
    pass

class ProviderConfigError(ProviderError):
    """Raised when the user provided invalid configuration for a provider (e.g., missing API key)."""
    pass

class APIError(ProviderError):
    """Raised when an external API call fails (e.g., network timeout, 5xx error)."""
    pass

class GuardTriggeredError(CarbonTrackerError):
    """Raised when a budget guard triggers a stop action in python mode."""
    pass

class WrongModeError(CarbonTrackerError):
    """Raised when a budget guard triggers a stop action in python mode."""
    pass
