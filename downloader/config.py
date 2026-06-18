"""Configuration loading for the downloader."""

from configparser import ConfigParser
from dataclasses import dataclass
from pathlib import Path
from typing import Union


@dataclass(frozen=True)
class DownloaderConfig:
    """Instagram account used by the downloader.

    Args:
        ig_name: Instagram username to use for downloads.
    """

    ig_name: str


def load_downloader_config(path: Union[str, Path] = "settings.ini") -> DownloaderConfig:
    """Load downloader configuration from an INI file.

    Args:
        path: Path to the settings file.

    Returns:
        Parsed downloader configuration.

    Raises:
        ValueError: If no valid per-run Instagram username is configured.
    """

    config = ConfigParser()
    config.read(Path(path))

    ig_name = config.get("Credentials", "ig_name", fallback="").strip()
    if not ig_name or ig_name == "your_instagram_username":
        raise ValueError(f"Please configure a valid 'ig_name' in {path}.")

    if "," in ig_name:
        raise ValueError(
            "Only one Instagram account can be configured per run. "
            f"Please set 'ig_name' in {path} to the account currently active "
            "in Firefox."
        )

    return DownloaderConfig(ig_name=ig_name)
