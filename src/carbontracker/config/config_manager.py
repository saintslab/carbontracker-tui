import os
from pathlib import Path
import tempfile
from typing import Any, Dict, Optional

try:
    import tomllib as tomli
except ModuleNotFoundError:
    import tomli
import tomli_w
from pydantic import BaseModel, ConfigDict, Field

from carbontracker.config.location_config import location_from_config, location_to_config
from carbontracker.core.types import Location

GLOBAL_CONFIG_DIR = Path.home() / ".config" / "carbontracker"
GLOBAL_CONFIG_FILE = GLOBAL_CONFIG_DIR / "config.toml"
LOCAL_CONFIG_DIR = Path(".carbontracker")
LOCAL_CONFIG_FILE = LOCAL_CONFIG_DIR / "config.toml"


class GlobalConfig(BaseModel):
    """
    Stored at ~/.config/carbontracker/config.toml (chmod 600).
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    api_keys: Dict[str, str] = Field(default_factory=dict)
    default_location: Optional[Location] = None
    default_pue: Optional[float] = None


def get_global_config_dir() -> Path:
    return Path.home() / ".config" / "carbontracker"


def get_global_config_file() -> Path:
    return get_global_config_dir() / "config.toml"


def get_local_config_dir() -> Path:
    return Path.cwd() / ".carbontracker"


def get_local_config_file() -> Path:
    return get_local_config_dir() / "config.toml"


def _read_toml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, "rb") as f:
            return tomli.load(f)
    except Exception as e:
        import logging
        logging.getLogger("carbontracker").warning(f"Failed to read {path}: {e}")
        return {}


def _write_toml(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            tomli_w.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


def load_global_config() -> GlobalConfig:
    data = _read_toml(get_global_config_file())
    if "default_location" in data:
        data["default_location"] = location_from_config(data["default_location"])
    try:
        return GlobalConfig.model_validate(data)
    except Exception:
        return GlobalConfig()


def save_global_config(config: GlobalConfig) -> None:
    data: Dict[str, Any] = {}
    if config.api_keys:
        data["api_keys"] = dict(config.api_keys)
    if config.default_location is not None:
        data["default_location"] = location_to_config(config.default_location)
    if config.default_pue is not None:
        data["default_pue"] = config.default_pue
    global_config_file = get_global_config_file()
    _write_toml(global_config_file, data)
    # Enforce strict 600 permissions for secure API key storage
    try:
        os.chmod(global_config_file, 0o600)
    except Exception:
        pass


def load_local_config() -> Dict[str, Any]:
    data = _read_toml(get_local_config_file())
    if "location" in data:
        data["location"] = location_from_config(data["location"])
    return data


def resolve_overrides(**user_kwargs: Any) -> Dict[str, Any]:
    """
    Resolution pipeline:
    1. GlobalConfig (PUE, Location, API Keys)
    2. LocalConfig
    3. Env Vars
    4. User kwargs
    Returns a flat dictionary that can be passed as **kwargs to SessionConfig.
    """
    global_cfg = load_global_config()
    local_cfg = load_local_config()

    overrides: Dict[str, Any] = {}

    # 1. Apply Global Config
    if global_cfg.default_pue is not None:
        overrides["pue"] = global_cfg.default_pue
    if global_cfg.default_location is not None:
        overrides["location"] = global_cfg.default_location
    if global_cfg.api_keys:
        overrides["api_keys"] = global_cfg.api_keys

    # 2. Apply Local Config
    overrides.update(local_cfg)

    # 3. Apply Environment Variables
    if "CARBONTRACKER_API_KEY" in os.environ:
        if "api_keys" not in overrides:
            overrides["api_keys"] = {}
        overrides["api_keys"]["electricity_maps"] = os.environ["CARBONTRACKER_API_KEY"]
    if "CARBONTRACKER_PUE" in os.environ:
        try:
            overrides["pue"] = float(os.environ["CARBONTRACKER_PUE"])
        except ValueError:
            pass

    # 4. Apply user overrides (only non-None / explicitly set)
    for k, v in user_kwargs.items():
        if v is not None:
            if k == "api_keys":
                merged_api_keys = dict(overrides.get("api_keys") or {})
                merged_api_keys.update(v)
                overrides["api_keys"] = merged_api_keys
            else:
                overrides[k] = v

    return overrides
