"""Compatibility entry point for the Instagram downloader."""

from typing import Optional

from downloader.auth import get_cookiefile, import_session
from downloader.history import (
    init_history_db,
    load_downloaded_shortcodes_db,
    prune_stale_shortcodes_db,
    save_downloaded_shortcode_db,
)
from downloader.logging_utils import log, timestamp
from downloader.session import prompt_for_max_posts, run_download_session
from downloader.version import check_instaloader_version

__all__ = [
    "check_instaloader_version",
    "get_cookiefile",
    "import_session",
    "init_history_db",
    "load_downloaded_shortcodes_db",
    "log",
    "prompt_for_max_posts",
    "prune_stale_shortcodes_db",
    "run_download_session",
    "save_downloaded_shortcode_db",
    "timestamp",
]


if __name__ == "__main__":
    max_posts: Optional[int] = prompt_for_max_posts()
    run_download_session(max_posts)
