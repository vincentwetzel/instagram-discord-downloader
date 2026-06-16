"""Firefox cookie location utilities."""

from contextlib import closing
from pathlib import Path
from platform import system
from sqlite3 import OperationalError, connect
from typing import Optional, Union

from downloader.logging_utils import log

DEFAULT_COOKIEFILE_PATTERNS: dict[str, str] = {
    "Windows": "AppData/Roaming/Mozilla/Firefox/Profiles/*/cookies.sqlite",
    "Darwin": "Library/Application Support/Firefox/Profiles/*/cookies.sqlite",
}


def get_cookiefile() -> Optional[Path]:
    """Locate Firefox cookies.sqlite file for cookie extraction.

    Returns:
        Path to cookies.sqlite file, or None if not found.
    """

    cookiefile_pattern = DEFAULT_COOKIEFILE_PATTERNS.get(
        system(),
        ".mozilla/firefox/*/cookies.sqlite",
    )
    cookiefiles = list(Path.home().glob(cookiefile_pattern))
    if not cookiefiles:
        return None

    # Sort by modification time to ensure we extract from the most recently active Firefox profile
    cookiefiles.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return cookiefiles[0]
