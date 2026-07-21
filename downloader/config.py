"""Configuration loading for the downloader."""

from configparser import ConfigParser, NoSectionError, NoOptionError
from dataclasses import dataclass
from pathlib import Path
from typing import Union


@dataclass(frozen=True)
class DownloaderConfig:
    """Configuration for the downloader session.

    Args:
        base_download_path: Optional base path for downloads, with placeholders.
    """

    base_download_path: Optional[str] = None


def load_downloader_config(path: Union[str, Path] = "settings.ini") -> DownloaderConfig:
    """Load downloader configuration from an INI file.

    Args:
        path: Path to the settings file.

    Returns:
        Parsed downloader configuration.
    """

    config = ConfigParser()
    config.read(Path(path))

    base_download_path: Optional[str] = None
    try:
        base_download_path = config.get("Storage", "base_download_path", fallback=None)
    except (NoSectionError, NoOptionError):
        pass # Section or option might not exist, fallback handles it

    return DownloaderConfig(base_download_path=base_download_path)
