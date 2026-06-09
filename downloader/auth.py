"""Instaloader authentication helpers."""

from contextlib import closing
from pathlib import Path
from platform import system
from sqlite3 import OperationalError, connect
from typing import Optional, Union

import instaloader

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


def import_session(
    cookiefile: Union[str, Path],
    instaloader_instance: instaloader.Instaloader,
) -> instaloader.Instaloader:
    """Import Instagram session from Firefox cookies.

    Args:
        cookiefile: Path to Firefox cookies.sqlite file.
        instaloader_instance: Instaloader instance to inject cookies into.

    Returns:
        Authenticated Instaloader instance with username set.

    Raises:
        RuntimeError: If not logged in to Instagram in Firefox.
    """

    log(f"Using cookies from {cookiefile}.")
    cookie_uri = f"{Path(cookiefile).as_uri()}?immutable=1"
    with closing(connect(cookie_uri, uri=True)) as conn:
        try:
            cookie_data = conn.execute(
                "SELECT name, value FROM moz_cookies "
                "WHERE baseDomain='instagram.com'"
            ).fetchall()
        except OperationalError:
            cookie_data = conn.execute(
                "SELECT name, value FROM moz_cookies "
                "WHERE host LIKE '%instagram.com'"
            ).fetchall()
        instaloader_instance.context._session.cookies.update(dict(cookie_data))

    username = instaloader_instance.test_login()
    if not username:
        raise RuntimeError(
            "Not logged in. Are you logged in successfully in Firefox?"
        )
    log(f"Imported session cookie for {username}.")
    instaloader_instance.context.username = username
    return instaloader_instance
