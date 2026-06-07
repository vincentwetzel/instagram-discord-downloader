"""Instaloader authentication helpers."""

from glob import glob
from os.path import expanduser
from platform import system
from sqlite3 import OperationalError, connect
from typing import Optional

import instaloader

from downloader.logging_utils import log


def get_cookiefile() -> Optional[str]:
    """Locate Firefox cookies.sqlite file for cookie extraction.

    Returns:
        Path to cookies.sqlite file, or None if not found.
    """

    default_cookiefile: dict[str, str] = {
        "Windows": "~/AppData/Roaming/Mozilla/Firefox/Profiles/*/cookies.sqlite",
        "Darwin": "~/Library/Application Support/Firefox/Profiles/*/cookies.sqlite",
    }
    cookiefile_pattern = default_cookiefile.get(
        system(),
        "~/.mozilla/firefox/*/cookies.sqlite",
    )
    cookiefiles = glob(expanduser(cookiefile_pattern))
    if not cookiefiles:
        return None
    return cookiefiles[0]


def import_session(
    cookiefile: str,
    instaloader_instance: instaloader.Instaloader,
) -> instaloader.Instaloader:
    """Import Instagram session from Firefox cookies.

    Args:
        cookiefile: Path to Firefox cookies.sqlite file.
        instaloader_instance: Instaloader instance to inject cookies into.

    Returns:
        Authenticated Instaloader instance with username set.

    Raises:
        SystemExit: If not logged in to Instagram in Firefox.
    """

    log(f"Using cookies from {cookiefile}.")
    conn = connect(f"file:{cookiefile}?immutable=1", uri=True)
    try:
        try:
            cookie_data = conn.execute(
                "SELECT name, value FROM moz_cookies "
                "WHERE baseDomain='instagram.com'"
            )
        except OperationalError:
            cookie_data = conn.execute(
                "SELECT name, value FROM moz_cookies "
                "WHERE host LIKE '%instagram.com'"
            )
        instaloader_instance.context._session.cookies.update(cookie_data)
    finally:
        conn.close()

    username = instaloader_instance.test_login()
    if not username:
        raise SystemExit(
            "Not logged in. Are you logged in successfully in Firefox?"
        )
    log(f"Imported session cookie for {username}.")
    instaloader_instance.context.username = username
    return instaloader_instance
