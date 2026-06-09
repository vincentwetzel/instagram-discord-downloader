"""Configuration loading for the downloader."""

from configparser import ConfigParser
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union


@dataclass(frozen=True)
class DownloaderConfig:
    """Instagram credentials used by the downloader.

    Args:
        ig_name: Instagram username to use for authentication and downloads.
        password: Optional Instagram password.
    """

    ig_name: str
    password: Optional[str]


def load_downloader_config(path: Union[str, Path] = "settings.ini") -> DownloaderConfig:
    """Load downloader configuration from an INI file.

    Args:
        path: Path to the settings file.

    Returns:
        Parsed downloader configuration.
    """

    config = ConfigParser()
    config.read(Path(path))

    ig_name = config.get("Credentials", "ig_name", fallback="")
    if not ig_name or ig_name == "your_instagram_username":
        raise ValueError(f"Please configure a valid 'ig_name' in {path}.")

    password = config.get("Credentials", "ig_pw", fallback=None)
    if password == "your_instagram_password":
        password = None

    return DownloaderConfig(
        ig_name=ig_name,
        password=password,
    )
