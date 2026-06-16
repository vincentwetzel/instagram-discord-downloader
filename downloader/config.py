"""Configuration loading for the downloader."""

from configparser import ConfigParser
from dataclasses import dataclass
from pathlib import Path
from typing import Union


@dataclass(frozen=True)
class DownloaderConfig:
    """Instagram credentials used by the downloader.

    Args:
        ig_names: List of Instagram usernames to use for downloads.
    """

    ig_names: list[str]


def load_downloader_config(path: Union[str, Path] = "settings.ini") -> DownloaderConfig:
    """Load downloader configuration from an INI file.

    Args:
        path: Path to the settings file.

    Returns:
        Parsed downloader configuration.
    """

    config = ConfigParser()
    config.read(Path(path))

    ig_name_raw = config.get("Credentials", "ig_name", fallback="")
    if not ig_name_raw:
        ig_name_raw = config.get("Credentials", "ig_names", fallback="")

    if not ig_name_raw or ig_name_raw == "your_instagram_username":
        raise ValueError(f"Please configure a valid 'ig_name' or 'ig_names' in {path}.")

    # Parse comma-separated usernames into a structured list
    ig_names = [name.strip() for name in ig_name_raw.split(",") if name.strip()]
    if not ig_names:
        raise ValueError(f"Please configure at least one valid 'ig_name' in {path}.")

    return DownloaderConfig(
        ig_names=ig_names,
    )
