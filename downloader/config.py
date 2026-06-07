"""Configuration loading for the downloader."""

from configparser import ConfigParser
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class DownloaderConfig:
    """Instagram credentials used by the downloader.

    Args:
        ig_name: Instagram username to use for authentication and downloads.
        password: Optional Instagram password.
    """

    ig_name: str
    password: Optional[str]


def load_downloader_config(path: str = "settings.ini") -> DownloaderConfig:
    """Load downloader configuration from an INI file.

    Args:
        path: Path to the settings file.

    Returns:
        Parsed downloader configuration.
    """

    config = ConfigParser()
    config.read(path)
    return DownloaderConfig(
        ig_name=config.get("Credentials", "ig_name", fallback="vincentwetzel"),
        password=config.get("Credentials", "pw", fallback=None),
    )
